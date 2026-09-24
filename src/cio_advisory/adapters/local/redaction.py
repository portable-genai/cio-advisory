"""Local PII redaction adapter (PIIRedactionPort): regex de-identification.

The ``local`` profile's stand-in for **Sensitive Data Protection / DLP**: masks the national
identifiers for the configured jurisdiction(s) plus universal email/phone with deterministic
regexes, returning findings. B3 handles customer PII, so this redaction runs at the boundary
(P-04, rule R1) before any text reaches a model or an audit sink. The pattern set is
jurisdiction-driven (``settings.pii.jurisdictions``, default SG/HK/JP/AU) so a non-APAC
deployment detects its own identifiers by config, not a code change. There is no Google
emulator for DLP, so this path is unconditional and imports no google-cloud package.

The rows and their checksum validators come from the shared ``pii-kit`` package, NOT a local
copy: this redactor, the DLP adapter and the eval leak-check all read the SAME rows, so a
pattern fix is a version bump rather than a copy that drifts out of sync (a copy that drifts
narrows rows silently, and a narrowed row leaks identifiers no gate can see).

Rows that carry a checksum validator (JP My Number, AU TFN) mask only genuine identifiers,
so ordinary digit runs (portfolio valuations, account references) are left intact rather than
falsely redacted out of the prose the model reasons over. B3 has no bank-account row, so the
universal email/phone rows lead and the national-id rows follow with no bare-digit catch-all
and therefore no row-ordering hazard.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from pii_kit import UNIVERSAL_PATTERNS, national_patterns_for
from pii_kit.patterns import Pattern

from ...config import Settings
from ...domain.models import RedactionFinding, RedactionResult

#: The phone rows (universal and SG) would take an eight-digit amount for a phone number:
#: "a SGD 90000000 portfolio" reached the model as "a SGD [SG_PHONE] portfolio". A match
#: directly after a currency code or symbol is an amount, so those rows leave it intact.
_PHONE_INFO_TYPES = frozenset({"PHONE_NUMBER", "SG_PHONE"})
_AFTER_A_CURRENCY = re.compile(
    r"(?:[$€£¥]|\b(?:SGD|USD|HKD|AUD|JPY|EUR|GBP|CNY|CHF|S\$|US\$|HK\$|A\$))\s?$"
)


class LocalRegexRedactionAdapter:
    """Mask the configured jurisdictions' national ids + email/phone, like DLP de-identify."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Universal rows first, then the national-id rows for the configured jurisdictions.
        # B3 has no account row, so this order carries no subsumption hazard.
        self._patterns: tuple[Pattern, ...] = (
            *UNIVERSAL_PATTERNS,
            *tuple(national_patterns_for(settings.pii.jurisdictions)),
        )

    def redact(self, text: str) -> RedactionResult:
        redacted = text
        counts: dict[str, int] = {}
        for info_type, pattern, validator in self._patterns:

            def _sub(
                m: re.Match[str],
                _it: str = info_type,
                _val: Callable[[str], bool] | None = validator,
            ) -> str:
                if _val is not None and not _val(m.group(0)):
                    return m.group(0)  # checksum fail: not a real identifier, leave it intact
                if _it in _PHONE_INFO_TYPES and _AFTER_A_CURRENCY.search(m.string, 0, m.start()):
                    return m.group(0)  # an amount after a currency marker, not a phone number
                counts[_it] = counts.get(_it, 0) + 1
                return f"[{_it}]"

            redacted = pattern.sub(_sub, redacted)
        findings = tuple(RedactionFinding(info_type=it, count=n) for it, n in counts.items() if n)
        return RedactionResult(text=redacted, findings=findings)
