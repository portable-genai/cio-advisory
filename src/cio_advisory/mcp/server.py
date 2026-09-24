"""Serve the governed tool catalog cio-advisory already declares, over MCP 2026-07-28.

The catalog declared three governed tools and served none of them: there was no MCP server
process anywhere in the fleet. This supplies the callables that answer the existing catalog and
declares nothing new. `hex_service_kit.mcpserve.bind` refuses a mismatch in either direction at
start-up.

**This is a suitability surface, so the identity is the load-bearing part.** `brief` and
`talking_points` take a `Principal` and reach a client's portfolio. MCP stdio verifies no end
user, so the principal constructed below is a SERVICE caller carrying NO entitlement principals
and no tenant. Every portfolio read behind these tools then sees an empty scope and fails
closed. Filling those fields so a briefing came back would be manufacturing an authorization
decision the transport cannot support, on a surface whose whole purpose is deciding what a
particular client may be told.

Nothing here produces advice. The briefing carries its own not-advice disclaimer from the
domain, and this module neither removes nor rewrites it.
"""

from __future__ import annotations

from typing import Any

from hex_service_kit import mcpserve

from ..adapters.controls import RecordingReviewRouter
from ..api import deps

# The service is typed against the DOMAIN's principal, not the kit's. Both carry the
# same fields, so constructing the kit's here type-checked as nothing and shipped a
# value the service's own annotation rejects.
from ..domain.identity import Principal
from ..domain.serialization import to_jsonable

#: The tools this module answers, as data, so a test can hold it against the catalog.
HANDLER_NAMES: tuple[str, ...] = ("build_briefing", "generate_talking_points", "check_suitability")


def _service() -> tuple[Any, RecordingReviewRouter]:
    """The advisory service for ONE tool call, and the recorder its review hand-off goes through.

    Every payload these tools return carries ``review_routing``, so a briefing that requires
    review but never reached the console says so to the calling agent.
    """
    routing = RecordingReviewRouter(deps.get_container().review_router)
    return deps.build_advisory_service(deps.get_container(), review_router=routing), routing


def build_handlers(actor: str) -> dict[str, mcpserve.Handler]:
    """Bind each declared tool to the advisory service that already performs it."""
    principal = Principal(subject=actor, principals=(), tenant="", source="mcp")

    def build_briefing(**arguments: Any) -> Any:
        service, routing = _service()
        briefing = service.brief(str(arguments.get("client_id", "") or ""), principal)
        return {**to_jsonable(briefing), "review_routing": routing.outcome.value}

    def generate_talking_points(**arguments: Any) -> Any:
        client_id = str(arguments.get("client_id", "") or "")
        service, routing = _service()
        points = service.talking_points(client_id, principal)
        return {
            "client_id": client_id,
            "talking_points": to_jsonable(points),
            "review_routing": routing.outcome.value,
        }

    def check_suitability(**arguments: Any) -> Any:
        """Suitability is the briefing's alignment section, not a separate judgement.

        The service decides alignment while building the briefing, against the client's own
        mandate. Recomputing it here by another route would create a second suitability answer,
        which on this surface is the one duplication that must not exist.

        ``alignment`` is a single ``PortfolioAlignment`` holding ``themes_in_line``, ``gaps`` and
        ``overweights``, so a named theme is reported as WHICH of those three it falls in rather
        than as a filtered list. An unknown theme says so explicitly instead of returning an
        empty result that reads like "no concerns".
        """
        service, routing = _service()
        briefing = service.brief(str(arguments.get("client_id", "") or ""), principal)
        alignment = briefing.alignment
        outcome = routing.outcome.value
        theme = str(arguments.get("theme", "") or "")
        if not theme:
            return {"alignment": alignment, "review_routing": outcome}
        for bucket in ("themes_in_line", "gaps", "overweights"):
            if theme in {str(x) for x in getattr(alignment, bucket, ())}:
                return {
                    "theme": theme,
                    "standing": bucket,
                    "alignment": alignment,
                    "review_routing": outcome,
                }
        return {
            "theme": theme,
            "standing": "not_in_mandate",
            "alignment": alignment,
            "review_routing": outcome,
        }

    return {
        "build_briefing": build_briefing,
        "generate_talking_points": generate_talking_points,
        "check_suitability": check_suitability,
    }


def build_server(actor: str, *, with_audit_tools: bool = True) -> Any:
    """Build the MCP server for cio-advisory's catalog, refusing on any catalog/handler mismatch."""
    container = deps.get_container()
    return mcpserve.build_server(
        name="cio-advisory",
        version=str(getattr(container.settings, "version", "") or "0.0.1"),
        catalog=container.tool_catalog,
        handlers=build_handlers(actor),
        audit_store=getattr(container, "audit", None) if with_audit_tools else None,
    )
