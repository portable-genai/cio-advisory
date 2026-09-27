"""Remote-platform guardrail adapter : thin HTTP client to A1.

When B3 runs inside the full Gemini Enterprise Agent Platform deployment, guardrail
screening is delegated to the shared ``agent-guardrail-gateway`` service (backed by
Model Armor + Sensitive Data Protection / DLP) rather than calling Model Armor directly.
This adapter implements :class:`GuardrailPort` by POSTing to that gateway's
``/v1/guardrail/screen`` endpoint and parsing the response back into the domain
:class:`GuardrailVerdict` (SPEC §6, A1 contract).

The adapter follows the construction convention ``__init__(self, settings)`` and reads its
base URL from ``GUARDRAIL_GATEWAY_URL`` (sensible localhost default), so nothing GCP-specific
is required to construct or exercise it.
"""

from __future__ import annotations

import httpx

from ...domain.errors import AdvisoryError
from ...domain.models import (
    Direction,
    GuardrailCategory,
    GuardrailFinding,
    GuardrailVerdict,
)
from ...domain.serialization import to_jsonable
from ...envread import setting_or_default
from . import _s2s

_DEFAULT_URL = "http://localhost:8080"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class RemoteGuardrailError(AdvisoryError):
    """Raised when the remote guardrail gateway returns a non-2xx response."""


class RemoteGuardrailAdapter:
    """HTTP client for the A1 ``agent-guardrail-gateway`` service."""

    def __init__(self, settings: object) -> None:
        self._settings = settings
        self._base_url = _s2s.validate_base_url(
            setting_or_default("GUARDRAIL_GATEWAY_URL", _DEFAULT_URL), service="guardrail gateway"
        )

    def screen(self, text: str, direction: Direction) -> GuardrailVerdict:
        """Screen inbound prompt or outbound response via the A1 gateway."""
        payload = {"text": text, "direction": to_jsonable(direction)}
        url = f"{self._base_url}/v1/guardrail/screen"
        try:
            response = httpx.post(url, json=payload, timeout=_TIMEOUT, headers=_s2s.headers())
        except httpx.HTTPError as exc:
            raise RemoteGuardrailError(f"guardrail gateway request to {url} failed: {exc}") from exc
        if response.status_code // 100 != 2:
            raise RemoteGuardrailError(
                f"guardrail gateway {url} returned {response.status_code}: {response.text[:500]}"
            )
        return self._parse_verdict(response.json(), direction)

    @staticmethod
    def _parse_verdict(body: dict, fallback_direction: Direction) -> GuardrailVerdict:
        raw_direction = body.get("direction")
        direction = Direction(raw_direction) if raw_direction else fallback_direction
        findings = tuple(
            GuardrailFinding(
                category=GuardrailCategory(item.get("category", "other")),
                confidence=str(item.get("confidence", "")),
                detail=str(item.get("detail", "")),
            )
            for item in (body.get("findings") or ())
        )
        # Allowed only on the JSON literal ``true``. ``bool()`` of the string "false", of 1 or
        # of a non-empty object is True, so a gateway answering in any other shape is a block.
        # An allowed verdict must also carry the screened text as a string: an allow with no
        # text (or a non-string one) is a gateway that did not say what may be used, and is
        # refused rather than letting a caller fall back to the unscreened original.
        allowed = body.get("allowed") is True
        sanitized = body.get("sanitized_text")
        reason = str(body.get("reason", ""))
        if allowed and not isinstance(sanitized, str):
            return GuardrailVerdict(
                allowed=False,
                direction=direction,
                findings=findings,
                sanitized_text=None,
                reason="blocked: the guardrail gateway allowed without returning the text to use",
            )
        return GuardrailVerdict(
            allowed=allowed,
            direction=direction,
            findings=findings,
            sanitized_text=sanitized if allowed else None,
            reason=reason,
        )
