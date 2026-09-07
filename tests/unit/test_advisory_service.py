"""Unit tests for AdvisoryService : the SPEC §5 R1-safe advisory pipeline.

Pipeline (SPEC §5):
    redact(inputs) -> guardrail.screen(INPUT)
      -> [if blocked: audit BLOCKED + raise GuardrailBlockedError]
      -> portfolio.get_profile + get_portfolio
      -> house_view.retrieve (A2)  [empty -> RetrievalEmptyError]
      -> TalkingPointsService.synthesise (LLM + SuitabilityPolicy per point, drop UNSUITABLE)
      -> compute PortfolioAlignment -> attach not-advice disclaimer
      -> guardrail.screen(OUTPUT) -> CioReviewPolicy (always review) -> audit.record(redacted)

These tests use only in-memory fakes (no Google Cloud SDK).
"""

from __future__ import annotations

import pytest
from tests.conftest import BlockingGuardrail, load_service
from tests.fixtures import sample_clients

from cio_advisory.domain.errors import GuardrailBlockedError, RetrievalEmptyError
from cio_advisory.domain.identity import Principal
from cio_advisory.domain.models import (
    AdvisoryBriefing,
    Decision,
    Direction,
    SuitabilityVerdict,
)

ACTOR = "rm@bank.test"
BALANCED = sample_clients.BALANCED_CLIENT_ID
CONSERVATIVE = sample_clients.CONSERVATIVE_CLIENT_ID

# The verified principal the service runs on behalf of. A same-tenant (demo-bank) advisory
# RM: the local portfolio adapter stamps the seeded clients as owned by demo-bank, so this
# principal is entitled to them (object authorization, domain/entitlements.py).
PRINCIPAL = Principal(
    subject=ACTOR, principals=("group:cio-analyst",), tenant="demo-bank", source="test"
)
# A principal holding an explicit per-client grant, used where the portfolio is stubbed to
# return an owner-less profile (the grant admits access regardless of the client's tenant).
PRINCIPAL_WITH_GRANT = Principal(
    subject=ACTOR, principals=(f"client:{BALANCED}",), tenant="demo-bank", source="test"
)


# --------------------------------------------------------------------------- #
# Redaction happens BEFORE retrieval (P-04: minimise PII to model & store).
# --------------------------------------------------------------------------- #
def test_redaction_runs_before_retrieval(advisory_service, redaction):
    advisory_service.brief(BALANCED, PRINCIPAL)
    assert redaction.calls, "redaction.redact was never called"
    assert redaction.calls[0] == BALANCED


def test_redaction_strips_pii_before_anything_downstream(
    house_view, portfolio, llm, guardrail, redaction, tracer, audit
):
    # If a client id arrives carrying PII, the redacted form is what gets audited.
    service = load_service("AdvisoryService")(
        house_view, portfolio, llm, guardrail, redaction, tracer, audit
    )
    # The PII request maps to a real client once redacted to the bare ref; here we assert
    # the redaction boundary fires and the audit prompt is de-identified.
    pii = sample_clients.PII_CLIENT_REQUEST
    # Patch the fake portfolio to accept the noisy id by stripping to a known client.
    portfolio.get_profile = lambda _cid: sample_clients.BALANCED_PROFILE  # type: ignore[assignment]
    portfolio.get_portfolio = lambda _cid: sample_clients.BALANCED_PORTFOLIO  # type: ignore[assignment]
    # The stubbed profile is owner-less; an explicit client grant admits the request so this
    # test exercises the redaction boundary, not the (separately tested) tenant path.
    service.brief(pii, PRINCIPAL_WITH_GRANT)
    assert audit.events
    assert "S1234567A" not in audit.events[-1].redacted_prompt
    assert "jane.doe@example.com" not in audit.events[-1].redacted_prompt


