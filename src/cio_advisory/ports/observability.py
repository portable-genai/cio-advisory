"""Observability ports : the A5 (audit/trace) and A4 (eval gate) concerns.

Primary GCP adapters: **Cloud Logging locked WORM bucket** for immutable audit, **Cloud
Trace via OpenTelemetry** for reasoning-loop traces (message content capture OFF so PII
never reaches a span), and the **Gen AI evaluation service** for the promotion gate
(groundedness, suitability accuracy, citation accuracy, no-advice safety). Audit is also
delegated to the A5 ``agent-observability`` service via a remote-platform adapter; the
eval gate to the A4 ``model-quality-gate`` service plus an in-repo offline gate.

Two of the three ports are NOT written out here. ``ObservabilityTracerPort`` (with the
``TokenUsage`` value type it reports) comes from ``hex-service-kit`` and
``EvaluationGatePort`` from ``agent-eval-kit``: sixteen repositories had each hand-copied
these and they had already drifted apart, one dropping the evaluation port outright and two
dropping its ``gate`` method, which is the half that can refuse a promotion. A Protocol
copied into N repositories is N Protocols, and only one of them gets fixed when a defect is
found. The split across the two commons packages follows where the types already live: the
tracer beside the value type it reports, the gate beside the ``EvalReport`` it returns. Both
are typing-only imports, so the offline profile still needs no OpenTelemetry, no HTTP client
and no cloud SDK.

``AuditSinkPort`` stays declared here because it is typed in this repo's own vocabulary: it
takes this repo's :class:`~cio_advisory.domain.models.AuditEvent`, which the commons has no
opinion about.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_eval_kit import EvaluationGatePort
from hex_service_kit.observability import ObservabilityTracerPort, TokenUsage

from ..domain.models import AuditEvent


@runtime_checkable
class AuditSinkPort(Protocol):
    def record(self, event: AuditEvent) -> None:
        """Write an immutable, already-redacted audit record (WORM)."""
        ...


__all__ = [
    "AuditSinkPort",
    "EvaluationGatePort",
    "ObservabilityTracerPort",
    "TokenUsage",
]
