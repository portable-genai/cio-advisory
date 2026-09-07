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
    """A single position in the client's portfolio.

    ``tags`` are the instrument's theme tags, carried from the instrument reference data.
    They are what lets a house-view theme be linked to the positions it is actually about
    DETERMINISTICALLY, instead of trusting a model to say which of a client's holdings a
    theme relates to. ``instrument_id`` is the reference key those tags came from.
    """

    instrument: str  # display name of the instrument
    asset_class: AssetClass
    value: float  # market value in ``currency``
    weight: float  # share of the portfolio in [0.0, 1.0]
    currency: str = "USD"
    instrument_id: str = ""  # reference key, e.g. "DEMO-EQ-GLB"
    tags: tuple[str, ...] = ()  # theme tags, e.g. ("megacap-tech", "ai-infrastructure")


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


class ThemeSignal(StrEnum):
    """What a house view is to a portfolio: something to add, or something to watch out for.

    DERIVED from the stance rather than stored beside it, so the two can never disagree.
    An overweight stance is an opportunity, an underweight stance is a threat, and a neutral
    stance is a watch item. A briefing reads the report as opportunities and threats, which
    is the vocabulary a relationship manager and a client already share.
    """

    OPPORTUNITY = "opportunity"
    THREAT = "threat"
    WATCH = "watch"


_SIGNAL_BY_STANCE: dict[Stance, ThemeSignal] = {
    Stance.OVERWEIGHT: ThemeSignal.OPPORTUNITY,
    Stance.UNDERWEIGHT: ThemeSignal.THREAT,
    Stance.NEUTRAL: ThemeSignal.WATCH,
}


@dataclass(frozen=True, slots=True)
class HouseView:
    """One CIO house-view theme retrieved from the governed knowledge base (A2)."""

    id: str  # stable article/theme id, e.g. "cio-2026q2-ai-infrastructure"
    theme: str  # human-readable theme, e.g. "AI infrastructure build-out"
    stance: Stance
    asset_class: AssetClass
    rationale: str = ""
    citation: Citation | None = None  # provenance back to the source CIO article
    tags: tuple[str, ...] = ()  # theme tags matched against a holding's own

    @property
    def signal(self) -> ThemeSignal:
        """Opportunity, threat or watch item, derived from the stance."""
        return _SIGNAL_BY_STANCE[self.stance]


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
# The model portfolio : what a portfolio is measured AGAINST
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class AllocationTarget:
    """The ideal weight for one asset class, and the band around it that counts as in range.

    The band is what makes a gap a fact rather than an opinion: a portfolio is short of its
    profile only when it sits OUTSIDE the band the bank published, not merely off the target.
    """

    asset_class: AssetClass
    target_weight: float  # the ideal share in [0.0, 1.0]
    min_weight: float  # below this the portfolio is under-allocated
    max_weight: float  # above this it is over-allocated


@dataclass(frozen=True, slots=True)
class ModelPortfolio:
    """The bank's ideal allocation for one risk profile, as published on a date.

    Data rather than configuration: a bank revises this per quarter and per booking centre,
    and a briefing has to be able to say which edition it measured against. The
    concentration limit stays configuration, because that is a policy number rather than a
    market view.
    """

    model_id: str
    risk_appetite: RiskAppetite
    targets: tuple[AllocationTarget, ...] = ()
    jurisdiction: str = "SG"
    effective_from: str = ""  # ISO date the allocation took effect
    source: str = ""  # the publication this allocation came from

    def target_for(self, asset_class: AssetClass) -> AllocationTarget | None:
        for target in self.targets:
            if target.asset_class is asset_class:
                return target
        return None


class GapStatus(StrEnum):
    """Where one asset class sits against its band."""

    UNDER = "under"
    IN_RANGE = "in_range"
    OVER = "over"


@dataclass(frozen=True, slots=True)
class AllocationGap:
    """One asset class, what the client holds in it, and what the model portfolio wants.

    ``drift`` is signed and in weight units: negative when the portfolio is short of the
    target, positive when it is heavy. ``value_gap`` is the same distance in money, which is
    the number a relationship manager actually discusses.
    """

    asset_class: AssetClass
    current_weight: float
    target_weight: float
    min_weight: float
    max_weight: float
    status: GapStatus
    current_value: float = 0.0
    total_value: float = 0.0

    @property
    def drift(self) -> float:
        """Signed distance from the target, in weight units (negative means short)."""
        return round(self.current_weight - self.target_weight, 6)

    @property
    def value_gap(self) -> float:
        """Signed distance from the target, in the portfolio's currency."""
        return round((self.target_weight - self.current_weight) * self.total_value, 2)