# --------------------------------------------------------------------------- #
# Normal path : a well-formed, cited, human-review briefing.
# --------------------------------------------------------------------------- #
def test_briefing_is_well_formed_and_requires_review(advisory_service):
    briefing = advisory_service.brief(BALANCED, PRINCIPAL)

    assert isinstance(briefing, AdvisoryBriefing)
    assert briefing.client_id == BALANCED
    assert briefing.requires_human_review is True, "a briefing is always maker-checker gated"
    assert briefing.not_advice_disclaimer, "the not-advice disclaimer is mandatory"
    assert briefing.talking_points, "expected at least one talking point"


def test_talking_points_are_not_advice_and_cited(advisory_service):
    briefing = advisory_service.brief(BALANCED, PRINCIPAL)
    for tp in briefing.talking_points:
        assert tp.is_advice is False, "talking points are decision-support, never advice"
        assert tp.citations, "every talking point must carry a house-view citation"
        assert tp.suitability is not None, "every talking point carries a suitability check"
        assert all(c.source_id in sample_clients.HOUSE_VIEWS_BY_ID for c in tp.citations), (
            "citations map back to retrieved house views"
        )


def test_unsuitable_points_are_dropped_for_conservative_client(advisory_service):
    # The conservative client cannot hold the aggressive equity / alternatives overweights,
    # so those talking points must be dropped (never presented as a recommendation).
    briefing = advisory_service.brief(CONSERVATIVE, PRINCIPAL)
    verdicts = [
        tp.suitability.verdict for tp in briefing.talking_points if tp.suitability is not None
    ]
    assert SuitabilityVerdict.UNSUITABLE not in verdicts


def test_normal_path_audits_and_is_redacted(advisory_service, audit):
    advisory_service.brief(BALANCED, PRINCIPAL)
    assert audit.events, "the briefing must be audited"
    event = audit.events[-1]
    assert event.action == "briefing"
    assert event.actor == ACTOR
    assert event.decision in (Decision.ALLOWED, Decision.ESCALATED)


def test_pipeline_wrapped_in_tracer_span(advisory_service, tracer):
    advisory_service.brief(BALANCED, PRINCIPAL)
    assert tracer.spans, "the advisory pipeline must open at least one trace span"
    assert "advisory.brief" in tracer.spans


def test_escalated_audit_when_a_point_needs_review(advisory_service, audit):
    # The balanced client triggers REVIEW on the aggressive equity overweight, so the
    # briefing is audited as ESCALATED.
    advisory_service.brief(BALANCED, PRINCIPAL)
    assert any(e.decision is Decision.ESCALATED for e in audit.events)


# --------------------------------------------------------------------------- #
# Output guardrail screen runs (R1 full safety).
# --------------------------------------------------------------------------- #
def test_output_guardrail_is_screened(advisory_service, guardrail):
    advisory_service.brief(BALANCED, PRINCIPAL)
    directions = [d for _, d in guardrail.calls]
    assert Direction.INPUT in directions
    assert Direction.OUTPUT in directions, "the output must be screened (R1)"


# --------------------------------------------------------------------------- #
# Blocked input : hard error, no LLM call, audited BLOCKED.
# --------------------------------------------------------------------------- #
def test_blocked_input_raises_and_audits(house_view, portfolio, llm, redaction, tracer, audit):
    service = load_service("AdvisoryService")(
        house_view, portfolio, llm, BlockingGuardrail(block_input=True), redaction, tracer, audit
    )
    with pytest.raises(GuardrailBlockedError):
        service.brief(BALANCED, PRINCIPAL)
    assert llm.requests == [], "no synthesis after a blocked input"
    assert house_view.calls == [], "no retrieval after a blocked input"
    blocked = [e for e in audit.events if e.decision is Decision.BLOCKED]
    assert blocked, "a blocked input must be audited as BLOCKED"


