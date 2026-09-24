"""ADK FunctionTools that expose the B3 domain capabilities to the agent.

Each tool is a thin, side-effect-honest wrapper: it builds the advisory service from a
:class:`~cio_advisory.config.Container` (so every port is bound to the adapter selected by
the active profile), invokes the service, and returns a JSON-safe dict via
:func:`~cio_advisory.domain.serialization.to_jsonable`.

Design notes
------------
* The domain service owns orchestration (redact -> guardrail -> load -> retrieve ->
  synthesise -> suitability -> guardrail -> audit; SPEC §5). These tools deliberately add
  **no** business logic of their own.
* ``google.adk`` is imported lazily inside :func:`build_function_tools` so this module
  imports cleanly under the on-prem/test profile with no ADK installed (SPEC §4). The plain
  Python tool callables are importable and unit-testable without ADK at all.
* Every callable carries a precise type-hinted signature and a docstring: ADK derives the
  tool's name, description and JSON parameter schema from them, so the wording here is part
  of the agent's contract surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..config import Container, Settings, build_container

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from google.adk.tools import FunctionTool

_DEFAULT_ACTOR = "cio-advisory-agent"


def _container(settings: Settings | None) -> Container:
    return build_container(settings)


def _principal(actor: str) -> Any:
    """The verified principal the agent acts as (a demo-bank advisory service identity).

    The agent runs server-side within its tenant; ``actor`` is the audit/service identity.
    Object authorization (``domain/entitlements.py``) is enforced against this principal, so
    a client outside the agent's tenant (and without an explicit grant) is denied.
    """
    from ..domain.identity import Principal

    return Principal(
        subject=actor,
        principals=("group:cio-analyst",),
        tenant="demo-bank",
        source="agent",
    )


def _service(settings: Settings | None) -> tuple[Any, Any]:
    """The advisory service for ONE tool call, and the recorder its review hand-off goes through.

    The tool reports what happened to the hand-off (``review_routing``) from the recorder, so
    a briefing that requires review but never reached the console says so to the agent.
    """
    from ..adapters.controls import RecordingReviewRouter
    from ..api.deps import build_advisory_service

    c = _container(settings)
    routing = RecordingReviewRouter(c.review_router)
    return build_advisory_service(c, review_router=routing), routing


def build_briefing(
    client_id: str,
    actor: str = _DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Build a suitability-checked advisory briefing for one client.

    Connects CIO house views to the client's portfolio and returns personalised talking
    points, each with a suitability verdict and citations, a portfolio alignment summary,
    and the mandatory non-advice disclaimer. The result requires human review (the RM is
    the maker-checker, P-06). This is decision-support, NOT advice.

    Args:
      client_id: Opaque client reference (no PII).
      actor: Authenticated RM / service identity the request is made for.

    Returns:
      A JSON-safe ``AdvisoryBriefing`` dict, plus ``review_routing``: whether the briefing
      was sent to the review console (``routed``), could not be (``failed``), or routing is
      switched off (``off``).
    """
    from ..domain.serialization import to_jsonable

    service, routing = _service(settings)
    payload: dict[str, Any] = to_jsonable(service.brief(client_id, _principal(actor)))
    payload["review_routing"] = routing.outcome.value
    return payload


def generate_talking_points(
    client_id: str,
    actor: str = _DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Generate personalised, suitability-aware talking points for one client.

    Returns the ``TalkingPoint`` objects, each linking a CIO house-view theme to the
    client's holdings, with a suitability verdict and citations. Decision-support, NOT
    advice (``is_advice`` is always false).

    Args:
      client_id: Opaque client reference (no PII).
      actor: Authenticated RM / service identity the request is made for.

    Returns:
      A JSON-safe dict: ``client_id``, ``talking_points`` (a list of ``TalkingPoint``
      dicts) and ``review_routing``, what happened to the briefing's human-review hand-off.
    """
    from ..domain.serialization import to_jsonable

    service, routing = _service(settings)
    points = service.talking_points(client_id, _principal(actor))
    return {
        "client_id": client_id,
        "talking_points": to_jsonable(points),
        "review_routing": routing.outcome.value,
    }


def check_suitability(
    client_id: str,
    theme: str,
    actor: str = _DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Assess whether a CIO house-view theme is suitable for a client.

    Builds the client's briefing and returns the ``SuitabilityAssessment`` for the matching
    theme (verdict SUITABLE / REVIEW / UNSUITABLE, the factors that drove it, a rationale,
    and citations), or a REVIEW envelope if the theme is not in the client's in-scope set.

    Args:
      client_id: Opaque client reference (no PII).
      theme: The CIO house-view theme to assess.
      actor: Authenticated RM / service identity the request is made for.

    Returns:
      A JSON-safe ``SuitabilityAssessment`` dict (or a REVIEW envelope), plus
      ``review_routing`` for the briefing it was read from.
    """
    from ..domain.serialization import to_jsonable

    service, routing = _service(settings)
    briefing = service.brief(client_id, _principal(actor))
    wanted = theme.strip().lower()
    for point in briefing.talking_points:
        assessment = point.suitability
        if assessment is not None and assessment.theme.strip().lower() == wanted:
            payload: dict[str, Any] = to_jsonable(assessment)
            payload["review_routing"] = routing.outcome.value
            return payload
    return {
        "theme": theme,
        "verdict": "review",
        "rationale": (
            "No suitable, in-scope talking point matched this theme; the RM should review "
            "the full briefing."
        ),
        "review_routing": routing.outcome.value,
    }


# The plain callables, in stable order, so the agent layer and tests share one list.
TOOL_FUNCTIONS = (
    build_briefing,
    generate_talking_points,
    check_suitability,
)


def build_function_tools() -> list[FunctionTool]:
    """Wrap each domain-service callable as an ADK ``FunctionTool``.

    ADK introspects each function's signature and docstring to derive the tool name,
    description and parameter JSON schema. ``google.adk`` is imported here (lazily) so the
    module is import-safe without ADK installed (SPEC §4).
    """
    from google.adk.tools import FunctionTool

    return [FunctionTool(func=fn) for fn in TOOL_FUNCTIONS]
