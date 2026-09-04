"""Shared conversion from an escalated advisory briefing to an ``review-kit`` Review payload.

Lives in the adapter layer (not the pure domain) because it depends on the kit. Redacts the subject
descriptor, summary and citation snippets before they leave the process (R1 / P-04 boundary), using
the shared ``pii-kit`` (the same pack the redaction adapter uses), so no raw client identifier
reaches human-review-console over the wire; human-review-console redacts again before its own audit
write (defense in depth). The maker (the RM/assistant that originated the briefing) and the tenant
are asserted here and trusted by human-review-console because this is an authenticated S2S caller
(per-hop OBO is the deferred next layer).
"""

from __future__ import annotations

import re

from pii_kit import NATIONAL_ID_PATTERNS, UNIVERSAL_PATTERNS, national_patterns_for
from pii_kit import redact as pii_redact
from review_kit import Citation as KitCitation
from review_kit import Review

from ..domain.models import AdvisoryBriefing, Citation, SuitabilityVerdict

# Cap the citations carried on the wire: enough to let a reviewer trace the briefing without
# copying the entire evidence set into the review console.
_MAX_CITATIONS = 8

# The review console is a shared sink: a briefing for an SG client may still quote an HK id, so the
# payload is scrubbed against every jurisdiction's national ids plus universal email/phone,
# regardless of which market configured this producer.
_ALL_PATTERNS = (
    *national_patterns_for(tuple(NATIONAL_ID_PATTERNS.keys())),
    *UNIVERSAL_PATTERNS,
)

# A briefing carries no single risk band; its escalation signal is the strongest per-point
# suitability verdict. Ordered weakest -> strongest so ``max`` picks the most severe, mapped to a
# console severity string. UNSUITABLE points are dropped upstream, but the mapping stays complete.
_SEVERITY_ORDER: tuple[SuitabilityVerdict, ...] = (
    SuitabilityVerdict.SUITABLE,
    SuitabilityVerdict.REVIEW,
    SuitabilityVerdict.UNSUITABLE,
)
_SEVERITY_LABEL: dict[SuitabilityVerdict, str] = {
    SuitabilityVerdict.SUITABLE: "low",
    SuitabilityVerdict.REVIEW: "medium",
    SuitabilityVerdict.UNSUITABLE: "high",
}
_ESCALATING = frozenset({SuitabilityVerdict.REVIEW, SuitabilityVerdict.UNSUITABLE})


def _redact(text: str) -> str:
    """Mask every jurisdiction's national identifiers plus email/phone before the wire."""
    return re.sub(r"\s+", " ", pii_redact(text, _ALL_PATTERNS)).strip()


def _verdicts(briefing: AdvisoryBriefing) -> list[SuitabilityVerdict]:
    return [p.suitability.verdict for p in briefing.talking_points if p.suitability is not None]


def _strongest_verdict(briefing: AdvisoryBriefing) -> SuitabilityVerdict:
    """The briefing's most severe per-point suitability verdict, or SUITABLE when it has none."""
    present = [v for v in _verdicts(briefing) if v in _SEVERITY_ORDER]
    if not present:
        return SuitabilityVerdict.SUITABLE
    return max(present, key=_SEVERITY_ORDER.index)


def _escalated(briefing: AdvisoryBriefing) -> bool:
    """Mirror the review policy: any REVIEW/UNSUITABLE talking point escalates."""
    return any(v in _ESCALATING for v in _verdicts(briefing))


def _briefing_citations(briefing: AdvisoryBriefing) -> list[Citation]:
    out: list[Citation] = []
    for point in briefing.talking_points:
        out.extend(point.citations)
        if point.suitability is not None:
            out.extend(point.suitability.citations)
    return out


def _kit_citations(briefing: AdvisoryBriefing) -> tuple[KitCitation, ...]:
    seen: set[str] = set()
    out: list[KitCitation] = []
    for c in _briefing_citations(briefing):
        if c.source_id in seen:
            continue
        seen.add(c.source_id)
        out.append(KitCitation(source_id=c.source_id, title=c.title, snippet=_redact(c.snippet)))
        if len(out) >= _MAX_CITATIONS:
            break
    return tuple(out)


def briefing_to_review(briefing: AdvisoryBriefing, *, maker: str, tenant: str = "") -> Review:
    """Build the review a producer submits to human-review-console when an advisory briefing
    escalates.
    """
    n_flagged = sum(1 for v in _verdicts(briefing) if v in _ESCALATING)
    descriptor = (
        f"CIO advisory briefing for client {briefing.client_id} "
        f"({len(briefing.talking_points)} talking points)"
    )
    summary = (
        f"talking_points={len(briefing.talking_points)}; "
        f"review_or_unsuitable={n_flagged}; "
        f"gaps={len(briefing.alignment.gaps)}; overweights={len(briefing.alignment.overweights)}"
    )
    verdict = _strongest_verdict(briefing)
    return Review(
        action="advisory_briefing:brief",
        subject=_redact(descriptor),
        maker=maker,
        tenant=tenant,
        summary=_redact(summary),
        severity=_SEVERITY_LABEL[verdict],
        # Dual control when the briefing escalates (any REVIEW/UNSUITABLE point); a briefing is
        # always maker-checker gated, escalation raises it to four-eyes.
        required_approvals=2 if _escalated(briefing) else 1,
        sod_group="advisory-maker-checker",
        case_ref=briefing.client_id,
        citations=_kit_citations(briefing),
    )
