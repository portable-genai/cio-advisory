"""On-prem placeholder for ``EvaluationGatePort`` : the on-premise migration target.

One of the reversibility (P-02) migration placeholders: in the managed profile this port
binds to the Gen AI evaluation service adapter; switching ``profile`` to ``onprem``
rebinds it here. The adapter constructs cleanly with **no external dependencies** and
structurally satisfies the same Protocol as the managed adapter. Porting the promotion
gate to an on-premise evaluator is *only* a matter of filling this body in : the offline
eval gate in ``eval/run_eval.py`` runs regardless and the core domain logic is unchanged.
"""

from __future__ import annotations

from agent_eval_kit import EvalReport

from ...config import Settings

_MESSAGE = (
    "On-prem EvaluationGatePort adapter is a migration placeholder; implement against "
    "your on-premise platform. Core domain logic is unchanged."
)


class OnPremEvalAdapter:
    """Placeholder evaluation-gate adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def evaluate(self, dataset_path: str) -> EvalReport:
        raise NotImplementedError(_MESSAGE)

    def gate(self, target: str) -> bool:
        """Refuse the promotion decision too : a control, not a diagnostic.

        Unlike the on-prem tracer, which is absent rather than fatal, both halves of this port
        raise. Tracing is a diagnostic a client may reasonably run without; a promotion gate is
        a control, and a client running without one must find out at the call rather than
        discover later that everything was promoted unchecked.
        """
        raise NotImplementedError(_MESSAGE)
