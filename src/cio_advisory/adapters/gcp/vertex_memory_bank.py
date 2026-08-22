"""Agent Platform Memory Bank adapter (MemoryPort).

Durable RM preferences and facts on the Gemini Enterprise Agent Platform Memory Bank,
pinned to ``asia-southeast1``. Memory content is redacted at the boundary (P-04) before it
is stored, and is scoped (user / client / global) so a client's context never leaks across
relationships.

All ``vertexai`` imports are lazy so on-prem and test profiles load this module with no SDK
installed.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain.models import MemoryItem


class VertexMemoryBankAdapter:
    """Store and search durable RM memory via Agent Platform Memory Bank."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._service: Any | None = None

    def _get_service(self) -> Any:
        if self._service is None:
            from vertexai import agent_engines

            self._service = agent_engines.get(self._settings.agent_engine.resource_name)
        return self._service

    def store(self, item: MemoryItem) -> None:
        service = self._get_service()
        service.create_memory(fact=item.content, scope={"scope": item.scope})

    def search(self, query: str, scope: str = "user", top_k: int = 5) -> list[MemoryItem]:
        service = self._get_service()
        results = service.retrieve_memories(query=query, scope={"scope": scope})
        out: list[MemoryItem] = []
        for i, result in enumerate(results or []):
            content = str(getattr(getattr(result, "memory", result), "fact", "") or result)
            out.append(MemoryItem(id=f"mem-{i}", content=content, scope=scope))
        return out[:top_k]
