"""Agent Platform Sessions adapter (SessionPort).

Per-client conversation state on the Gemini Enterprise Agent Platform Sessions service,
pinned to ``asia-southeast1``. Session content stays in-region; PII is redacted at the
boundary (P-04) before any message is appended.

All ``vertexai`` imports are lazy so on-prem and test profiles load this module with no SDK
installed.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain.models import LlmMessage, Session, utcnow


class VertexSessionsAdapter:
    """Manage per-client session state via Agent Platform Sessions."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._service: Any | None = None

    def _get_service(self) -> Any:
        if self._service is None:
            from vertexai import agent_engines

            self._service = agent_engines.get(self._settings.agent_engine.resource_name)
        return self._service

    def create_session(self, user_id: str, client_id: str | None = None) -> Session:
        service = self._get_service()
        remote = service.create_session(user_id=user_id)
        return Session(
            id=str(getattr(remote, "id", "")),
            user_id=user_id,
            client_id=client_id,
            created_at=utcnow(),
        )

    def get(self, session_id: str) -> Session | None:
        service = self._get_service()
        remote = service.get_session(session_id=session_id)
        if remote is None:
            return None
        return Session(
            id=session_id,
            user_id=str(getattr(remote, "user_id", "")),
        )

    def append(self, session_id: str, message: LlmMessage) -> None:
        service = self._get_service()
        service.append_event(session_id=session_id, author=message.role, content=message.content)

    def history(self, session_id: str) -> list[LlmMessage]:
        service = self._get_service()
        events = service.list_events(session_id=session_id)
        return [
            LlmMessage(
                role=str(getattr(e, "author", "user")),
                content=str(getattr(e, "content", "")),
            )
            for e in (events or [])
        ]
