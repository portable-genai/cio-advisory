"""MCP tool-catalog adapter (ToolCatalogPort).

Exposes the governed, least-privilege tools B3 publishes over **MCP** (2025-11-25). The
catalog is intentionally narrow: each tool maps to one domain capability (build a briefing,
generate talking points, check suitability) with an explicit input schema, so a peer agent
sees exactly what it is allowed to call.

No tool advertises an ``actor`` input: identity is resolved server-side from the verified
:class:`~cio_advisory.domain.identity.Principal`, so a calling peer agent never asserts who
it is acting as (see docs/embedding-and-identity.md). Pure-stdlib at import time : no MCP
SDK is required to construct it (the live MCP server is wired in the deployed runtime).
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import ToolSpec

_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="build_briefing",
        description="Build a suitability-checked advisory briefing for one client.",
        input_schema={
            "type": "object",
            "properties": {"client_id": {"type": "string"}},
            "required": ["client_id"],
        },
    ),
    ToolSpec(
        name="generate_talking_points",
        description="Generate personalised, suitability-aware talking points for a client.",
        input_schema={
            "type": "object",
            "properties": {"client_id": {"type": "string"}},
            "required": ["client_id"],
        },
    ),
    ToolSpec(
        name="check_suitability",
        description="Assess the suitability of a CIO house-view theme for a client.",
        input_schema={
            "type": "object",
            "properties": {
                "client_id": {"type": "string"},
                "theme": {"type": "string"},
            },
            "required": ["client_id", "theme"],
        },
    ),
)


class McpToolCatalogAdapter:
    """Serve the governed B3 tool catalog (MCP-shaped ToolSpecs)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._tools = {tool.name: tool for tool in _TOOLS}

    def list_tools(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def get_tool(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)
