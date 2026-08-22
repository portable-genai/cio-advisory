"""Vertical domain models for the CIO Advisory Assistant (system B3).

This module is the heart of the hexagon. It has **no dependency on Google Cloud,
ADK, FastAPI, or any framework** : only the Python standard library. Every adapter
(GCP, remote-platform, or on-prem placeholder) speaks in terms of these types, which
is what lets the managed-service stack be swapped for an on-premise one without
touching domain logic (General Principle P-02, "no vendor lock-in / ports & adapters").

It holds the **vertical** artifacts: the wealth-advisory types a fork is expected to
replace (client profile, portfolio, CIO house view, suitability, talking points and the
advisory briefing). The vertical-neutral machinery it builds on (citations, the LLM
envelope, guardrail and redaction verdicts, the audit event, the eval report, agent
cards) lives in :mod:`cio_advisory.domain.kernel`, which imports nothing from this
package. Every kernel name is re-exported below, so existing import sites that reach for
``cio_advisory.domain.models`` keep working unchanged, while the dependency arrow points
one way only: models -> kernel, never back. ``tests/unit/test_kernel_boundary.py`` proves
that direction by execution.

CRITICAL framing: B3 is a **decision-support** assistant for private-bank relationship
managers (RMs), not a source of financial advice. Every output is suitability-tagged,
carries a "not advice" disclaimer, and is maker-checker gated (the RM is the human
checker). The synthetic client/portfolio data shipped with this repo is fictional and
must not be used with live client data without sign-off.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .kernel import AgentCard as AgentCard
from .kernel import AgentSkill as AgentSkill
from .kernel import AuditEvent as AuditEvent
from .kernel import Citation as Citation
from .kernel import Decision as Decision
from .kernel import Direction as Direction
from .kernel import EvalMetricResult as EvalMetricResult
from .kernel import EvalReport as EvalReport
from .kernel import GuardrailCategory as GuardrailCategory
from .kernel import GuardrailFinding as GuardrailFinding
from .kernel import GuardrailVerdict as GuardrailVerdict
from .kernel import LlmMessage as LlmMessage
from .kernel import LlmRequest as LlmRequest
from .kernel import LlmResponse as LlmResponse
from .kernel import RedactionFinding as RedactionFinding
from .kernel import RedactionResult as RedactionResult
from .kernel import RetrievalQuery as RetrievalQuery
from .kernel import RetrievedPassage as RetrievedPassage
from .kernel import SourceType as SourceType
from .kernel import StrEnum as StrEnum
from .kernel import ThinkingLevel as ThinkingLevel
from .kernel import TokenUsage as TokenUsage
from .kernel import ToolSpec as ToolSpec
from .kernel import WebCitation as WebCitation
from .kernel import utcnow as utcnow

# Everything above is a deliberate public re-export of a kernel name (the redundant ``as``
# aliases are what tell ruff so). ``TokenUsage``, ``EvalMetricResult`` and ``EvalReport``
# reach this module from the shared commons via the kernel: they were hand-copied into
# sixteen repositories and had already drifted, so the commons declares each once and there
# is one definition to fix when a defect is found.


# --------------------------------------------------------------------------- #
# Client profile & suitability inputs
# --------------------------------------------------------------------------- #
class RiskAppetite(StrEnum):
    """The client's risk appetite, the spine of every suitability check."""

    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


# Ordinal rank so a policy can compare appetites (CONSERVATIVE < BALANCED < AGGRESSIVE).
RISK_APPETITE_RANK: dict[RiskAppetite, int] = {
    RiskAppetite.CONSERVATIVE: 0,
    RiskAppetite.BALANCED: 1,
    RiskAppetite.AGGRESSIVE: 2,
}


@dataclass(frozen=True, slots=True)
class ClientProfile:
    """The know-your-client picture a suitability assessment is run against.

    All fields are de-identified at the boundary (P-04) before they reach a model
    or an audit sink; ``id`` is an opaque, non-PII client reference.

    ``tenant`` is the server-side owner linkage the object-authorization gate reads
    (``domain/entitlements.py``): the portfolio adapter stamps which tenant owns the
    client, so a verified :class:`~cio_advisory.domain.identity.Principal` can only be
    granted access to clients in its own tenant (or via an explicit ``client:<id>``
    grant). It is never client-asserted; an owner-less client (``tenant == ""``) fails
    closed (deny).
    """

    id: str  # opaque client reference, e.g. "client-000042" (never a name / NRIC)
    risk_appetite: RiskAppetite
    objectives: tuple[str, ...] = ()  # e.g. ("capital-growth", "income")
    knowledge_experience: str = "informed"  # "retail" | "informed" | "professional"
    constraints: tuple[str, ...] = ()  # e.g. ("no-leverage", "esg-only", "no-illiquid")
    jurisdiction: str = "SG"  # booking jurisdiction (SG | HK | ...)
    tenant: str = ""  # owning tenant/book (server-side authZ owner; "" => owner-less => deny)


# --------------------------------------------------------------------------- #
# Portfolio & holdings
# --------------------------------------------------------------------------- #
class AssetClass(StrEnum):
    EQUITY = "equity"
    FIXED_INCOME = "fixed_income"
    CASH = "cash"
    ALTERNATIVES = "alternatives"
    REAL_ASSETS = "real_assets"
    MULTI_ASSET = "multi_asset"


