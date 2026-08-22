"""On-prem placeholder for ``AgentRuntimePort`` : the on-premise migration target.

One of the reversibility (P-02) migration placeholders: in the managed profile this port
binds to the Agent Runtime (reasoningEngine) adapter; switching ``profile`` to ``onprem``
rebinds it here. The adapter constructs cleanly with **no external dependencies** and
structurally satisfies the same Protocol as the managed adapter, so the contract tests
prove interface parity. Porting B3 hosting on-premise is *only* a matter of filling these
bodies in : the core domain logic is unchanged.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import AdvisoryBriefing, Session

_MESSAGE = (
    "On-prem AgentRuntimePort adapter is a migration placeholder; implement against your "
    "on-premise platform. Core domain logic is unchanged."
)


class OnPremAgentRuntimeAdapter:
    """Placeholder agent-runtime adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def query(self, session: Session, message: str) -> AdvisoryBriefing:
        raise NotImplementedError(_MESSAGE)

    def health(self) -> bool:
        raise NotImplementedError(_MESSAGE)
