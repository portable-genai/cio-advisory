"""A2A AgentCard for the B3 CIO Advisory Assistant (A3 Registry & Governance).

This builds the assistant's discovery card : the same minimal A2A shape the
``agent-registry`` service stores and serves (SPEC §6). It is published at
``/.well-known/agent-card.json``; :func:`agent_card_document` returns the JSON-safe body
the API layer serves there.

The card advertises exactly the three skills B3 exposes (build a briefing, generate
talking points, check suitability), mirroring the ADK FunctionTools so a peer agent or the
registry sees one consistent capability surface.

This module is pure (domain models only) and imports without ADK or any Google Cloud SDK
installed (SPEC §4).
"""

from __future__ import annotations

from typing import Any

from ..config import Settings
from ..domain.models import AgentCard, AgentSkill

SKILLS: tuple[AgentSkill, ...] = (
    AgentSkill(
        id="build_briefing",
        name="Advisory briefing",
        description=(
            "Build a personalised, suitability-checked advisory briefing for one client by "
            "connecting CIO house views to the client's portfolio. Decision-support, not "
            "advice; carries a non-advice disclaimer and requires human review (P-06)."
        ),
    ),
    AgentSkill(
        id="generate_talking_points",
        name="Talking points",
        description=(
            "Generate personalised, suitability-aware talking points an RM can use, each "
            "linked to a CIO house-view theme and the client's holdings, with citations."
        ),
    ),
    AgentSkill(
        id="check_suitability",
        name="Suitability check",
        description=(
            "Assess whether a CIO house-view theme is suitable for a client against their "
            "risk appetite, objectives, constraints, knowledge and portfolio concentration."
        ),
    ),
)

_DESCRIPTION = (
    "Grounded, suitability-checked decision-support assistant for private-bank relationship "
    "managers. Connects CIO house views (via the governed knowledge base) to a client's "
    "portfolio and produces personalised talking points, each suitability-tagged and "
    "citation-backed. Decision-support, NOT financial advice; the RM is the human checker. "
    "Built ports-and-adapters on the Gemini Enterprise Agent Platform."
)


def build_agent_card(settings: Settings) -> AgentCard:
    """Construct the A2A :class:`AgentCard` for this assistant."""
    base_url = _resolve_url(settings)
    return AgentCard(
        name="cio-advisory",
        description=_DESCRIPTION,
        url=base_url,
        version="0.1.0",
        skills=SKILLS,
        provider="cio-advisory",
    )


def agent_card_document(settings: Settings) -> dict[str, Any]:
    """Return the JSON-safe body to serve at ``/.well-known/agent-card.json``."""
    from ..domain.serialization import to_jsonable

    return to_jsonable(build_agent_card(settings))


def _resolve_url(settings: Settings) -> str:
    """Best-effort public URL for the card, region-pinned to asia-southeast1."""
    resource = settings.agent_engine.resource_name
    if resource:
        return f"https://aiplatform.googleapis.com/v1/{resource}"
    return "https://cio-advisory.doc.internal/a2a"
