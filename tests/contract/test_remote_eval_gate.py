"""Contract test : the platform ``RemoteEvalGateAdapter`` speaks A4's hardened wire shape.

The A4 ``model-quality-gate`` gate rejects the loose shapes a laxer client sends (a bare
``target`` string, a top-level ``metrics`` list, and unregistered metric names that a laxer
gate would silently PASS). These respx tests pin the contract at the HTTP
boundary : a structured ``target``, a top-level ``dataset_id`` equal to ``target.dataset_id``,
metric selection by ``bundle`` only, the ``results`` response key, and the ``/v1/gate``
decision endpoint. Following the local-adapter test convention, the real adapter is exercised
in-process (no GCP SDK) with the network mocked.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from cio_advisory.adapters.platform.remote_eval_gate import (
    RemoteEvalGateAdapter,
    RemoteEvalGateError,
)
from cio_advisory.config import Settings
from cio_advisory.domain.models import EvalReport

_BASE = "http://a4.test"
_BUNDLE = "doc3-cio-advisory"


def _adapter(monkeypatch: pytest.MonkeyPatch) -> RemoteEvalGateAdapter:
    # The base URL is read in __init__, so set it before constructing the adapter.
    monkeypatch.setenv("QUALITY_GATE_URL", _BASE)
    return RemoteEvalGateAdapter(Settings())


@respx.mock
def test_evaluate_posts_hardened_contract_and_parses_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The hardened Hrz4 /v1/evaluations response carries the durable identifiers on the
    # PLAIN evaluation path too (the hardened ``_parse`` refuses a body without them), so the
    # fixture models the full shape, n_examples included: omitting the count left it at 0,
    # and the old fail-open verdict still read PASSED, a promotion certified by nothing.
    route = respx.post(f"{_BASE}/v1/evaluations").mock(
        return_value=httpx.Response(200, json=_attested_eval_report())
    )

    report = _adapter(monkeypatch).evaluate("eval/datasets/golden_clients.jsonl")

    assert route.called
    sent = json.loads(route.calls.last.request.content)

    # Only the three hardened keys are sent : a structured target, a top-level dataset id,
    # and the bundle. No top-level ``metrics`` list / bare metric names of any kind.
    assert set(sent) == {"target", "dataset_id", "bundle"}
    assert isinstance(sent["target"], dict)
    assert set(sent["target"]) == {"model", "prompt_version", "dataset_id", "system"}

    # The pinned reasoning model + a stable prompt version drive the target.
    assert sent["target"]["model"] == Settings().models.reasoning
    assert sent["target"]["prompt_version"]  # stable, non-empty

    # dataset_id is the basename without ``.jsonl`` and MUST match target.dataset_id (A4 422s).
    assert sent["dataset_id"] == "golden_clients"
    assert sent["dataset_id"] == sent["target"]["dataset_id"]

    # Metric selection is by bundle only; assert no unregistered metric name leaks into the body.
    assert sent["bundle"] == _BUNDLE
    assert "metrics" not in sent
    assert "metrics" not in sent["target"]

    # The ``results`` list is parsed into the domain EvalReport.
    assert isinstance(report, EvalReport)
    assert report.dataset == "eval/datasets/golden_clients.jsonl"
    assert [r.metric for r in report.results] == ["groundedness", "no_advice_safety"]
    assert report.results[0].score == pytest.approx(0.95)
    assert report.results[0].threshold == pytest.approx(0.80)

    # The scored-example count is carried through from the service, not hardcoded. It is
    # what ``passed`` fails closed on, so an adapter that dropped it would report every
    # cloud evaluation as FAILED while still parsing perfectly good metric scores.
    assert report.n_examples == 24
    assert report.passed is True


@respx.mock
def test_evaluate_carries_the_attested_evidence_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """The durable identifiers Hrz4 attested with must survive the adapter, not be dropped.

    An adapter that rebuilds the report from three fields (dataset, results, n_examples)
    silently discards the run id, the dataset version and digest, the evaluator, the
    schema version and the artifact references : precisely the evidence that makes a promotion
    auditable, and precisely what the service refuses to answer without. A report
    that scores well but cannot say which run produced it is not model-risk evidence.
    """
    respx.post(f"{_BASE}/v1/evaluations").mock(
        return_value=httpx.Response(200, json=_attested_eval_report())
    )

    report = _adapter(monkeypatch).evaluate("eval/datasets/golden_clients.jsonl")

    assert report.run_id == "run-fictional-0001"
    assert report.dataset_version == "golden@2026-08-01"
    assert report.dataset_digest.startswith("sha256:")
    assert report.evaluator == "hrz4-ai-quality (FICTIONAL)"
    assert report.schema_version == "eval-run/v1"
    assert report.artifact_refs == ("gs://fictional-hrz4-evidence/run-fictional-0001/report.json",)
    assert report.attested is True


def _attested_eval_report() -> dict:
    """Attested evaluation evidence in the full hardened shape, obviously fictional.

    Every score/threshold/passed row is internally CONSISTENT, because the hardened Hrz4
    contract (``agent_eval_kit.gate_client.PromotionGateClient._parse``) re-derives each
    verdict and refuses a contradiction rather than trusting the flag.
    """
    return {
        "results": [
            {"metric": "groundedness", "score": 0.95, "threshold": 0.80, "passed": True},
            {"metric": "no_advice_safety", "score": 1.0, "threshold": 0.99, "passed": True},
        ],
        "n_examples": 24,
        "run_id": "run-fictional-0001",
        "dataset_version": "golden@2026-08-01",
        "dataset_digest": "sha256:feedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedface",
        "evaluator": "hrz4-ai-quality (FICTIONAL)",
        "schema_version": "eval-run/v1",
        "artifact_refs": ["gs://fictional-hrz4-evidence/run-fictional-0001/report.json"],
        "attested": True,
    }


#: The complete GateDecision the hardened Hrz4 promotion endpoint returns: attested eval
#: evidence with durable identifiers, a red-team report whose aggregate matches its rows,
#: the model-card and MRM references, and a top-level verdict consistent with all of it. A
#: naked ``{"passed": true}`` is the unhardened thin shape and does not model the
#: service; this fixture is what the promotion authority actually certifies with. (This
#: repo-local adapter reads the aggregate ``passed``; the fixture still carries the full
#: evidence so the next client hardening lands as a pin bump, not a fixture rewrite.)
_GATE_DECISION = {
    "passed": True,
    "eval_report": _attested_eval_report(),
    "redteam_report": {
        "passed": True,
        "results": [
            {"case": "prompt-injection-01", "passed": True, "blocked": True},
            {"case": "pii-exfil-01", "passed": True, "blocked": True},
        ],
    },
    "model_card_ref": "gs://fictional-hrz4-evidence/model-cards/doc3-cio-advisory.md",
    "mrm_evidence_ref": "gs://fictional-hrz4-evidence/mrm/doc3-cio-advisory-2026-08.json",
}


@respx.mock
def test_gate_posts_to_v1_gate_and_returns_bool(monkeypatch: pytest.MonkeyPatch) -> None:
    route = respx.post(f"{_BASE}/v1/gate").mock(
        return_value=httpx.Response(200, json=_GATE_DECISION)
    )

    passed = _adapter(monkeypatch).gate("data/golden.jsonl")

    assert route.called
    sent = json.loads(route.calls.last.request.content)
    assert set(sent) == {"target", "dataset_id", "bundle"}
    assert sent["bundle"] == _BUNDLE
    assert sent["dataset_id"] == "golden"
    assert sent["dataset_id"] == sent["target"]["dataset_id"]
    assert passed is True


@respx.mock
def test_gate_fail_is_reached_through_consistent_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A FAIL decision still carries full, self-consistent evidence: one metric row under
    its threshold with ``passed: false``, the eval aggregate false, and the top-level
    verdict agreeing. A contradictory body is a service defect, not a FAIL."""
    failing_report = _attested_eval_report()
    failing_report["results"] = [
        {"metric": "groundedness", "score": 0.62, "threshold": 0.80, "passed": False},
        {"metric": "no_advice_safety", "score": 1.0, "threshold": 0.99, "passed": True},
    ]
    failing_report["passed"] = False
    body = {**_GATE_DECISION, "passed": False, "eval_report": failing_report}
    respx.post(f"{_BASE}/v1/gate").mock(return_value=httpx.Response(200, json=body))

    assert _adapter(monkeypatch).gate("data/golden.jsonl") is False


@respx.mock
def test_non_2xx_raises_remote_eval_gate_error(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.post(f"{_BASE}/v1/evaluations").mock(
        return_value=httpx.Response(422, text="unregistered metric name")
    )

    with pytest.raises(RemoteEvalGateError):
        _adapter(monkeypatch).evaluate("golden.jsonl")
