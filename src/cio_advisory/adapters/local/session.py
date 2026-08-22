"""Local session adapter (SessionPort): in-process per-client conversation state.

The ``local`` profile's stand-in for **Agent Platform Sessions**: a small in-process
store of sessions and their message history, seedable and deterministic. When the
Firestore emulator is opted in (``FIRESTORE_EMULATOR_HOST`` set AND the client lib
imports), the adapter routes to it instead and reads back through it, so a second process
(or a restart) pointed at the same emulator sees the same sessions and history. The google
client is imported lazily, only on that branch, so the default path imports no
google-cloud package.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import LlmMessage, Session
from ._emulator import firestore_emulator_active, firestore_emulator_host

_SESSIONS = "sessions"
_MESSAGES = "messages"


class LocalSessionAdapter:
    """Session store: in-process by default, Firestore-emulator-backed when opted in.

    On the emulator branch the adapter both writes and reads back through Firestore, so a
    restart or second process pointed at the same emulator sees the same sessions and
    history; the default path is purely in-process and SDK-free.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._sessions: dict[str, Session] = {}
        self._history: dict[str, list[LlmMessage]] = {}
        self._n = 0
        self._fs = None
        if firestore_emulator_active():
            self._fs = self._connect_emulator()

    def _connect_emulator(self):  # type: ignore[no-untyped-def]
        # Lazy import: only reached when FIRESTORE_EMULATOR_HOST is set and the lib imports.
        from google.cloud import firestore  # noqa: PLC0415

        # firestore.Client honours FIRESTORE_EMULATOR_HOST automatically.
        return firestore.Client(project=self._settings.project_id or "local")

    def create_session(self, user_id: str, client_id: str | None = None) -> Session:
        self._n += 1
        sid = f"sess-{self._n}"
        session = Session(id=sid, user_id=user_id, client_id=client_id)
        if self._fs is not None:
            self._fs.collection(_SESSIONS).document(sid).set(
                {
                    "id": sid,
                    "user_id": user_id,
                    "client_id": client_id,
                    "created_at": session.created_at.isoformat(),
                }
            )
        self._sessions[sid] = session
        self._history[sid] = []
        return session

    def get(self, session_id: str) -> Session | None:
        fs = self._fs
        if fs is not None:
            snap = fs.collection(_SESSIONS).document(session_id).get()
            if not snap.exists:
                return None
            data = snap.to_dict() or {}
            return Session(
                id=data.get("id", session_id),
                user_id=data.get("user_id", ""),
                client_id=data.get("client_id"),
            )
        return self._sessions.get(session_id)

    def append(self, session_id: str, message: LlmMessage) -> None:
        fs = self._fs
        if fs is not None:
            # Append-only ordered subcollection so history() can read it back deterministically.
            messages = fs.collection(_SESSIONS).document(session_id).collection(_MESSAGES)
            seq = len(list(messages.stream()))
            messages.add({"seq": seq, "role": message.role, "content": message.content})
            return
        self._history.setdefault(session_id, []).append(message)

    def history(self, session_id: str) -> list[LlmMessage]:
        fs = self._fs
        if fs is not None:
            docs = (
                fs.collection(_SESSIONS)
                .document(session_id)
                .collection(_MESSAGES)
                .order_by("seq")
                .stream()
            )
            return [LlmMessage(role=d.get("role"), content=d.get("content")) for d in docs]
        return list(self._history.get(session_id, []))

    @property
    def emulator_host(self) -> str | None:
        """The Firestore emulator host in use, or None for the in-process default."""
        return firestore_emulator_host() if self._fs is not None else None
