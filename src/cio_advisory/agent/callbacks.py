"""Model-boundary callbacks: defense-in-depth guardrail + redaction + audit.

The advisory service already screens and redacts inside its pipeline (SPEC §5). These ADK
callbacks add a **second, independent line of defence at the model boundary** (P-04
minimise-data-to-model, P-07 audited-everything): every prompt that reaches the LLM and
every response that leaves it is, once more,

  1. **redacted** (Sensitive Data Protection / DLP, via :class:`PIIRedactionPort`) so client
     PII never reaches the model or any log/span, and
  2. **screened** (Model Armor, via :class:`GuardrailPort`) for prompt injection, jailbreak,
     sensitive-data leakage and RAI categories, and
  3. **audited** (Cloud Logging locked WORM bucket, via :class:`AuditSinkPort`) with an
     already-redacted record at agent turn end.

What is screened is what is SENT. The INPUT screen reads every non-model part of the request:
the user's text AND every tool result (``function_response``), which is how the grounding
sub-agent's web-derived answer and every FunctionTool's output reach the root model. The
OUTPUT screen reads the model's text and its function calls. On an allow, the redacted and
screened text is written back onto the request or response part by part, so the model reads
exactly the text the guardrail cleared rather than the original it was derived from; if the
screened text cannot be mapped back, the call is refused. Function-call ARGUMENTS are screened
but not rewritten: they go to this service's own tools, which need the real client reference.

The same model callbacks are attached to the ``web_grounding`` sub-agent
(``agent/grounding_agent.py``), whose ``google_search`` calls ``AgentTool`` runs on their own:
without them its generation calls would be unscreened in both directions.

The callbacks are built from a :class:`~cio_advisory.config.Container`, so the active
profile decides whether these are real Model Armor / DLP / Cloud Logging calls or on-prem
placeholders.

PII-in-spans
------------
ADK can attach message content to trace spans. That would leak PII into Cloud Trace, so
:func:`configure_span_privacy` sets ``ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false``
(idempotent; never overrides an operator who has already pinned it).

ADK imports are done lazily inside the factory / callbacks so this module imports without
ADK installed (SPEC §4).
"""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..config import Container
from ..domain.models import (
    AuditEvent,
    Decision,
    Direction,
    GuardrailVerdict,
    utcnow,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from google.adk.agents.callback_context import CallbackContext
    from google.adk.models import LlmRequest, LlmResponse

SPAN_CONTENT_ENV = "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS"

_LAST_PROMPT_KEY = "_ca_last_redacted_prompt"
_LAST_RESPONSE_KEY = "_ca_last_redacted_response"
_BLOCKED_KEY = "_ca_turn_blocked"

#: Joins the parts of one request (or response) into the single text that is redacted and
#: screened, and splits the screened text back onto those parts. A visible symbol no redaction
#: or screen has a reason to rewrite; if one ever does, the split no longer lines up and the
#: call is refused rather than sent with text that was not the text screened.
_SEGMENT_SEP = "\n␞\n"


def configure_span_privacy() -> None:
    """Ensure message content is never captured into trace spans (PII safety)."""
    os.environ.setdefault(SPAN_CONTENT_ENV, "false")


@dataclass(frozen=True, slots=True)
class _Segment:
    """One part of a request or response, as the text the screen reads for it.

    ``kind`` decides what happens when the screened text differs: a ``text`` part is rewritten
    in place, a ``function_response`` is replaced by the screened text as its result, a
    ``function_call`` keeps its arguments (they go to this service's own tools, and the screen
    has still read them), and an ``opaque`` content that cannot be rewritten refuses the call.
    """

    part: Any
    kind: str
    text: str


def _redact_then_screen(
    container: Container,
    text: str,
    direction: Direction,
) -> tuple[str, GuardrailVerdict]:
    """Redact ``text`` then guardrail-screen it; return (text, verdict).

    Allowed: the text is the verdict's ``sanitized_text`` exactly as given, the text to send.
    Blocked: it is the REDACTED text, kept for the audit record only and never sent. There is
    no fallback from an allowed verdict to the unscreened text: an allow that names no text is
    refused (and ``GuardrailVerdict`` refuses to construct one in the first place).
    """
    redaction = container.redaction.redact(text)
    verdict = container.guardrail.screen(redaction.text, direction)
    if verdict.allowed and verdict.sanitized_text is not None:
        return verdict.sanitized_text, verdict
    if verdict.allowed:  # pragma: no cover - unconstructible; kept so no path can fall back
        verdict = GuardrailVerdict(
            allowed=False,
            direction=direction,
            reason="blocked: the guardrail allowed without returning the text to use",
        )
    return redaction.text, verdict


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)


def _segments(content: Any) -> list[_Segment]:
    """Every part of one ``types.Content`` the screen must read, in order."""
    if content is None:
        return []
    if isinstance(content, str):
        return [_Segment(part=None, kind="opaque", text=content)] if content else []
    parts = getattr(content, "parts", None)
    if parts is None:
        return [_Segment(part=None, kind="opaque", text=str(content))]
    out: list[_Segment] = []
    for part in parts:
        text = getattr(part, "text", None)
        if text:
            out.append(_Segment(part=part, kind="text", text=text))
        call = getattr(part, "function_call", None)
        if call is not None:
            name = getattr(call, "name", "") or ""
            args = _json(getattr(call, "args", None) or {})
            out.append(_Segment(part=part, kind="function_call", text=f"{name}({args})"))
        response = getattr(part, "function_response", None)
        if response is not None:
            result = _json(getattr(response, "response", None))
            out.append(_Segment(part=part, kind="function_response", text=result))
    return out


def _joined(segments: list[_Segment]) -> str:
    return _SEGMENT_SEP.join(segment.text for segment in segments)


