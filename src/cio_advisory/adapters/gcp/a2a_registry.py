"""A2A registry adapter (AgentRegistryPort).

Publishes and resolves B3's A2A AgentCard. Standalone, the card is served from B3's own
``/.well-known/agent-card.json``; inside the platform it is registered with the A3
``agent-registry`` service (the ``platform`` adapter). This GCP adapter keeps an
in-process registry of cards plus the assistant's own card, so discovery works without the
shared service in a single-tenant deploy.

Pure-stdlib at import time : no Google Cloud SDK is required to construct it.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import AgentCard


class A2ARegistryAdapter:
    """In-process A2A AgentCard registry for the standalone (gcp) profile."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cards: dict[str, AgentCard] = {}

    def register(self, card: AgentCard) -> None:
        self._cards[card.name] = card

    def get(self, name: str) -> AgentCard | None:
        if name in self._cards:
            return self._cards[name]
        from ...agent.agent_card import build_agent_card

        card = build_agent_card(self._settings)
        return card if card.name == name else None

    def list(self) -> list[AgentCard]:
        from ...agent.agent_card import build_agent_card

        cards = dict(self._cards)
        own = build_agent_card(self._settings)
        cards.setdefault(own.name, own)
        return list(cards.values())
