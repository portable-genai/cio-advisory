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
    GoldenExample,
    _build_adapters,
    _make_service,
    brief_example,
    load_golden,
    load_thresholds_from_rubrics,
    score_citation_accuracy,
    score_gap_coverage,
    score_groundedness,
    score_no_advice_safety,
    score_pii_safety,
    score_suitability_accuracy,
)

from cio_advisory.domain.models import AdvisoryBriefing, SuitabilityVerdict

#: The reviewed bars, read from `eval/rubrics/*.yaml` exactly as the gate reads them. The
#: module-level dict this used to import is gone: a threshold written as a Python literal
#: carries no argument, and having both was two homes for one number.
THRESHOLDS = load_thresholds_from_rubrics()


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


def test_gap_coverage_can_go_red() -> None:
    """The red case is a briefing that stops speaking to a gap it could have closed.

    Chosen on a client with an addressable gap, so the proof is not vacuous: dropping every
    point that addresses one is precisely the regression this metric exists to catch, and it
    is invisible to every other metric here. A briefing whose remaining points are still
    grounded, still cited, still correctly suitability-tagged and still free of advice scores
    a clean sheet everywhere else while no longer being about this client's portfolio.
    """
    example = next(e for e in _GOLDEN if _has_addressable_gap(e))
    produced, _ = _brief(example)
    addressing = [
        p for p in produced.talking_points if p.alignment is not None and p.alignment.addresses
    ]
    assert addressing, "the proof needs a briefing that closes at least one gap"
    assert_can_go_red(
        lambda b: score_gap_coverage(b, example),
        green=produced,
        red=replace(
            produced,
            talking_points=tuple(p for p in produced.talking_points if p not in addressing),
        ),  # every gap-filling point quietly gone
        threshold=THRESHOLDS["gap_coverage"],
        metric="gap_coverage",
    )


def _has_addressable_gap(example: GoldenExample) -> bool:
    produced, _ = _brief(example)
    return any(
        p.alignment is not None and p.alignment.addresses is not None
        for p in produced.talking_points
    )


# --------------------------------------------------------------------------- #
# Retrieval quality: the metrics that can see a knowledge base going quiet
# --------------------------------------------------------------------------- #
def test_the_retrieval_metrics_can_go_red() -> None:
    """Run the SHIPPED proof, the same one the scored run executes before it scores.

    Two directions, and only one of them is obvious. A retriever that returns nothing loses
    recall; a retriever that returns everything GAINS recall and loses precision, which is
    exactly how a knowledge base is "fixed" after a recall complaint.
    """
    from eval.run_eval import load_thresholds_from_rubrics, prove_retrieval_metrics_can_go_red

    prove_retrieval_metrics_can_go_red(load_thresholds_from_rubrics())


def test_the_labelled_queries_are_scored_against_the_real_retriever() -> None:
    """Not a fake keyed off the case, which would make recall 1.0 by construction.

    The fake house-view adapter the rest of this gate uses returns exactly the views the golden
    case declares, so scoring retrieval through it would be a tautology with a threshold. These
    metrics go through `LocalFtsHouseViewAdapter`, the SQLite FTS5 index the offline briefing
    path actually queries, and its top-k carries real noise.
    """
    from eval.run_eval import score_retrieval_quality

    scores = score_retrieval_quality()
    assert scores.n_queries >= 10, "too few labelled queries to say anything about recall"
    assert scores.n_relevant >= 10, "too few labelled positives to express a recall bar"
    # Precision is well below 1.0 because most queries have one right answer and the cut is
    # five. If this ever reads 1.0 the retriever has stopped returning anything but the answer,
    # which would mean the index, not the metric, has changed shape.
    assert 0.0 < scores.precision_at_k < 1.0


def test_the_retrieval_index_does_not_depend_on_the_developer_s_home_directory() -> None:
    """A gate whose result depends on `$HOME` is not a gate.

    The adapter's default is a SQLite file under the running user's home directory that
    self-seeds once and then persists. On the machine this was written on that file still held
    a previous quarter's four house views, and every labelled query scored zero against a
    retriever that was in fact working.
    """
    from eval.run_eval import _retrieval_index

    index = _retrieval_index()
    assert index._db_path == ":memory:"


def test_every_scored_metric_has_a_reviewed_bar_and_every_bar_is_scored() -> None:
    """Both directions. The second is the one nobody writes by hand, and the one that rots."""
    from agent_eval_kit import load_rubrics
    from agent_eval_kit.rubrics import RubricError
    from eval.run_eval import RUBRICS, SCORED

    load_rubrics(RUBRICS).assert_covers(SCORED)
    with pytest.raises(RubricError, match="reads as governance"):
        load_rubrics(RUBRICS).assert_covers(SCORED[:-1])