@dataclass(frozen=True, slots=True)
class Holding:
    """A single position in the client's portfolio."""

    instrument: str  # display name / identifier of the instrument
    asset_class: AssetClass
    value: float  # market value in ``currency``
    weight: float  # share of the portfolio in [0.0, 1.0]
    currency: str = "USD"


@dataclass(frozen=True, slots=True)
class Portfolio:
    """The client's current holdings, used to personalise talking points."""

    client_id: str
    holdings: tuple[Holding, ...] = ()
    total_value: float = 0.0
    currency: str = "USD"

    def weight_in(self, asset_class: AssetClass) -> float:
        """Aggregate portfolio weight currently allocated to ``asset_class``."""
        return round(sum(h.weight for h in self.holdings if h.asset_class is asset_class), 6)

    def max_single_weight(self) -> float:
        """Largest single-position weight (a simple concentration signal)."""
        return max((h.weight for h in self.holdings), default=0.0)


# --------------------------------------------------------------------------- #
# CIO house views (retrieved from the A2 governed KB over CIO articles)
# --------------------------------------------------------------------------- #
class Stance(StrEnum):
    OVERWEIGHT = "overweight"
    NEUTRAL = "neutral"
    UNDERWEIGHT = "underweight"


@dataclass(frozen=True, slots=True)
class HouseView:
    """One CIO house-view theme retrieved from the governed knowledge base (A2)."""

    id: str  # stable article/theme id, e.g. "cio-2026q2-ai-infrastructure"
    theme: str  # human-readable theme, e.g. "AI infrastructure build-out"
    stance: Stance
    asset_class: AssetClass
    rationale: str = ""
    citation: Citation | None = None  # provenance back to the source CIO article


# --------------------------------------------------------------------------- #
# Runtime, session & memory
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Session:
    id: str
    user_id: str
    client_id: str | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True, slots=True)
class MemoryItem:
    id: str
    content: str
    scope: str = "user"  # "user" | "client" | "global"
    created_at: datetime = field(default_factory=utcnow)


# --------------------------------------------------------------------------- #
# Suitability : the regulatory heart of B3
# --------------------------------------------------------------------------- #
class SuitabilityVerdict(StrEnum):
    """Per-theme suitability verdict against the client's profile.

    SUITABLE: may be presented as a talking point.
    REVIEW: present only with an explicit caveat; the RM must judge.
    UNSUITABLE: never presented as a recommendation; dropped or flagged.
    """

    SUITABLE = "suitable"
    REVIEW = "review"
    UNSUITABLE = "unsuitable"


@dataclass(frozen=True, slots=True)
class SuitabilityFactor:
    """One input that fed the suitability verdict, with its contribution."""

    name: str  # e.g. "risk_appetite_alignment", "concentration", "constraint_breach"
    weight: float  # relative importance in [0.0, 1.0]
    present: bool  # whether this factor was satisfied / triggered
    detail: str = ""


@dataclass(frozen=True, slots=True)
class SuitabilityAssessment:
    """The suitability check for one theme / talking point (SPEC §5).

    Carries the verdict, the factors that drove it, a plain-language rationale, and
    citations back to the house view and the portfolio. UNSUITABLE assessments must
    never be surfaced to the client as a recommendation.
    """

    theme: str
    verdict: SuitabilityVerdict
    factors: tuple[SuitabilityFactor, ...] = ()
    rationale: str = ""
    citations: tuple[Citation, ...] = ()


# --------------------------------------------------------------------------- #
# Top-level assistant outputs (the artifacts B3 produces)
# --------------------------------------------------------------------------- #
#: The mandatory non-advice disclaimer attached to every AdvisoryBriefing (P-06).
NOT_ADVICE_DISCLAIMER: str = (
    "This material is decision-support for the relationship manager only. It is NOT "
    "financial advice, a recommendation, or an offer, and it has not been suitability-"
    "signed-off for the client. The relationship manager remains the human checker and "
    "is responsible for any advice given to the client."
)


@dataclass(frozen=True, slots=True)
class TalkingPoint:
    """A personalised, suitability-checked talking point (SPEC §5).

    Links a CIO house-view theme to the client's holdings. It is explicitly NOT advice
    (``is_advice=False``); it surfaces a discussion point for the RM to weigh, with its
    own suitability assessment and citations.
    """

    headline: str
    body: str
    house_view_theme: str
    linked_holdings: tuple[str, ...] = ()
    suitability: SuitabilityAssessment | None = None
    citations: tuple[Citation, ...] = ()
    is_advice: bool = False


@dataclass(frozen=True, slots=True)
class PortfolioAlignment:
    """How the client's portfolio lines up with the current CIO house views."""

    themes_in_line: tuple[str, ...] = ()  # themes the portfolio already reflects
    gaps: tuple[str, ...] = ()  # overweight house views the portfolio under-holds
    overweights: tuple[str, ...] = ()  # positions heavier than the house view supports


@dataclass(frozen=True, slots=True)
class AdvisoryBriefing:
    """The deliverable for one client : the bundle an RM takes into a conversation.

    Always ``requires_human_review=True``: an advisory briefing is consequential and
    the RM is the maker-checker. Carries the mandatory ``not_advice_disclaimer``.
    """

    client_id: str
    talking_points: tuple[TalkingPoint, ...] = ()
    alignment: PortfolioAlignment = field(default_factory=PortfolioAlignment)
    not_advice_disclaimer: str = NOT_ADVICE_DISCLAIMER
    requires_human_review: bool = True
    generated_at: datetime = field(default_factory=utcnow)
