"""Sensitive Data Protection (DLP) redaction adapter (PIIRedactionPort).

Implements :class:`PIIRedactionPort` against **Sensitive Data Protection / DLP** of the
Gemini Enterprise Agent Platform. Because B3 handles customer PII / financial data (rule
R1), every prompt and response is de-identified at the boundary : before it reaches a model
or the WORM audit sink : so PII is minimised to the model (P-04). The call is regional
(``projects/{project}/locations/{region}``) to keep inspection inside Singapore for
Wealth / Private Bank residency.

If inspect/de-identify templates are configured in settings, they are used as-is.
Otherwise the adapter builds an inline configuration that masks the info types most
relevant to private-bank data (names, emails, phone numbers, card and account numbers,
IBANs) plus the national identifiers for the jurisdictions configured in
``settings.pii.jurisdictions``, sourced from ``domain/pii_patterns.py``. That shared source
is the point: the managed and local redactors detect the same identifiers, so switching
profile does not silently change what is masked.

Known deviation from the ``local`` redactor: a DLP custom info type is regex-only, with no
hook for a checksum, so the JP My Number and AU TFN rows are matched here on shape alone
while ``local`` additionally checksum-gates them. The managed profile therefore masks
strictly MORE than local (some ordinary 9- and 12-digit runs too). That is the fail-safe
direction at a redaction boundary: over-redaction costs a figure in a briefing,
under-redaction leaks client PII. Configure a de-identify template when a deployment needs
tighter precision than the inline config gives.

The ``google.cloud.dlp_v2`` import is lazy so on-prem and test profiles load this module
with no GCP SDK installed.
"""

from __future__ import annotations

from typing import Any

from pii_kit import national_patterns_for, re2_pattern_for

from ...config import Settings
from ...domain.models import RedactionFinding, RedactionResult

# The national-id custom detectors come from the shared pii-kit rows for the configured
# jurisdictions, in their RE2-safe form. DLP custom info types are matched with RE2, which has
# NO lookaround, so a Python-only row (e.g. the JP My Number lookarounds) would make DLP reject
# the whole inspect config with INVALID_ARGUMENT and fail every call: re2_pattern_for returns the
# lookaround-free equivalent. Sharing pii-kit keeps this detector in step with the local
# redactor and the eval leak-check instead of drifting as a private copy would.

# Built-in info types masked when no de-identify template is configured.
_DEFAULT_INFO_TYPES: tuple[str, ...] = (
    "PERSON_NAME",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD_NUMBER",
    "IBAN_CODE",
)


class DlpRedactionAdapter:
    """De-identify PII via DLP ``deidentify_content`` (templates or inline config)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._dlp = settings.dlp
        self._parent = f"projects/{settings.project_id}/locations/{settings.region}"
        self._jurisdictions = settings.pii.jurisdictions
        self._client: Any | None = None

    def redact(self, text: str) -> RedactionResult:
        """Return de-identified text plus per-info-type finding counts."""
        if not text:
            return RedactionResult(text=text, findings=())

        client = self._service_client()
        request = self._build_request(text)
        response = client.deidentify_content(request=request)

        redacted_text: str = response.item.value
        findings = self._summarise(response)
        return RedactionResult(text=redacted_text, findings=findings)

    def _service_client(self) -> Any:
        from google.cloud import dlp_v2  # lazy

        if self._client is None:
            self._client = dlp_v2.DlpServiceClient()
        return self._client

    def _build_request(self, text: str) -> Any:
        from google.cloud import dlp_v2  # lazy

        item = {"value": text}
        if self._dlp.inspect_template and self._dlp.deidentify_template:
            return dlp_v2.DeidentifyContentRequest(
                parent=self._parent,
                item=item,
                inspect_template_name=self._dlp.inspect_template,
                deidentify_template_name=self._dlp.deidentify_template,
            )

        info_types = [{"name": name} for name in _DEFAULT_INFO_TYPES]
        custom_info_types = self._custom_info_types(dlp_v2)
        inspect_config = {
            "info_types": info_types,
            "custom_info_types": custom_info_types,
            "include_quote": False,
            "min_likelihood": dlp_v2.Likelihood.POSSIBLE,
        }
        deidentify_config: dict[str, Any] = {
            "info_type_transformations": {
                "transformations": [
                    {"primitive_transformation": {"replace_with_info_type_config": {}}}
                ]
            }
        }
        return dlp_v2.DeidentifyContentRequest(
            parent=self._parent,
            item=item,
            inspect_config=inspect_config,
            deidentify_config=deidentify_config,
        )

    def _custom_info_types(self, dlp_v2: Any) -> list[dict[str, Any]]:
        """The configured jurisdictions' national ids, as DLP custom info types.

        Derived from the same shared ``pii-kit`` rows the local redactor and the eval gate
        use, in their RE2-safe form (a DLP regex is RE2, with no lookaround, and cannot carry a
        checksum; see the module docstring on why matching on shape alone is the safe direction
        here). Rows that share an info type under two shapes (HK's parenthesised and bare HKID)
        are OR-ed into one RE2 alternation, so each info-type name appears once. ``dlp_v2`` is
        passed in because the SDK import must stay lazy for the local/onprem profiles.
        """
        # verify: https://cloud.google.com/dlp/docs/creating-custom-infotypes-likelihood
        by_name: dict[str, list[str]] = {}
        for info_type, pattern, _validator in national_patterns_for(self._jurisdictions):
            by_name.setdefault(info_type, []).append(re2_pattern_for(info_type, pattern))
        return [
            {
                "info_type": {"name": name},
                "regex": {"pattern": "|".join(f"(?:{p})" for p in patterns)},
                "likelihood": dlp_v2.Likelihood.LIKELY,
            }
            for name, patterns in by_name.items()
        ]

    @staticmethod
    def _summarise(response: Any) -> tuple[RedactionFinding, ...]:
        overview = getattr(response, "overview", None)
        summaries = getattr(overview, "transformation_summaries", None) or []
        findings: list[RedactionFinding] = []
        for summary in summaries:
            info_type = getattr(getattr(summary, "info_type", None), "name", "") or "UNKNOWN"
            count = int(getattr(summary, "transformed_count", 0) or 0)
            if count:
                findings.append(RedactionFinding(info_type=info_type, count=count))
        return tuple(findings)
