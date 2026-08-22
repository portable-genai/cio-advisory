"""Local LLM adapter (LLMPort): a deterministic, schema-driven generator.

The ``local`` profile's stand-in for **Gemini**: no model, no network, fully
reproducible. It reads ``request.response_schema`` (the JSON schema the calling service
asks for) and emits a deterministic JSON object whose keys match it. For the
talking-points schema it parses the rendered HOUSE VIEWS block in the prompt, recovers
each ``[source_id] theme`` header, and emits one non-advice talking point per house view,
citing only that view's ``source_id`` via ``used_source_ids`` so the suitability check and
page-level citation mapping are exercised honestly. There is no Google emulator for Gemini,
so this path is unconditional.

The schema-driven ``FakeLLM`` is a real, registered adapter rather than a ``tests/conftest.py``
fixture, so the in-memory implementation lives once under ``adapters/local`` and drives both
the offline tests and the CLI.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ...config import Settings
from ...domain.models import (
    LlmRequest,
    LlmResponse,
    TokenUsage,
)

# The rendered house-view block keys each view with a ``[source_id] theme (stance: ...``
# header (see domain.prompts.HOUSE_VIEW_BLOCK). Recover the ids and themes the service
# actually grounded on so the talking points cite only retrieved house views.
_HV_HEADER_RE = re.compile(r"^\[([a-z0-9][a-z0-9\-]*)\]\s*(.+?)\s*\(stance:", re.MULTILINE)
# Fallback: any ``[source_id]`` token, for non-talking-point prompts.
_SOURCE_HEADER_RE = re.compile(r"\[([a-z0-9][a-z0-9\-]*)\]")


def _schema_properties(schema: dict | None) -> dict[str, Any]:
    if not schema:
        return {}
    props = schema.get("properties")
    return props if isinstance(props, dict) else {}


class LocalDeterministicLLMAdapter:
    """Deterministic LLM whose ``generate`` returns JSON matching the request schema.

    The body is shaped from ``request.response_schema``: the talking-points schema wraps
    an ``items`` array, so the adapter emits one item per house view present in the
    prompt; any other object schema gets a deterministic per-field value. Every item
    references the source ids actually present in the prompt via ``used_source_ids`` so
    the services map page-level citations and never cite a hallucinated source.
    """

    REASONING_MODEL = "gemini-3.5-flash"
    TRIAGE_MODEL = "gemini-3.1-flash-lite"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._reasoning_model = settings.models.reasoning or self.REASONING_MODEL
        self._triage_model = settings.models.triage or self.TRIAGE_MODEL

    # ------------------------------------------------------------------ #
    # LLMPort
    # ------------------------------------------------------------------ #
    def generate(self, request: LlmRequest) -> LlmResponse:
        body = self._body_for_schema(request.response_schema, request)
        return LlmResponse(
            text=json.dumps(body),
            usage=TokenUsage(input_tokens=128, output_tokens=64, thinking_tokens=32),
            model=request.model or self._reasoning_model,
            web_citations=(),
            raw=body,
        )

    def classify(self, text: str, labels: list[str]) -> str:
        # Deterministic triage: first label (the services only use this for routing).
        return labels[0] if labels else ""

    # ------------------------------------------------------------------ #
    # Schema-driven body
    # ------------------------------------------------------------------ #
    def _user_content(self, request: LlmRequest) -> str:
        for message in reversed(request.messages):
            if message.role == "user":
                return message.content
        return ""

    def _house_views_from_request(self, request: LlmRequest) -> list[tuple[str, str]]:
        """Recover ``(source_id, theme)`` pairs from the rendered HOUSE VIEWS block."""
        user = self._user_content(request)
        seen: dict[str, str] = {}
        for sid, theme in _HV_HEADER_RE.findall(user):
            if sid not in seen:
                seen[sid] = theme.strip()
        return list(seen.items())

    def _source_ids_from_request(self, request: LlmRequest) -> list[str]:
        user = self._user_content(request)
        seen: list[str] = []
        for sid in _SOURCE_HEADER_RE.findall(user):
            if sid not in seen:
                seen.append(sid)
        return seen

    def _talking_point_items(self, request: LlmRequest) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for source_id, theme in self._house_views_from_request(request):
            items.append(
                {
                    "headline": f"A point to discuss: {theme}",
                    "body": (
                        f"The current house view relates to {theme}. The client may wish to "
                        f"consider how this connects to their holdings [{source_id}]."
                    ),
                    "house_view_theme": theme,
                    "linked_holdings": [],
                    "used_source_ids": [source_id],
                }
            )
        return items

    def _flat_field(self, name: str, source_ids: list[str]) -> Any:
        return {
            "summary": "ok",
            "used_source_ids": list(source_ids),
            "citations": list(source_ids),
            "grounded": True,
            "supported": True,
        }.get(name, "")

    def _body_for_schema(self, schema: dict | None, request: LlmRequest) -> dict[str, Any]:
        props = _schema_properties(schema)
        if "items" in props:
            return {"items": self._talking_point_items(request)}
        source_ids = self._source_ids_from_request(request)
        if not props:
            return {"summary": "ok", "used_source_ids": source_ids}
        return {name: self._flat_field(name, source_ids) for name in props}