@dataclass(frozen=True, slots=True)
class ThemeAlignment:
    """One CIO theme set against this portfolio: what it is about, and what it touches.

    This is the row a briefing shows per theme. ``addresses`` names the under-allocated
    asset class an opportunity would move towards its target; ``exposure`` names the class a
    threat is already about. Both are computed, never asserted by a model.
    """

    theme: str
    signal: ThemeSignal
    asset_class: AssetClass
    status: GapStatus
    addresses: AllocationGap | None = None  # the gap this opportunity would close
    exposure: AllocationGap | None = None  # the holding weight this threat bears on
    related_holdings: tuple[str, ...] = ()
    citation: Citation | None = None


@dataclass(frozen=True, slots=True)
class PortfolioSummary:
    """What the client holds today, beside what their risk profile says they should.

    The before-picture a briefing is read against. It is deliberately available WITHOUT
    generating anything: the gaps are arithmetic over the holdings and the model portfolio,
    so the console can show them the moment a client is picked.
    """

    client_id: str
    risk_appetite: RiskAppetite
    total_value: float = 0.0
    currency: str = "USD"
    holdings: tuple[Holding, ...] = ()
    allocation_gaps: tuple[AllocationGap, ...] = ()
    model_portfolio: ModelPortfolio | None = None

    def gaps_under(self) -> tuple[AllocationGap, ...]:
        """The asset classes the portfolio is short of, worst first."""
        under = [g for g in self.allocation_gaps if g.status is GapStatus.UNDER]
        return tuple(sorted(under, key=lambda g: g.drift))

    def gaps_over(self) -> tuple[AllocationGap, ...]:
        """The asset classes the portfolio is heavy in, heaviest first."""
        over = [g for g in self.allocation_gaps if g.status is GapStatus.OVER]
        return tuple(sorted(over, key=lambda g: -g.drift))


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
    alignment: ThemeAlignment | None = None  # the computed gap or exposure this point is about


@dataclass(frozen=True, slots=True)
class PortfolioAlignment:
    """How the client's portfolio lines up with the current CIO house views.

    The three name lists are the summary a reader skims; ``theme_links`` carries the
    reasoning behind each one and ``allocation_gaps`` the arithmetic behind that. A theme
    counts as a gap when the asset class it is about sits BELOW the model portfolio's band,
    not merely when the portfolio holds none of it: "you hold no alternatives" and "you hold
    four points less than your profile calls for" are different statements, and only the
    second can be closed by a number.

    ``uncovered_gaps`` is the honest half. It names the asset classes this client is short
    of that today's report says nothing about, so a briefing can decline to invent a theme
    for them instead of quietly omitting the gap.
    """

    themes_in_line: tuple[str, ...] = ()  # themes whose asset class sits inside its band
    gaps: tuple[str, ...] = ()  # opportunity themes addressing an under-allocated class
    overweights: tuple[str, ...] = ()  # themes whose asset class is over its band
    theme_links: tuple[ThemeAlignment, ...] = ()  # per theme: what it addresses, what it touches
    allocation_gaps: tuple[AllocationGap, ...] = ()  # every asset class against its band
    uncovered_gaps: tuple[str, ...] = ()  # under-allocated classes no theme addresses


@dataclass(frozen=True, slots=True)
class AdvisoryBriefing:
    """The deliverable for one client : the bundle an RM takes into a conversation.

    Always ``requires_human_review=True``: an advisory briefing is consequential and
    the RM is the maker-checker. Carries the mandatory ``not_advice_disclaimer``.
    """

    client_id: str
    talking_points: tuple[TalkingPoint, ...] = ()
    alignment: PortfolioAlignment = field(default_factory=PortfolioAlignment)
    portfolio_summary: PortfolioSummary | None = None
    house_views_considered: tuple[HouseView, ...] = ()
    not_advice_disclaimer: str = NOT_ADVICE_DISCLAIMER
    requires_human_review: bool = True
    generated_at: datetime = field(default_factory=utcnow)