def _write_back(segments: list[_Segment], screened: str) -> bool:
    """Put the screened text back onto the parts it came from; False if it cannot be done.

    After this returns True, what the model receives (or what leaves it) is exactly the text
    the guardrail screened, part for part, function-call arguments aside.
    """
    if not segments:
        return screened == ""
    pieces = screened.split(_SEGMENT_SEP)
    if len(pieces) != len(segments):
        return False
    changed = [
        (seg, piece) for seg, piece in zip(segments, pieces, strict=True) if piece != seg.text
    ]
    if any(seg.kind == "opaque" for seg, _ in changed):
        return False
    for seg, piece in changed:
        if seg.kind == "text":
            seg.part.text = piece
        elif seg.kind == "function_response":
            seg.part.function_response.response = {"result": piece}
    return True


def _content_to_text(content: Any) -> str:
    """Flatten an ADK ``types.Content`` (or text) to the text the screen reads for it.

    Text parts, function calls (name and arguments) and function responses (the tool's
    result) are all included: a screen that read only ``part.text`` never saw a tool result.
    """
    return _joined(_segments(content))


def _unmappable(direction: Direction) -> GuardrailVerdict:
    return GuardrailVerdict(
        allowed=False,
        direction=direction,
        reason="blocked: the screened text could not be mapped back onto the model call",
    )


def _request_segments(llm_request: Any) -> list[_Segment]:
    """Every non-model part of a request: the user's text and every tool result.

    Model turns are left out; each was OUTPUT-screened when it was produced.
    """
    return [
        segment
        for content in (getattr(llm_request, "contents", None) or [])
        if getattr(content, "role", None) != "model"
        for segment in _segments(content)
    ]


def _screen_request(container: Container, llm_request: Any) -> tuple[str, GuardrailVerdict]:
    """Redact and INPUT-screen what the model is about to read, then send exactly that."""
    segments = _request_segments(llm_request)
    screened, verdict = _redact_then_screen(container, _joined(segments), Direction.INPUT)
    if verdict.allowed and not _write_back(segments, screened):
        verdict = _unmappable(Direction.INPUT)
    return screened, verdict


def _screen_response(container: Container, llm_response: Any) -> tuple[str, GuardrailVerdict]:
    """Redact and OUTPUT-screen what the model answered, text and function calls alike."""
    segments = _segments(getattr(llm_response, "content", None))
    screened, verdict = _redact_then_screen(container, _joined(segments), Direction.OUTPUT)
    if verdict.allowed and not _write_back(segments, screened):
        verdict = _unmappable(Direction.OUTPUT)
    return screened, verdict


def _set_state(callback_context: Any, key: str, value: Any) -> None:
    state = getattr(callback_context, "state", None)
    if state is None:
        return
    with contextlib.suppress(Exception):  # pragma: no cover - extremely defensive
        state[key] = value


def _get_state(callback_context: Any, key: str, default: Any = None) -> Any:
    state = getattr(callback_context, "state", None)
    if state is None:
        return default
    try:
        return state.get(key, default)
    except Exception:  # pragma: no cover - extremely defensive
        return default


def build_callbacks(container: Container) -> dict[str, Callable[..., Any]]:
    """Build the before/after-model and after-agent callbacks bound to ``container``."""
    from google.adk.models import LlmResponse
    from google.genai import types

    def _refusal(reason: str) -> LlmResponse:
        return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=reason)]))

    def before_model_callback(
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> LlmResponse | None:
        safe_text, verdict = _screen_request(container, llm_request)
        _set_state(callback_context, _LAST_PROMPT_KEY, safe_text)

        if not verdict.allowed:
            _set_state(callback_context, _BLOCKED_KEY, True)
            return _refusal(verdict.reason or "Request blocked by input guardrail policy.")
        return None

    def after_model_callback(
        callback_context: CallbackContext,
        llm_response: LlmResponse,
    ) -> LlmResponse | None:
        safe_text, verdict = _screen_response(container, llm_response)
        _set_state(callback_context, _LAST_RESPONSE_KEY, safe_text)

        if not verdict.allowed:
            _set_state(callback_context, _BLOCKED_KEY, True)
            return _refusal(verdict.reason or "Response withheld by output guardrail policy.")
        # The screened text has been written back onto the response's own parts.
        return llm_response

    def after_agent_callback(callback_context: CallbackContext) -> types.Content | None:
        redacted_prompt = _get_state(callback_context, _LAST_PROMPT_KEY, "")
        redacted_response = _get_state(callback_context, _LAST_RESPONSE_KEY, "")
        blocked = bool(_get_state(callback_context, _BLOCKED_KEY, False))
        decision = Decision.BLOCKED if blocked else Decision.ALLOWED
        trace_id = _trace_id(callback_context)

        event = AuditEvent(
            action="briefing",
            actor=_actor(callback_context),
            decision=decision,
            redacted_prompt=redacted_prompt,
            redacted_response=redacted_response,
            resource="cio-advisory",
            trace_id=trace_id,
            timestamp=utcnow(),
            metadata={"layer": "model-boundary"},
        )
        container.audit.record(event)
        return None

    return {
        "before_model_callback": before_model_callback,
        "after_model_callback": after_model_callback,
        "after_agent_callback": after_agent_callback,
    }


def _actor(callback_context: Any) -> str:
    actor = _get_state(callback_context, "actor", None)
    if actor:
        return str(actor)
    user_id = getattr(callback_context, "user_id", None)
    return str(user_id) if user_id else "cio-advisory-agent"


def _trace_id(callback_context: Any) -> str | None:
    invocation_id = getattr(callback_context, "invocation_id", None)
    return str(invocation_id) if invocation_id else None
