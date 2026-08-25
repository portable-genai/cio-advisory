"""Ports : the abstract interfaces (the hexagon boundary).

Every port is a ``typing.Protocol`` so adapters need only structural conformance and
contract tests can verify any adapter (GCP, remote-platform, or on-prem placeholder)
satisfies the same contract.

``ObservabilityTracerPort`` and ``EvaluationGatePort`` (with the ``TokenUsage`` value type)
are not declared in this package: they come from the shared commons packages and are
re-exported through :mod:`.observability` so consumers still have one import site for the
whole boundary set. Copies of them had already drifted across the fleet, which is the whole
reason they are imported rather than typed out.
"""

from .generation import GroundingPort, LLMPort
from .governance import AgentRegistryPort, ToolCatalogPort
from .identity import EndUserAuthUnavailableError, IdentityPort
from .observability import (
    AuditSinkPort,
    EvaluationGatePort,
    ObservabilityTracerPort,
    TokenUsage,
)
from .portfolio import PortfolioPort
from .retrieval import HouseViewRetrievalPort
from .review_router import ReviewRouterPort
from .runtime import AgentRuntimePort, MemoryPort, SessionPort
from .safety import GuardrailPort, PIIRedactionPort

__all__ = [
    "HouseViewRetrievalPort",
    "PortfolioPort",
    "LLMPort",
    "GroundingPort",
    "GuardrailPort",
    "PIIRedactionPort",
    "AgentRuntimePort",
    "SessionPort",
    "MemoryPort",
    "AuditSinkPort",
    "ObservabilityTracerPort",
    "TokenUsage",
    "EvaluationGatePort",
    "AgentRegistryPort",
    "ToolCatalogPort",
    "IdentityPort",
    "EndUserAuthUnavailableError",
    "ReviewRouterPort",
]
