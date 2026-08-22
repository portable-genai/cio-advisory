"""PII redaction adapter tests (the redact-before-everything boundary, R1, P-04).

Prove the jurisdiction-driven local redactor masks the advisory desk's APAC national
identifiers (SG NRIC, HK HKID, JP My Number, AU TFN) plus universal email/phone; that the
checksum-gated rows mask only genuine identifiers; and that an unknown jurisdiction degrades
safely to email/phone only rather than raising. Same pattern source as the eval gate, so what
these tests mask is exactly what the gate detects.

Worth stating what this adapter guards, because the pipeline's redacted surface is narrow: a
client is referenced by an opaque id, and ``advisory_service._brief_inner`` redacts exactly
that id before it reaches the guardrail or the audit sink. A client reference is the field a
real integration mis-keys onto an NRIC, and it is the one client-controlled string on the
path, so these masks are what stand between a mis-keyed id and a WORM record.
"""

from __future__ import annotations

from cio_advisory.adapters.local.redaction import LocalRegexRedactionAdapter
from cio_advisory.config import PiiSettings, Settings

# FICTIONAL identifiers. The JP My Number and AU TFN carry VALID check digits; the paired
# "_INVALID" values share the shape but fail the checksum, so they must survive unmasked.
_SG_NRIC = "S1234567A"
_HK_HKID = "A123456(3)"
_JP_MYNUMBER_VALID = "123456789018"
_JP_MYNUMBER_INVALID = "123456789012"
_AU_TFN_VALID = "123 456 782"
_AU_TFN_INVALID = "123 456 781"
_EMAIL = "ops@example.com"
_PHONE = "+81 90 1234 5678"


def _redactor(*jurisdictions: str) -> LocalRegexRedactionAdapter:
    return LocalRegexRedactionAdapter(Settings(pii=PiiSettings(jurisdictions=jurisdictions)))


def test_default_jurisdictions_are_the_apac_markets() -> None:
    # The pack the assistant ships with; the eval gate's golden clients mirror exactly these.
    assert Settings().pii.jurisdictions == ("SG", "HK", "JP", "AU")


def test_sg_nric_and_email_and_phone_masked() -> None:
    r = _redactor("SG", "HK", "JP", "AU")
    out = r.redact(f"client-000042 NRIC {_SG_NRIC}, email {_EMAIL}, phone {_PHONE}")
    assert _SG_NRIC not in out.text
    assert _EMAIL not in out.text
    assert _PHONE not in out.text
    info = {f.info_type for f in out.findings}
    assert {"SG_NRIC_FIN", "EMAIL_ADDRESS", "PHONE_NUMBER"} <= info


def test_hk_hkid_masked() -> None:
    r = _redactor("HK")
    out = r.redact(f"client-000113 HKID {_HK_HKID}")
    assert _HK_HKID not in out.text
    assert "HK_HKID" in {f.info_type for f in out.findings}


def test_jp_my_number_masked_only_when_checksum_valid() -> None:
    r = _redactor("JP")
    valid = r.redact(f"My Number {_JP_MYNUMBER_VALID} on file.")
    assert _JP_MYNUMBER_VALID not in valid.text
    assert "[JP_MY_NUMBER]" in valid.text
    assert {"JP_MY_NUMBER"} <= {f.info_type for f in valid.findings}
    # A 12-digit run with a wrong check digit is NOT a My Number: it must survive intact.
    invalid = r.redact(f"Account reference {_JP_MYNUMBER_INVALID} is not an id.")
    assert _JP_MYNUMBER_INVALID in invalid.text
    assert not invalid.findings


def test_au_tfn_masked_only_when_checksum_valid() -> None:
    r = _redactor("AU")
    valid = r.redact(f"TFN {_AU_TFN_VALID} recorded.")
    assert _AU_TFN_VALID not in valid.text
    assert "AU_TFN" in {f.info_type for f in valid.findings}
    # A 9-digit run with a wrong check digit is NOT a TFN: it must survive intact.
    invalid = r.redact(f"Mandate {_AU_TFN_INVALID} settled.")
    assert _AU_TFN_INVALID in invalid.text
    assert not invalid.findings


def test_ordinary_briefing_figures_survive() -> None:
    """Figures that fail their checksum reach the model intact.

    The regression behind the checksum gating. Without a validator on the AU TFN (9 digits)
    and JP My Number (12 digits) rows, the bare shapes would mask portfolio valuations and
    account references out of the prose the model reasons over.
    """
    r = _redactor("SG", "HK", "JP", "AU")
    prose = (
        "Global Equity Fund valued at 400000000 against a mandate of 260000000; "
        "custody reference 100000000, settlement instruction 200000000001, "
        "weight 0.35 and yield 4.0 percent."
    )
    out = r.redact(prose)
    assert out.text == prose
    assert not out.findings


def test_checksum_gating_reduces_false_positives_without_eliminating_them() -> None:
    """A figure that satisfies the checksum by coincidence IS masked. Known and accepted.

    Roughly one 9-digit run in eleven passes the TFN mod-11 check by chance, and round
    numbers are well represented among them, so this is not a corner case in a book of
    valuations. Pinned deliberately rather than left as a surprise: over-redaction is the
    safe direction here (a masked figure degrades a narration, a missed identifier is a
    breach), and the honest fix is context words on the shared pack, not a looser rule on a
    safety boundary. See the note in ``domain/pii_patterns.py``.
    """
    r = _redactor("AU")
    out = r.redact("Mandate drawn to 250000000 at year end.")  # valid TFN checksum by chance
    assert "[AU_TFN]" in out.text
    assert "AU_TFN" in {f.info_type for f in out.findings}


def test_all_market_ids_masked_together() -> None:
    r = _redactor("SG", "HK", "JP", "AU")
    out = r.redact(f"{_SG_NRIC} / {_HK_HKID} / {_JP_MYNUMBER_VALID} / {_AU_TFN_VALID} / {_EMAIL}")
    for raw in (_SG_NRIC, _HK_HKID, _JP_MYNUMBER_VALID, _AU_TFN_VALID, _EMAIL):
        assert raw not in out.text
    assert out.redacted


def test_unknown_jurisdiction_degrades_to_email_and_phone_only() -> None:
    r = _redactor("XX")  # unknown ISO code: no national-id pack, universal PII still applies
    out = r.redact(f"NRIC {_SG_NRIC}, email {_EMAIL}")
    # The national id survives (its pack was not configured) ...
    assert _SG_NRIC in out.text
    # ... but the universal email is still masked, and the adapter never raises.
    assert _EMAIL not in out.text
    assert {f.info_type for f in out.findings} == {"EMAIL_ADDRESS"}
