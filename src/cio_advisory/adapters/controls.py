"""The runtime-control seam: what a switched-off control binds, and what a caller reports.

Two halves, both profile-independent, so they live beside the adapter families rather than in
one of them.

**Disabled adapters.** When a deployment switches a cheap runtime control off
(``CIO_GUARDRAIL``, ``CIO_PII_REDACTION``, ``CIO_REVIEW_ROUTING``), the container binds one of
these instead of the profile's class. Each satisfies its port and does nothing, so no service
grows a ``None`` branch, and the container logs the posture at startup.

**Recording wrapper.** Every caller that hands a briefing to the review router (the API routes,
the agent tools, the CLI and the MCP server) builds its service around a
:class:`RecordingReviewRouter` for that one call, so what it returns can say what happened to
the hand-off: ``routed``, ``failed``, ``off`` or ``not_required``. A failure is logged and
absorbed here, because an already-assembled, already-audited briefing must not fail on a
console outage, but it is no longer invisible: the caller reports ``failed``.

No redaction-disclosure wrapper lives here. The redaction port in this service masks the
opaque client reference a caller names, which only the guardrail and the audit trail read; no
user free text reaches the model through it, so there is nothing for ``input_redacted`` to
disclose.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from ..config import Settings
from ..domain.models import AdvisoryBriefing, Direction, GuardrailVerdict, RedactionResult

_log = logging.getLogger(__name__)


class ReviewRouting(StrEnum):
    """What happened to the human-review hand-off for one result."""

    ROUTED = "routed"
    FAILED = "failed"
    OFF = "off"
    NOT_REQUIRED = "not_required"


#: What each outcome means, in the words a relationship manager needs. A briefing that
#: requires review but is not queued must say so rather than read as reviewed.
REVIEW_ROUTING_TEXT: dict[ReviewRouting, str] = {
    ReviewRouting.ROUTED: "Sent to the review console.",
    ReviewRouting.FAILED: (
        "Could not reach the review console; this briefing is not queued for review."
    ),
    ReviewRouting.OFF: (
        "Review routing is off in this deployment; this briefing is not queued for review."
    ),
    ReviewRouting.NOT_REQUIRED: "No human review was required, so nothing was routed.",
}


# --------------------------------------------------------------------------- #
# Disabled adapters
# --------------------------------------------------------------------------- #
class DisabledGuardrail:
    """GuardrailPort with the guardrail switched off: allows everything, text unchanged."""

    enabled = False

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def screen(self, text: str, direction: Direction) -> GuardrailVerdict:
        return GuardrailVerdict(
            allowed=True, direction=direction, sanitized_text=text, reason="guardrail off"
        )


class DisabledRedaction:
    """PIIRedactionPort with redaction switched off: text unchanged, no findings."""

    enabled = False

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def redact(self, text: str) -> RedactionResult:
        return RedactionResult(text=text, findings=())


class DisabledReviewRouter:
    """ReviewRouterPort with routing switched off: nothing is submitted anywhere."""

    enabled = False

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def route(self, briefing: AdvisoryBriefing, *, maker: str, tenant: str = "") -> None:
        return None


# --------------------------------------------------------------------------- #
# Recording wrapper
# --------------------------------------------------------------------------- #
class RecordingReviewRouter:
    """Wraps the bound review router for one call and records each hand-off's outcome.

    The service hands a briefing over only when it requires review, so a call that never
    reaches :meth:`route` reports ``not_required``.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._outcomes: list[ReviewRouting] = []

    def route(self, briefing: AdvisoryBriefing, *, maker: str, tenant: str = "") -> None:
        if not getattr(self._inner, "enabled", True):
            self._outcomes.append(ReviewRouting.OFF)
            return
        try:
            self._inner.route(briefing, maker=maker, tenant=tenant)
        except Exception as exc:  # noqa: BLE001 - the outcome is reported, never raised
            _log.warning("human-review hand-off failed: %s", type(exc).__name__)
            self._outcomes.append(ReviewRouting.FAILED)
            return
        self._outcomes.append(ReviewRouting.ROUTED)

    @property
    def outcome(self) -> ReviewRouting:
        """One value for the caller: any failure wins, then off, then routed."""
        for worst in (ReviewRouting.FAILED, ReviewRouting.OFF, ReviewRouting.ROUTED):
            if worst in self._outcomes:
                return worst
        return ReviewRouting.NOT_REQUIRED