def test_blocked_input_screens_input_only(house_view, portfolio, llm, redaction, tracer, audit):
    blocking = BlockingGuardrail(block_input=True)
    service = load_service("AdvisoryService")(
        house_view, portfolio, llm, blocking, redaction, tracer, audit
    )
    with pytest.raises(GuardrailBlockedError):
        service.brief(BALANCED, PRINCIPAL)
    directions = [d for _, d in blocking.calls]
    assert Direction.INPUT in directions
    assert Direction.OUTPUT not in directions


# --------------------------------------------------------------------------- #
# Empty governed KB : hard error (a briefing must be grounded).
# --------------------------------------------------------------------------- #
def test_empty_house_views_raises(
    empty_house_view, portfolio, llm, guardrail, redaction, tracer, audit
):
    service = load_service("AdvisoryService")(
        empty_house_view, portfolio, llm, guardrail, redaction, tracer, audit
    )
    with pytest.raises(RetrievalEmptyError):
        service.brief(BALANCED, PRINCIPAL)


# --------------------------------------------------------------------------- #
# Portfolio alignment is computed.
# --------------------------------------------------------------------------- #
def test_alignment_measures_against_the_model_portfolio_not_against_zero(advisory_service):
    """A gap is a distance from the published target, and this test used to say otherwise.

    It asserted that AI infrastructure was IN LINE for client-000042 because the portfolio
    held some equity, and that private markets was a gap because it held no alternatives.
    Both readings came from the same defect: the old alignment asked "is this asset class
    present" rather than "is it inside the band the bank published". The balanced client
    holds 30 percent equity against a 45 percent target with a 35 percent floor, so equity is
    the clearest gap this client has, and the theme that speaks to it is now reported as one.
    """
    briefing = advisory_service.brief(BALANCED, PRINCIPAL)
    alignment = briefing.alignment

    assert "AI infrastructure build-out" in alignment.gaps
    assert "AI infrastructure build-out" not in alignment.themes_in_line
    assert "Selective private markets" in alignment.gaps

    # Quality credit sits inside its band, so it is in line: held, and not short.
    assert "Quality investment-grade credit" in alignment.themes_in_line

    # The figures behind those words, which the old alignment could not produce at all.
    equity = next(g for g in alignment.allocation_gaps if g.asset_class.value == "equity")
    assert equity.status.value == "under"
    assert equity.drift == pytest.approx(-0.15)
    assert equity.value_gap == pytest.approx(180_000, abs=1.0)

    # And the honest half: a gap today's report says nothing about is named, not omitted.
    assert "real_assets" in alignment.uncovered_gaps


def test_a_talking_point_carries_the_computed_gap_it_addresses(advisory_service):
    """The link from a point to a gap is arithmetic, not something the model asserted."""
    briefing = advisory_service.brief(BALANCED, PRINCIPAL)
    linked = [p for p in briefing.talking_points if p.alignment is not None]
    assert linked, "every point resolved to a house view should carry its alignment"
    addressing = [p for p in linked if p.alignment.addresses is not None]
    assert addressing, "at least one point should address an under-allocated class"
    for point in addressing:
        assert point.alignment.addresses.status.value == "under"


def test_a_point_never_names_a_holding_the_client_does_not_own(advisory_service):
    """A model naming a fund the client does not hold is not describing this portfolio."""
    briefing = advisory_service.brief(BALANCED, PRINCIPAL)
    owned = {h.instrument for h in briefing.portfolio_summary.holdings}
    for point in briefing.talking_points:
        assert set(point.linked_holdings) <= owned, point.linked_holdings


def test_the_briefing_carries_the_portfolio_it_is_about(advisory_service):
    """The before-picture travels with the briefing, so a console need not ask twice."""
    briefing = advisory_service.brief(BALANCED, PRINCIPAL)
    summary = briefing.portfolio_summary
    assert summary is not None
    assert summary.client_id == BALANCED
    assert summary.total_value == pytest.approx(1_200_000)
    assert summary.model_portfolio is not None
    assert summary.gaps_under(), "this client is short of something; the summary should say so"
    assert briefing.house_views_considered, "the themes the briefing weighed are reported"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
