"""Model Armor guardrail adapter (GuardrailPort).

Implements :class:`GuardrailPort` against **Model Armor** on the Gemini Enterprise Agent
Platform. Every inbound prompt and outbound response is screened (prompt-injection /
jailbreak / sensitive-data / malicious-URL / RAI) via ``sanitizeUserPrompt`` /
``sanitizeModelResponse`` on the regional host, pinned to Singapore for residency. Because
B3 handles customer PII (rule R1), this runs on both directions of every request.

FAIL CLOSED. The verdict is ALLOWED only when ``filter_match_state`` is ``NO_MATCH_FOUND``
AND ``invocation_result`` is ``SUCCESS``, each read by the enum member's ``.name`` (``str()``
of a proto-plus ``IntEnum`` is its number on Python 3.11+). ``invocation_result`` is set
independently of the match state: ``PARTIAL`` (some filters were skipped or failed) and
``FAILURE`` (all were) arrive WITH ``NO_MATCH_FOUND``, because a skipped filter reports
``EXECUTION_SKIPPED`` and no match. Filters skip on input past their token limit, on an
unsupported language (multi-language detection is off in this region), or on a detector error,
so "no match" from a screen that did not run is refused, not passed. Every call carries a
deadline (``model_armor.timeout_seconds``), and an API error or timeout propagates to the
caller, which audits the refusal.

The ``google.cloud.modelarmor`` import is lazy so on-prem and test profiles load this
module with no GCP SDK installed.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain.models import (
    Direction,
    GuardrailCategory,
    GuardrailFinding,
    GuardrailVerdict,
)


class ModelArmorGuardrailAdapter:
    """Screen prompts/responses through a regional Model Armor template."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._armor = settings.model_armor
        self._client: Any | None = None

    def _template(self) -> str:
        return (
            f"projects/{self._settings.project_id}/locations/{self._settings.region}"
            f"/templates/{self._armor.template_id}"
        )

    def _get_client(self) -> Any:
        from google.cloud import modelarmor_v1 as ma  # lazy

        if self._client is None:
            self._client = ma.ModelArmorClient(client_options={"api_endpoint": self._armor.host})
        return self._client

    def screen(self, text: str, direction: Direction) -> GuardrailVerdict:
        """Screen inbound prompt or outbound response. Raises if Model Armor cannot answer."""
        from google.cloud import modelarmor_v1 as ma  # lazy

        client = self._get_client()
        template = self._template()
        if direction is Direction.INPUT:
            response = client.sanitize_user_prompt(
                request=ma.SanitizeUserPromptRequest(
                    name=template,
                    user_prompt_data=ma.DataItem(text=text),
                ),
                timeout=self._armor.timeout_seconds,
            )
        else:
            response = client.sanitize_model_response(
                request=ma.SanitizeModelResponseRequest(
                    name=template,
                    model_response_data=ma.DataItem(text=text),
                ),
                timeout=self._armor.timeout_seconds,
            )
        return self._map_result(response, direction, text)

    @staticmethod
    def _map_result(response: Any, direction: Direction, original: str) -> GuardrailVerdict:
        """Map a sanitize response to a verdict: allowed ONLY on a complete, clean screen.

        Complete means ``invocation_result`` is ``SUCCESS``; clean means
        ``filter_match_state`` is ``NO_MATCH_FOUND``. A match blocks however many filters ran.
        A missing or empty ``sanitization_result`` (proto-plus hands back a default message,
        ``FILTER_MATCH_STATE_UNSPECIFIED``) blocks, because a screen that returned no answer
        has not cleared the text. API errors are not caught here; they propagate.
        """
        result = getattr(response, "sanitization_result", None)
        state_name = getattr(getattr(result, "filter_match_state", None), "name", None)
        invocation = getattr(getattr(result, "invocation_result", None), "name", None)
        if state_name == "NO_MATCH_FOUND" and invocation == "SUCCESS":
            return GuardrailVerdict(
                allowed=True,
                direction=direction,
                findings=(),
                sanitized_text=original,
                reason="ok",
            )
        if state_name == "MATCH_FOUND":
            reason = "blocked by Model Armor"
            detail = "Model Armor filter match"
        elif state_name == "NO_MATCH_FOUND":
            reason = "blocked: Model Armor returned no complete filter decision"
            detail = f"invocation_result={invocation or 'absent'}: not every filter ran"
        else:
            reason = "blocked by Model Armor"
            detail = f"Model Armor returned no usable verdict (filter_match_state={state_name})"
        return GuardrailVerdict(
            allowed=False,
            direction=direction,
            findings=(
                GuardrailFinding(
                    category=GuardrailCategory.OTHER,
                    confidence="high",
                    detail=detail,
                ),
            ),
            sanitized_text=None,
            reason=reason,
        )
