"""Remote-platform evaluation-gate adapter : thin HTTP client to A4.

At promotion time B3 must pass the shared **A4 AI Quality / model-risk** gate
(``model-quality-gate``) before it can be deployed (R5). This adapter implements
:class:`EvaluationGatePort` by POSTing a structured target to A4's ``POST /v1/evaluations``
endpoint and mapping the returned ``results`` list into the domain :class:`EvalReport`
(SPEC §6, A4 contract). It also exposes a companion :meth:`gate` that asks A4's
``POST /v1/gate`` for the single promotion pass/fail decision. The offline gate in
``eval/run_eval.py`` remains the in-repo merge guard; A4 is the richer, judged check run
pre-promotion.

Contract notes (A4 is hardened and rejects the loose shapes a laxer gate would tolerate):

* The request body is ``{"target": {model, prompt_version, dataset_id, system}, "dataset_id",
  "bundle"}``; the top-level ``dataset_id`` MUST equal ``target.dataset_id`` (A4 422s on a
  mismatch).
* A4 selects which metrics to run from the registered ``bundle`` (``doc3-cio-advisory``), so
  this client never sends metric names of its own : an unregistered metric 422s rather than
  silently PASSING. This repo's ``no_advice_safety`` safety metric is part of the bundle.
* The evaluation response lists per-metric outcomes under ``results`` (not ``metrics``).

The base URL is read from ``QUALITY_GATE_URL`` with a localhost default.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from agent_eval_kit import EvalMetricResult, EvalReport

from ...config import Settings
from ...domain.errors import AdvisoryError
from ...envread import setting_or_default

_DEFAULT_URL = "http://localhost:8084"
_TIMEOUT = httpx.Timeout(30.0, connect=5.0)

# A4 selects the promotion metric suite from this registered bundle id; we never send bare
# metric names (an unregistered name now 422s). The bundle already includes this repo's
# ``no_advice_safety`` guardrail metric alongside groundedness / suitability / citations.
_BUNDLE = "doc3-cio-advisory"

# Settings carries no prompt-version field yet, so pin a stable constant. When the prompt
# corpus is versioned in settings/config, source ``prompt_version`` from there instead.
_PROMPT_VERSION = "v1"


def _text(value: object) -> str:
    """A JSON value read as a plain string; anything else reads as absent, never as a claim."""
    return value if isinstance(value, str) else ""


def _optional_text(value: object) -> str | None:
    """The nullable identifiers: a non-string (including JSON ``null``) stays ``None``."""
    return value if isinstance(value, str) and value else None


def _refs(value: object) -> tuple[str, ...]:
    """Artifact references, keeping only the non-blank strings the service actually sent."""
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item.strip())


class RemoteEvalGateError(AdvisoryError):
    """Raised when the remote A4 quality service returns a non-2xx response."""


class RemoteEvalGateAdapter:
    """HTTP client for the A4 ``model-quality-gate`` evaluation gate."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model = settings.models.reasoning
        self._base_url = setting_or_default("QUALITY_GATE_URL", _DEFAULT_URL).rstrip("/")

    def evaluate(self, dataset_path: str) -> EvalReport:
        """Run the A4 evaluation gate against ``dataset_path`` and map ``results`` back."""
        body = self._post("/v1/evaluations", self._payload(self._dataset_id(dataset_path)))
        results = tuple(
            EvalMetricResult(
                metric=str(item.get("metric", "")),
                score=float(item.get("score", 0.0)),
                threshold=float(item.get("threshold", 0.0)),
                passed=bool(item.get("passed", False)),
            )
            for item in (body.get("results") or ())
        )
        # The gate service reports how many examples it scored. That count is evidence:
        # EvalReport.passed fails closed without it, so a response claiming metric scores
        # over nothing cannot certify a promotion.
        raw_n = body.get("n_examples", 0)
        n_examples = raw_n if isinstance(raw_n, int) and not isinstance(raw_n, bool) else 0
        # The durable identifiers travel with the report. This mapping used to stop at three
        # fields, which threw away the run id, the dataset version and digest, the evaluator,
        # the schema version and the artifact references : exactly the evidence that makes a
        # promotion auditable, and exactly what the hardened A4 contract now attests with. A
        # report that scores well but cannot say which run produced it is not model-risk
        # evidence, so anything the service sent is carried, and anything it omitted stays at
        # the report's own empty default rather than being invented here.
        return EvalReport(
            dataset=dataset_path,
            results=results,
            n_examples=n_examples,
            run_id=_text(body.get("run_id")),
            dataset_version=_text(body.get("dataset_version")) or "v1",
            dataset_digest=_text(body.get("dataset_digest")),
            evaluator=_text(body.get("evaluator")),
            schema_version=_text(body.get("schema_version")) or "eval-run/v1",
            trace_id=_optional_text(body.get("trace_id")),
            correlation_id=_optional_text(body.get("correlation_id")),
            artifact_refs=_refs(body.get("artifact_refs")),
            attested=body.get("attested") is True,
        )

    def gate(self, target: str) -> bool:
        """Ask A4's ``/v1/gate`` for the single promotion pass/fail decision."""
        body = self._post("/v1/gate", self._payload(self._dataset_id(target)))
        return bool(body.get("passed", False))

    # ----------------------------------------------------------------- helpers
    def _payload(self, dataset_id: str) -> dict[str, object]:
        """Shared A4 body: structured target + matching top-level dataset id + bundle."""
        return {
            "target": {
                "model": self._model,
                "prompt_version": _PROMPT_VERSION,
                "dataset_id": dataset_id,
                "system": "",
            },
            "dataset_id": dataset_id,
            "bundle": _BUNDLE,
        }

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        # TODO(plan-hrz-s2s-auth): attach S2S header once model-quality-gate verifies it
        try:
            response = httpx.post(url, json=payload, timeout=_TIMEOUT)
        except httpx.HTTPError as exc:
            raise RemoteEvalGateError(f"A4 quality request to {url} failed: {exc}") from exc
        if response.status_code // 100 != 2:
            raise RemoteEvalGateError(
                f"A4 quality {url} returned {response.status_code}: {response.text[:500]}"
            )
        return response.json()

    @staticmethod
    def _dataset_id(dataset_path: str) -> str:
        """A4's dataset id is the golden file's basename without the ``.jsonl`` suffix."""
        name = Path(dataset_path).name
        return name[: -len(".jsonl")] if name.endswith(".jsonl") else name
