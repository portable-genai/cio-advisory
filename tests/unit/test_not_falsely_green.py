"""Prove every eval metric can go RED: a degraded briefing must score below its threshold.

A metric that cannot fail proves nothing. Each scorer in ``eval/run_eval.py`` is fed the SAME
advisory briefing twice: once as the service produced it (green) and once carrying exactly the
defect the metric exists to catch (red). The scorers are imported rather than re-implemented,
so a scorer that silently became a constant 1.0 breaks this build.

The case is chosen so the proof is not itself vacuous: a briefing with no talking points, or an
example with no expected verdicts, scores 1.0 on several of these metrics by construction.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from agent_eval_kit import assert_can_go_red
from eval.run_eval import (
    DEFAULT_DATASET,
    THRESHOLDS,
    GoldenExample,
    _build_adapters,
    _make_service,
    brief_example,
    load_golden,
    score_citation_accuracy,
    score_groundedness,
    score_no_advice_safety,
    score_pii_safety,
    score_suitability_accuracy,
)

from cio_advisory.domain.models import AdvisoryBriefing, SuitabilityVerdict

_GOLDEN = load_golden(DEFAULT_DATASET)
#: An example with verdicts to get right, so suitability_accuracy scores something real.
_WITH_VERDICTS = next(e for e in _GOLDEN if e.expected_verdicts)
#: An example carrying a planted identifier, so pii_safety has a target to miss.
_WITH_PII = next(e for e in _GOLDEN if e.pii_in_inputs)


def _brief(example: GoldenExample) -> tuple[AdvisoryBriefing, list]:
    """Drive the real service over one golden example; return the briefing and its audit slice."""
    adapters = _build_adapters(_GOLDEN)
    service = _make_service(adapters)
    before = len(adapters.audit.events)
    briefing = brief_example(service, adapters, example)
    return briefing, adapters.audit.events[before:]


@pytest.fixture(scope="module")
def briefing() -> AdvisoryBriefing:
    produced, _ = _brief(_WITH_VERDICTS)
    assert produced.talking_points, "the proof needs a briefing that actually says something"
    return produced


def test_groundedness_can_go_red(briefing: AdvisoryBriefing) -> None:
    assert_can_go_red(
        score_groundedness,
        green=briefing,
        red=replace(
            briefing,
            talking_points=tuple(replace(p, citations=()) for p in briefing.talking_points),
        ),  # talking points with no house view behind them
        threshold=THRESHOLDS["groundedness"],
        metric="groundedness",
    )


def test_citation_accuracy_can_go_red(briefing: AdvisoryBriefing) -> None:
    fabricated = replace(briefing.talking_points[0].citations[0], source_id="fabricated-house-view")
    assert_can_go_red(
        lambda b: score_citation_accuracy(b, _WITH_VERDICTS),
        green=briefing,
        red=replace(
            briefing,
            talking_points=tuple(
                replace(p, citations=(fabricated,)) for p in briefing.talking_points
            ),
        ),  # cites a house view that was never retrieved
        threshold=THRESHOLDS["citation_accuracy"],
        metric="citation_accuracy",
    )


def test_suitability_accuracy_can_go_red(briefing: AdvisoryBriefing) -> None:
    flipped = {
        theme: (
            SuitabilityVerdict.UNSUITABLE
            if verdict is not SuitabilityVerdict.UNSUITABLE
            else SuitabilityVerdict.SUITABLE
        )
        for theme, verdict in _WITH_VERDICTS.expected_verdicts.items()
    }
    assert_can_go_red(
        lambda example: score_suitability_accuracy(briefing, example),
        green=_WITH_VERDICTS,
        red=replace(_WITH_VERDICTS, expected_verdicts=flipped),  # every verdict now disagrees
        threshold=THRESHOLDS["suitability_accuracy"],
        metric="suitability_accuracy",
    )


def test_no_advice_safety_can_go_red(briefing: AdvisoryBriefing) -> None:
    assert_can_go_red(
        score_no_advice_safety,
        green=briefing,
        red=replace(briefing, not_advice_disclaimer=""),  # the disclaimer quietly dropped
        threshold=THRESHOLDS["no_advice_safety"],
        metric="no_advice_safety",
    )


def test_pii_safety_can_go_red() -> None:
    """The red case re-introduces a raw identifier into the briefing AFTER redaction ran."""
    produced, events = _brief(_WITH_PII)
    assert_can_go_red(
        lambda b: score_pii_safety(b, _WITH_PII, events),
        green=produced,
        red=replace(
            produced,
            talking_points=tuple(
                replace(p, body=f"{p.body} Client NRIC S1234567D on file.")
                for p in produced.talking_points
            ),
        ),
        threshold=THRESHOLDS["pii_safety"],
        metric="pii_safety",
    )
