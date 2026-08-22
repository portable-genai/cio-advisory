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
def test_alignment_is_computed(advisory_service):
    briefing = advisory_service.brief(BALANCED, PRINCIPAL)
    alignment = briefing.alignment
    # The balanced portfolio holds equity and fixed income, both OVERWEIGHT house views,
    # so those themes are in-line; it holds no alternatives, so private markets is a gap.
    assert "AI infrastructure build-out" in alignment.themes_in_line
    assert "Selective private markets" in alignment.gaps


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
