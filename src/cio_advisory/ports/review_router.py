"""ReviewRouterPort: the boundary that routes an escalated advisory briefing to human-review-console
(rule R8).

Every :class:`~cio_advisory.domain.models.AdvisoryBriefing` is consequential decision-support and
always requires human review (maker-checker, P-06): the assistant is the maker, the relationship
manager is the checker. Rule R8 says a producer that sets ``requires_human_review`` MUST route the
item to the human-review-console Human-Review & Maker-Checker Console rather than terminate the
escalation in a per-repo boolean. This port is that hand-off. The domain stays pure: the adapter
(not this port) depends on the shared ``review-kit`` client and does the S2S submission.

The briefing carries no tenant field (a briefing is keyed by ``client_id``), so the tenant is a
call parameter threaded from the verified :class:`~cio_advisory.domain.identity.Principal`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import AdvisoryBriefing


@runtime_checkable
class ReviewRouterPort(Protocol):
    def route(self, briefing: AdvisoryBriefing, *, maker: str, tenant: str = "") -> None:
        """Route an escalated briefing to human-review-console for review (idempotent per client is
        ideal).
        """
        ...
