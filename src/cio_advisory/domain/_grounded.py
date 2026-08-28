"""Shared grounded synthesis helpers (private to the domain layer).

The B3 services share a skeleton: redact the request, screen it, retrieve CIO house
views from the governed KB (A2), render them and a portfolio summary into the prompt
context, call the LLM with a structured-output schema, defensively parse the JSON, and
map the model's ``used_source_ids`` back to the retrieved house views' ``Citation``
objects (preserving provenance).

This module factors out that machinery so each service keeps the exact constructor and
method signature mandated by SPEC §5 while sharing one well-tested core. It is
``_``-prefixed and not part of the public domain API.

Pure domain code : talks only to ports and models, no Google Cloud / ADK imports.
"""

from __future__ import annotations

import json
from typing import Any

from .models import (
    AssetClass,
    Citation,
    ClientProfile,
    HouseView,
    LlmMessage,
    LlmRequest,
    LlmResponse,
    Portfolio,
    SourceType,
    Stance,
    ThinkingLevel,
)
from .prompts import HOUSE_VIEW_BLOCK

_STANCE_BY_VALUE: dict[str, Stance] = {s.value: s for s in Stance}
_ASSET_CLASS_BY_VALUE: dict[str, AssetClass] = {a.value: a for a in AssetClass}


def coerce_stance(value: Any, default: Stance = Stance.NEUTRAL) -> Stance:
    """Map a model/store-emitted stance string to the ``Stance`` enum defensively."""
    if isinstance(value, Stance):
        return value
    if isinstance(value, str):
        return _STANCE_BY_VALUE.get(value.strip().lower(), default)
    return default


def coerce_asset_class(value: Any, default: AssetClass = AssetClass.MULTI_ASSET) -> AssetClass:
    """Map an emitted asset-class string to the ``AssetClass`` enum defensively."""
    if isinstance(value, AssetClass):
        return value
    if isinstance(value, str):
        return _ASSET_CLASS_BY_VALUE.get(value.strip().lower(), default)
    return default


def render_house_views(house_views: list[HouseView]) -> str:
    """Render house views into the numbered context block for the prompt.

    Each block is keyed by ``source_id`` so the model can echo ``[source_id]``
    citations exactly.
    """
    if not house_views:
        return "(no house views were retrieved)"
    blocks: list[str] = []
    for hv in house_views:
        blocks.append(
            HOUSE_VIEW_BLOCK.format(
                source_id=hv.id,
                theme=hv.theme,
                stance=hv.stance.value,
                asset_class=hv.asset_class.value,
                rationale=hv.rationale.strip() or "(no rationale provided)",
            )
        )
    return "\n".join(blocks)


def render_profile(profile: ClientProfile) -> str:
    """Render the client profile into a compact, de-identified summary line."""
    objectives = ", ".join(profile.objectives) or "unspecified"
    constraints = ", ".join(profile.constraints) or "none"
    return (
        f"client_ref={profile.id}; risk_appetite={profile.risk_appetite.value}; "
        f"objectives={objectives}; knowledge_experience={profile.knowledge_experience}; "
        f"constraints={constraints}; jurisdiction={profile.jurisdiction}"
    )


def render_portfolio(portfolio: Portfolio) -> str:
    """Render the portfolio into per-holding and per-asset-class weight lines."""
    if not portfolio.holdings:
        return "(empty portfolio)"
    lines = [
        f"total_value={portfolio.total_value:.0f} {portfolio.currency}",
        "holdings:",
    ]
    for h in portfolio.holdings:
        lines.append(
            f"  - {h.instrument} ({h.asset_class.value}): weight {h.weight:.0%}, "
            f"value {h.value:.0f} {h.currency}"
        )
    by_class: dict[AssetClass, float] = {}
    for h in portfolio.holdings:
        by_class[h.asset_class] = by_class.get(h.asset_class, 0.0) + h.weight
    lines.append("asset_class_weights:")
    for ac, w in by_class.items():
        lines.append(f"  - {ac.value}: {w:.0%}")
    return "\n".join(lines)


def retrieve_house_views(
    retrieval: Any,
    query_text: str,
    filters: dict[str, str] | None = None,
    top_k: int = 10,
) -> list[HouseView]:
    """Run a house-view retrieval through the HouseViewRetrievalPort defensively."""
    views = retrieval.retrieve(query_text, top_k=top_k, filters=dict(filters or {}))
    return list(views or [])


def parse_structured(response: LlmResponse) -> dict[str, Any]:
    """Parse an LLM structured-output response into a dict, defensively.

    The GCP adapter returns the structured JSON as ``LlmResponse.text`` when a
    ``response_schema`` is set. We ``json.loads`` it; on any failure we fall back to
    extracting the first balanced JSON object, and finally to an empty dict so callers
    degrade gracefully rather than raising on a malformed model reply.
    """
    text = (response.text or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"items": parsed}
    except (json.JSONDecodeError, ValueError):
        pass

    snippet = _extract_json_object(text)
    if snippet is not None:
        try:
            parsed = json.loads(snippet)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def _extract_json_object(text: str) -> str | None:
    """Return the first balanced ``{...}`` block in ``text``, or None."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def citations_for_source_ids(
    used_source_ids: list[str],
    house_views: list[HouseView],
) -> tuple[Citation, ...]:
    """Map model-returned ``used_source_ids`` back to retrieved house-view Citations.

    Preserves the provenance from retrieval. Unknown ids the model may have
    hallucinated are dropped : we only ever cite what we retrieved. When the model
    returned nothing usable, fall back to all retrieved house-view citations so a
    talking point is never left provenance-less.
    """
    by_id: dict[str, Citation] = {}
    for hv in house_views:
        if hv.id in by_id:
            continue
        by_id[hv.id] = hv.citation or Citation(
            source_id=hv.id,
            source_type=SourceType.HOUSE_VIEW,
            title=hv.theme,
        )

    wanted = [sid for sid in (used_source_ids or []) if sid in by_id]
    if not wanted:
        wanted = list(by_id.keys())

    out: list[Citation] = []
    seen: set[str] = set()
    for sid in wanted:
        if sid not in seen:
            seen.add(sid)
            out.append(by_id[sid])
    return tuple(out)


def build_llm_request(
    system_instruction: str,
    user_content: str,
    model: str | None,
    response_schema: dict | None,
    thinking: ThinkingLevel = ThinkingLevel.HIGH,
    temperature: float = 0.0,
    max_output_tokens: int = 4096,
) -> LlmRequest:
    """Assemble an ``LlmRequest`` with a single user message and a system prompt.

    ``model=None`` lets the adapter pick its configured default (the reasoning model,
    ``gemini-3.5-flash``); thinking defaults to HIGH for grounded synthesis per SPEC.
    """
    return LlmRequest(
        messages=(LlmMessage(role="user", content=user_content),),
        system_instruction=system_instruction,
        model=model,
        thinking=thinking,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        response_schema=response_schema,
    )


def maybe_record_usage(tracer: Any, response: Any) -> None:
    """Emit token usage to the tracer for FinOps, defensively (never fatal)."""
    try:
        usage = getattr(response, "usage", None)
        model = getattr(response, "model", "") or ""
        if usage is not None and hasattr(tracer, "record_token_usage"):
            tracer.record_token_usage(usage, model)
    except Exception:  # noqa: BLE001 - metrics must never break a generation path
        return


def as_str_list(value: Any) -> list[str]:
    """Coerce an arbitrary model value into a list of stripped non-empty strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return []
