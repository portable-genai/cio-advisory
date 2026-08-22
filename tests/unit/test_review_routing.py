"""R8 routing: an escalated advisory briefing is routed to Hrz7 via the shared review-kit.

Every advisory briefing requires human review (P-06), so rule R8 says it MUST be handed to the
Hrz7 maker-checker console rather than left as a boolean. These tests prove the producer half of
that loop end-to-end against the offline local router (an in-memory outbox), and prove the redact-
before-wire boundary so no raw client identifier reaches the console.

All data here is obviously fictional (synthetic client refs / identifiers).
"""

from __future__ import annotations

import pytest
from tests.conftest import load_service
from tests.fixtures import sample_clients

from cio_advisory.adapters._review_payload import briefing_to_review
from cio_advisory.adapters.local.review_router import LocalReviewRouter
from cio_advisory.config import Settings
from cio_advisory.domain.identity import Principal
from cio_advisory.domain.models import (
    AdvisoryBriefing,
    Citation,
    PortfolioAlignment,
    SourceType,
    SuitabilityAssessment,
    SuitabilityVerdict,
    TalkingPoint,
)

ACTOR = "rm@bank.test"
TENANT = "demo-bank"
BALANCED = sample_clients.BALANCED_CLIENT_ID
PRINCIPAL = Principal(
    subject=ACTOR, principals=("group:cio-analyst",), tenant=TENANT, source="test"
)


def _service_with_router(house_view, portfolio, llm, guardrail, redaction, tracer, audit, router):
    return load_service("AdvisoryService")(
        house_view,
        portfolio,
        llm,
        guardrail,
        redaction,
        tracer,
        audit,
        review_router=router,
    )


def test_brief_routes_escalated_briefing_to_outbox(
    house_view, portfolio, llm, guardrail, redaction, tracer, audit
):
    """A completed brief enqueues one review to the router's outbox, carrying the tenant (R8)."""
    router = LocalReviewRouter(Settings())
    service = _service_with_router(
        house_view, portfolio, llm, guardrail, redaction, tracer, audit, router
    )
    assert not router.outbox.pending()

    briefing = service.brief(BALANCED, PRINCIPAL)
    assert briefing.requires_human_review

    pending = router.outbox.pending()
    assert len(pending) == 1, "the escalated briefing must be routed to Hrz7 exactly once"
    review = pending[0].review
    assert review.action == "advisory_briefing:brief"
    assert review.case_ref == briefing.client_id
    assert review.maker == ACTOR
    assert review.tenant == TENANT


def _synthetic_citation(snippet: str) -> Citation:
    return Citation(
        source_id="hv-emerging-markets",
        source_type=SourceType.HOUSE_VIEW,
        title="EM equity house view",
        snippet=snippet,
    )


def _briefing_with_verdict(verdict: SuitabilityVerdict, snippet: str) -> AdvisoryBriefing:
    cite = _synthetic_citation(snippet)
    point = TalkingPoint(
        headline="Consider the EM equity theme",
        body="A discussion point for the RM to weigh.",
        house_view_theme="emerging-markets",
        suitability=SuitabilityAssessment(
            theme="emerging-markets",
            verdict=verdict,
            rationale="synthetic",
            citations=(cite,),
        ),
        citations=(cite,),
    )
    return AdvisoryBriefing(
        client_id="client-000042",
        talking_points=(point,),
        alignment=PortfolioAlignment(gaps=("emerging-markets",)),
    )


def test_payload_is_redacted_and_escalates_on_review_verdict():
    """The wire payload masks identifiers, maps severity, and dual-controls a REVIEW point."""
    # A citation snippet carrying a synthetic SG NRIC: it must be masked before the wire.
    snippet = "Guarantor NRIC S1234567D named in the schedule."
    review = briefing_to_review(
        _briefing_with_verdict(SuitabilityVerdict.REVIEW, snippet), maker=ACTOR, tenant=TENANT
    )

    assert review.tenant == TENANT
    assert review.severity == "medium"
    assert review.required_approvals == 2, "a REVIEW/UNSUITABLE point warrants dual control"
    # No raw NRIC survives into the payload the console receives.
    assert "S1234567D" not in review.summary
    assert "S1234567D" not in review.subject
    for citation in review.citations:
        assert "S1234567D" not in citation.snippet
    assert any(c.title == "EM equity house view" for c in review.citations)


def test_payload_low_severity_single_approval_when_all_suitable():
    """A briefing with only SUITABLE points is low severity and single-approval (still gated)."""
    review = briefing_to_review(
        _briefing_with_verdict(SuitabilityVerdict.SUITABLE, "No identifiers here."),
        maker=ACTOR,
        tenant=TENANT,
    )
    assert review.severity == "low"
    assert review.required_approvals == 1


def test_no_router_still_builds_briefing(
    house_view, portfolio, llm, guardrail, redaction, tracer, audit
):
    """Routing is optional: with no router bound, brief still returns the briefing."""
    service = _service_with_router(
        house_view, portfolio, llm, guardrail, redaction, tracer, audit, None
    )
    briefing = service.brief(BALANCED, PRINCIPAL)
    assert briefing.requires_human_review


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
