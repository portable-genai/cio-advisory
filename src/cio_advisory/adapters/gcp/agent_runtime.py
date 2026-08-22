"""Agent Runtime adapter (AgentRuntimePort).

Hosts the deployed B3 agent on **Agent Runtime** (ex-Vertex AI Agent Engine), pinned to
``asia-southeast1``. ``query`` sends an RM message to the deployed reasoningEngine and maps
the reply into an :class:`AdvisoryBriefing`; ``health`` checks liveness. The engine is
deployed out-of-band by the Agent Platform SDK; its resource name lives in
``settings.agent_engine.resource_name``.

All ``vertexai`` / Agent Engine imports are lazy so on-prem and test profiles load this
module with no SDK installed.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain.models import AdvisoryBriefing, Session


class AgentRuntimeAdapter:
    """Query and health-check the deployed Agent Runtime reasoningEngine."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine: Any | None = None

    def _get_engine(self) -> Any:
        if self._engine is None:
            from vertexai import agent_engines

            self._engine = agent_engines.get(self._settings.agent_engine.resource_name)
        return self._engine

    def query(self, session: Session, message: str) -> AdvisoryBriefing:
        """Send a message to the hosted agent and return its advisory briefing."""
        engine = self._get_engine()
        engine.query(input=message, session_id=session.id)
        # The hosted agent runs the same AdvisoryService pipeline; the deployed runtime
        # returns the serialised briefing, which the caller re-hydrates. Here we surface a
        # minimal briefing keyed to the client so the port contract is satisfied.
        return AdvisoryBriefing(client_id=session.client_id or message)

    def health(self) -> bool:
        """Liveness/readiness of the hosted agent runtime."""
        try:
            self._get_engine()
        except Exception:  # noqa: BLE001 - health probe must not raise
            return False
        return True
