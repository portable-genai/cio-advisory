"""Local agent-runtime adapter (AgentRuntimePort): in-process advisory pipeline.

The ``local`` profile's stand-in for **Agent Runtime** (the hosted reasoning engine):
rather than calling a deployed endpoint, it assembles the domain ``AdvisoryService`` from
the other local adapters and produces a briefing in-process. Under ``local`` the platform
client runs the app itself (a laptop runs one app, not the whole platform). SDK-free and
unconditional.

``query(session, message)`` treats ``message`` as the opaque client id (the same contract
the GCP runtime adapter honours) and returns the :class:`AdvisoryBriefing`.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import AdvisoryBriefing, Session


class LocalAgentRuntimeAdapter:
    """In-process agent runtime: builds briefings via the local AdvisoryService."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._service = None

    def _advisory_service(self):  # type: ignore[no-untyped-def]
        if self._service is None:
            from ...domain.advisory_service import AdvisoryService
            from .audit import LocalAppendOnlyAuditAdapter
            from .guardrail import LocalHeuristicGuardrailAdapter
            from .house_views import LocalFtsHouseViewAdapter
            from .llm import LocalDeterministicLLMAdapter
            from .portfolio import LocalPortfolioAdapter
            from .redaction import LocalRegexRedactionAdapter
            from .tracer import LocalNoopTracerAdapter

            self._service = AdvisoryService(
                house_view=LocalFtsHouseViewAdapter(self._settings),
                portfolio=LocalPortfolioAdapter(self._settings),
                llm=LocalDeterministicLLMAdapter(self._settings),
                guardrail=LocalHeuristicGuardrailAdapter(self._settings),
                redaction=LocalRegexRedactionAdapter(self._settings),
                tracer=LocalNoopTracerAdapter(self._settings),
                audit=LocalAppendOnlyAuditAdapter(self._settings),
            )
        return self._service

    def query(self, session: Session, message: str) -> AdvisoryBriefing:
        from ...domain.identity import Principal

        # The runtime acts as a same-tenant (demo-bank) advisory identity; the session
        # user is the audit actor. Object authorization is enforced in the service.
        principal = Principal(
            subject=session.user_id,
            principals=("group:cio-analyst",),
            tenant="demo-bank",
            source="local-runtime",
        )
        return self._advisory_service().brief(message, principal)

    def health(self) -> bool:
        return True
