"""Human-in-the-loop (maker-checker) policy for B3 : General Principle P-06.

B3 is a *decision-support* assistant, never an autonomous adviser. P-06 (maker-checker)
requires that a human : here the relationship manager : reviews any consequential output
before it is relied upon. This module centralises that gate so the AdvisoryService
applies identical rules and the threshold is auditable in one place.

Policy (SPEC §5):
* An :class:`AdvisoryBriefing` is **always** consequential and therefore always
  ``requires_human_review=True``: the assistant proposes (maker), the RM disposes
  (checker). The assistant never advises.
* A briefing whose talking points include any REVIEW or UNSUITABLE suitability verdict
  is *escalated* (a stronger signal than ordinary review) so the RM gives those points
  extra scrutiny before any client conversation.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import SuitabilityVerdict, TalkingPoint

#: Verdicts that escalate a briefing beyond ordinary review.
_ESCALATING_VERDICTS: frozenset[SuitabilityVerdict] = frozenset(
    {SuitabilityVerdict.REVIEW, SuitabilityVerdict.UNSUITABLE}
)


@dataclass(frozen=True, slots=True)
class CioReviewPolicy:
    """Maker-checker gate (P-06) for advisory briefings. Pure decision logic."""

    def requires_review(self, talking_points: tuple[TalkingPoint, ...]) -> bool:
        """An advisory briefing always requires human review (the RM is the checker).

        Returns True unconditionally: a personalised advisory briefing is consequential
        decision-support and the RM must sign off before any client conversation. The
        argument is accepted for symmetry with :meth:`escalates` and future tuning.
        """
        return True

    def escalates(self, talking_points: tuple[TalkingPoint, ...]) -> bool:
        """Whether any talking point carries a REVIEW / UNSUITABLE suitability verdict.

        An escalating briefing still requires review (it always does); ``escalates``
        marks that one or more points need *extra* scrutiny, which the service records
        on the audit trail as an ESCALATED decision.
        """
        for point in talking_points:
            assessment = point.suitability
            if assessment is not None and assessment.verdict in _ESCALATING_VERDICTS:
                return True
        return False
