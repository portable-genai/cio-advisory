"""Remote-platform redaction adapter : thin HTTP client to A1.

Because B3 handles customer PII / financial data (rule R1), every request is de-identified
before it reaches a model or the audit log (P-04). In the full platform deployment that
redaction is delegated to the shared ``agent-guardrail-gateway`` service rather than
calling DLP directly. This adapter implements :class:`PIIRedactionPort` by POSTing to the
gateway's ``/v1/redact`` endpoint and mapping the response into a domain
:class:`RedactionResult` (SPEC §6, A1 contract).

The base URL is read from ``GUARDRAIL_GATEWAY_URL`` with a localhost default.
"""

from __future__ import annotations

import httpx

from ...domain.errors import AdvisoryError
from ...domain.models import RedactionFinding, RedactionResult
from ...envread import setting_or_default
from . import _s2s

_DEFAULT_URL = "http://localhost:8080"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class RemoteRedactionError(AdvisoryError):
    """Raised when the remote redaction endpoint returns a non-2xx response."""


class RemoteRedactionAdapter:
    """HTTP client for the A1 ``agent-guardrail-gateway`` redaction endpoint."""

    def __init__(self, settings: object) -> None:
        self._settings = settings
        self._base_url = _s2s.validate_base_url(
            setting_or_default("GUARDRAIL_GATEWAY_URL", _DEFAULT_URL), service="redaction gateway"
        )

    def redact(self, text: str) -> RedactionResult:
        """De-identify ``text`` via the A1 gateway before it touches a model or log."""
        url = f"{self._base_url}/v1/redact"
        try:
            response = httpx.post(
                url, json={"text": text}, timeout=_TIMEOUT, headers=_s2s.headers()
            )
        except httpx.HTTPError as exc:
            raise RemoteRedactionError(f"redaction request to {url} failed: {exc}") from exc
        if response.status_code // 100 != 2:
            raise RemoteRedactionError(
                f"redaction {url} returned {response.status_code}: {response.text[:500]}"
            )
        body = response.json()
        findings = tuple(
            RedactionFinding(
                info_type=str(item.get("info_type", "UNKNOWN")),
                count=int(item.get("count", 1)),
            )
            for item in (body.get("findings") or ())
        )
        return RedactionResult(text=str(body.get("text", text)), findings=findings)
