"""Pydantic v2 request/response models for the B3 CIO Advisory Assistant API.

These schemas mirror the frozen domain dataclasses in
:mod:`cio_advisory.domain.models` one-for-one, so the HTTP boundary is a thin, typed
projection of the domain : the React/Next.js UI and the CLI consume exactly these shapes.
Each response model exposes a ``from_domain`` classmethod that builds itself from the
corresponding domain object, using :func:`domain.serialization.to_jsonable` where a nested
structure is easiest to project verbatim (enums become their ``.value`` strings).

Nothing here imports Google Cloud, ADK, or any adapter: the API layer depends only on the
domain models, the ports, and the orchestration services : never on a concrete adapter.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..domain import models as m
from ..domain.serialization import to_jsonable

# --------------------------------------------------------------------------- #
# Shared projections
# --------------------------------------------------------------------------- #


class CitationModel(BaseModel):
    """Provenance attached to a generated claim (mirror of Citation)."""

    source_id: str
    source_type: str
    title: str
    url: str = ""
    page: int | None = None
    snippet: str = ""
    score: float | None = None

    @classmethod
    def from_domain(cls, citation: m.Citation) -> CitationModel:
        return cls(**to_jsonable(citation))


class SuitabilityFactorModel(BaseModel):
    name: str
    weight: float
    present: bool
    detail: str = ""

    @classmethod
    def from_domain(cls, factor: m.SuitabilityFactor) -> SuitabilityFactorModel:
        return cls(**to_jsonable(factor))


class SuitabilityAssessmentModel(BaseModel):
    """Per-theme suitability assessment (mirror of SuitabilityAssessment)."""

    theme: str
    verdict: str
    factors: list[SuitabilityFactorModel] = Field(default_factory=list)
    rationale: str = ""
    citations: list[CitationModel] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, a: m.SuitabilityAssessment) -> SuitabilityAssessmentModel:
        return cls(
            theme=a.theme,
            verdict=a.verdict.value,
            factors=[SuitabilityFactorModel.from_domain(f) for f in a.factors],
            rationale=a.rationale,
            citations=[CitationModel.from_domain(c) for c in a.citations],
        )


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #


class ClientRequest(BaseModel):
    """Inbound request scoped to one client (briefing / talking-points).

    There is deliberately NO ``actor`` field: the audit actor is the server-verified
    :class:`~cio_advisory.domain.identity.Principal` resolved by ``api/security.py``
    (any client-supplied actor is ignored).
    """

    client_id: str = Field(..., min_length=1, description="Opaque client reference (no PII).")


class SuitabilityRequest(BaseModel):
    """Inbound request to check the suitability of one house-view theme for a client.

    Like :class:`ClientRequest`, identity is never taken from the body: the verified
    Principal supplies the audit actor.
    """

    client_id: str = Field(..., min_length=1, description="Opaque client reference (no PII).")
    theme: str = Field(..., min_length=1, description="The CIO house-view theme to assess.")


# --------------------------------------------------------------------------- #
# Artifact responses
# --------------------------------------------------------------------------- #


class TalkingPointModel(BaseModel):
    """A personalised, suitability-checked talking point (mirror of TalkingPoint)."""

    headline: str
    body: str
    house_view_theme: str
    linked_holdings: list[str] = Field(default_factory=list)
    suitability: SuitabilityAssessmentModel | None = None
    citations: list[CitationModel] = Field(default_factory=list)
    is_advice: bool = False
    alignment: ThemeAlignmentModel | None = None

    @classmethod
    def from_domain(cls, tp: m.TalkingPoint) -> TalkingPointModel:
        return cls(
            headline=tp.headline,
            body=tp.body,
            house_view_theme=tp.house_view_theme,
            linked_holdings=list(tp.linked_holdings),
            suitability=(
                SuitabilityAssessmentModel.from_domain(tp.suitability)
                if tp.suitability is not None
                else None
            ),
            citations=[CitationModel.from_domain(c) for c in tp.citations],
            is_advice=tp.is_advice,
            alignment=(
                ThemeAlignmentModel.from_domain(tp.alignment) if tp.alignment is not None else None
            ),
        )


class DataCitationModel(BaseModel):
    """Where a figure's rows came from: the warehouse analogue of a document citation.

    It describes the READ, not the rows. The rows are on the wire once, in the summary's
    ``holdings``, and each gap's ``contributors`` names which of them by ``instrument_id``.
    """

    store: str = ""  # duckdb | bigquery | in-process
    dataset: str = ""
    table: str = ""
    predicate: str = ""
    row_count: int = 0
    as_of: str = ""

    @classmethod
    def from_domain(cls, cite: m.DataCitation) -> DataCitationModel:
        return cls(
            store=cite.store,
            dataset=cite.dataset,
            table=cite.table,
            predicate=cite.predicate,
            row_count=cite.row_count,
            as_of=cite.as_of,
        )


class AllocationGapModel(BaseModel):
    """One asset class against the model portfolio's band, with the distance in both units."""

    asset_class: str
    current_weight: float
    target_weight: float
    min_weight: float
    max_weight: float
    status: str  # under | in_range | over
    current_value: float = 0.0
    total_value: float = 0.0
    #: Signed distance from target: negative is short. Computed properties on the domain
    #: dataclass, projected explicitly so the console never recomputes a figure the engine
    #: owns and the two can never round differently.
    drift: float = 0.0
    value_gap: float = 0.0
    #: The instrument_ids whose values sum to current_value, and the read they came
    #: from. Together they are what lets a reader open a figure and see its rows.
    contributors: list[str] = Field(default_factory=list)
    evidence: DataCitationModel | None = None

    @classmethod
    def from_domain(cls, gap: m.AllocationGap) -> AllocationGapModel:
        return cls(
            asset_class=gap.asset_class.value,
            current_weight=gap.current_weight,
            target_weight=gap.target_weight,
            min_weight=gap.min_weight,
            max_weight=gap.max_weight,
            status=gap.status.value,
            current_value=gap.current_value,
            total_value=gap.total_value,
            drift=gap.drift,
            value_gap=gap.value_gap,
            contributors=list(gap.contributors),
            evidence=(
                DataCitationModel.from_domain(gap.evidence) if gap.evidence is not None else None
            ),
        )


class AllocationTargetModel(BaseModel):
    asset_class: str
    target_weight: float
    min_weight: float
    max_weight: float


class ModelPortfolioModel(BaseModel):
    """The published allocation a portfolio was measured against, named and dated."""

    model_id: str
    risk_appetite: str
    jurisdiction: str = "SG"
    effective_from: str = ""
    source: str = ""
    targets: list[AllocationTargetModel] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, model: m.ModelPortfolio) -> ModelPortfolioModel:
        return cls(
            model_id=model.model_id,
            risk_appetite=model.risk_appetite.value,
            jurisdiction=model.jurisdiction,
            effective_from=model.effective_from,
            source=model.source,
            targets=[
                AllocationTargetModel(
                    asset_class=t.asset_class.value,
                    target_weight=t.target_weight,
                    min_weight=t.min_weight,
                    max_weight=t.max_weight,
                )
                for t in model.targets
            ],
        )


class HoldingModelOut(BaseModel):
    """One position as the console renders it, with the tags that link it to a theme."""

    instrument: str
    instrument_id: str = ""
    asset_class: str
    value: float
    weight: float
    currency: str = "USD"
    tags: list[str] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, holding: m.Holding) -> HoldingModelOut:
        return cls(
            instrument=holding.instrument,
            instrument_id=holding.instrument_id,
            asset_class=holding.asset_class.value,
            value=holding.value,
            weight=holding.weight,
            currency=holding.currency,
            tags=list(holding.tags),
        )


class PortfolioSummaryModel(BaseModel):
    """What the client holds today, beside what their risk profile calls for."""

    client_id: str
    risk_appetite: str
    total_value: float = 0.0
    currency: str = "USD"
    holdings: list[HoldingModelOut] = Field(default_factory=list)
    allocation_gaps: list[AllocationGapModel] = Field(default_factory=list)
    model_portfolio: ModelPortfolioModel | None = None
    #: What store answered, and as of when. None when the bound adapter cannot say.
    provenance: DataCitationModel | None = None

    @classmethod
    def from_domain(cls, summary: m.PortfolioSummary) -> PortfolioSummaryModel:
        return cls(
            client_id=summary.client_id,
            risk_appetite=summary.risk_appetite.value,
            total_value=summary.total_value,
            currency=summary.currency,
            holdings=[HoldingModelOut.from_domain(h) for h in summary.holdings],
            allocation_gaps=[AllocationGapModel.from_domain(g) for g in summary.allocation_gaps],
            model_portfolio=(
                ModelPortfolioModel.from_domain(summary.model_portfolio)
                if summary.model_portfolio is not None
                else None
            ),
            provenance=(
                DataCitationModel.from_domain(summary.provenance)
                if summary.provenance is not None
                else None
            ),
        )


class ThemeAlignmentModel(BaseModel):
    """One CIO theme set against this portfolio: what it closes, what it bears on."""

    theme: str
    signal: str  # opportunity | threat | watch
    asset_class: str
    status: str  # under | in_range | over
    addresses: AllocationGapModel | None = None
    exposure: AllocationGapModel | None = None
    related_holdings: list[str] = Field(default_factory=list)
    citation: CitationModel | None = None

    @classmethod
    def from_domain(cls, link: m.ThemeAlignment) -> ThemeAlignmentModel:
        return cls(
            theme=link.theme,
            signal=link.signal.value,
            asset_class=link.asset_class.value,
            status=link.status.value,
            addresses=(
                AllocationGapModel.from_domain(link.addresses)
                if link.addresses is not None
                else None
            ),
            exposure=(
                AllocationGapModel.from_domain(link.exposure) if link.exposure is not None else None
            ),
            related_holdings=list(link.related_holdings),
            citation=(
                CitationModel.from_domain(link.citation) if link.citation is not None else None
            ),
        )


class PortfolioAlignmentModel(BaseModel):
    themes_in_line: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    overweights: list[str] = Field(default_factory=list)
    theme_links: list[ThemeAlignmentModel] = Field(default_factory=list)
    allocation_gaps: list[AllocationGapModel] = Field(default_factory=list)
    uncovered_gaps: list[str] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, a: m.PortfolioAlignment) -> PortfolioAlignmentModel:
        return cls(
            themes_in_line=list(a.themes_in_line),
            gaps=list(a.gaps),
            overweights=list(a.overweights),
            theme_links=[ThemeAlignmentModel.from_domain(link) for link in a.theme_links],
            allocation_gaps=[AllocationGapModel.from_domain(g) for g in a.allocation_gaps],
            uncovered_gaps=list(a.uncovered_gaps),
        )


class AdvisoryBriefingResponse(BaseModel):
    """The advisory briefing for one client (mirror of AdvisoryBriefing)."""

    client_id: str
    talking_points: list[TalkingPointModel] = Field(default_factory=list)
    alignment: PortfolioAlignmentModel = Field(default_factory=PortfolioAlignmentModel)
    portfolio_summary: PortfolioSummaryModel | None = None
    house_views_considered: list[ThemeAlignmentModel] = Field(default_factory=list)
    not_advice_disclaimer: str
    requires_human_review: bool = True
    generated_at: str = ""

    @classmethod
    def from_domain(cls, briefing: m.AdvisoryBriefing) -> AdvisoryBriefingResponse:
        return cls(
            client_id=briefing.client_id,
            talking_points=[TalkingPointModel.from_domain(t) for t in briefing.talking_points],
            alignment=PortfolioAlignmentModel.from_domain(briefing.alignment),
            portfolio_summary=(
                PortfolioSummaryModel.from_domain(briefing.portfolio_summary)
                if briefing.portfolio_summary is not None
                else None
            ),
            # The whole report as it stands against this portfolio, opportunities and
            # threats alike, so the console can show what the CIO said and not only the
            # subset that survived suitability. Projected from the alignment's links rather
            # than from the raw house views: the link carries the theme AND what it means
            # here, and two shapes for one thing is how they drift.
            house_views_considered=[
                ThemeAlignmentModel.from_domain(link) for link in briefing.alignment.theme_links
            ],
            not_advice_disclaimer=briefing.not_advice_disclaimer,
            requires_human_review=briefing.requires_human_review,
            generated_at=briefing.generated_at.isoformat(),
        )


class TalkingPointsResponse(BaseModel):
    """A client's suitability-checked talking points (with the not-advice disclaimer)."""

    client_id: str
    talking_points: list[TalkingPointModel] = Field(default_factory=list)
    not_advice_disclaimer: str = m.NOT_ADVICE_DISCLAIMER
    requires_human_review: bool = True

    @classmethod
    def from_domain(cls, client_id: str, points: list[m.TalkingPoint]) -> TalkingPointsResponse:
        return cls(
            client_id=client_id,
            talking_points=[TalkingPointModel.from_domain(t) for t in points],
        )


# --------------------------------------------------------------------------- #
# Health & governance
# --------------------------------------------------------------------------- #


class HoldingModel(BaseModel):
    """One holding in an audience-registered portfolio."""

    name: str = Field(..., min_length=1, max_length=120)
    asset_class: str = "multi_asset"
    value: float = 0.0
    weight: float = 0.0
    currency: str = "USD"

    def to_domain(self) -> m.Holding:
        return m.Holding(
            instrument=self.name,
            asset_class=m.AssetClass(self.asset_class),
            value=self.value,
            weight=self.weight,
            currency=self.currency,
        )


class ClientRegistrationRequest(BaseModel):
    """Register one audience-provided client (opaque reference only, never PII).

    The owning tenant is NEVER taken from this body: the API stamps the verified
    principal's tenant, which is what the fail-closed client-authorization gate reads.
    """

    client_id: str = Field(..., min_length=3, max_length=60, pattern=r"^[a-z0-9][a-z0-9-]*$")
    risk_appetite: str = "balanced"
    objectives: list[str] = Field(default_factory=list)
    knowledge_experience: str = "informed"
    constraints: list[str] = Field(default_factory=list)
    jurisdiction: str = "SG"
    currency: str = "USD"
    holdings: list[HoldingModel] = Field(..., min_length=1)


class ClientRegistrationResponse(BaseModel):
    """Outcome of registering an audience-provided client."""

    client_id: str
    tenant: str
    holdings: int
    total_value: float


class ClientSummaryModel(BaseModel):
    """One client in the picker: its id and a PII-free label the SERVER derives.

    The console used to carry its own hardcoded list of four clients with hand-written
    labels, two of which the server did not serve at all. The label is computed here from
    the profile so the picker cannot describe a client the book does not have, or describe
    one it does have wrongly.
    """

    client_id: str
    label: str = ""
    risk_appetite: str = ""


class ClientListResponse(BaseModel):
    """The clients visible to the caller's tenant, with their server-derived labels."""

    clients: list[str] = Field(default_factory=list)
    #: The same clients with their labels. ``clients`` stays a list of ids so an existing
    #: caller keeps working; new callers read this.
    items: list[ClientSummaryModel] = Field(default_factory=list)
    book_version: str = ""
    fictional: bool = False


class HealthResponse(BaseModel):
    """Liveness/readiness of the assistant and its active profile."""

    status: str = "ok"
    profile: str = "local"
    #: Provenance the UI banner states on every page: where the runtime sits and which
    #: model answers. Derived server-side so the console never guesses (org decision,
    #: 2026-08-30).
    runtime: str = "local"  # "gcp" | "local"
    generator_model: str = "deterministic-offline-stub"
    region: str = "asia-southeast1"


class AgentSkillModel(BaseModel):
    id: str
    name: str
    description: str


class AgentCardModel(BaseModel):
    """A2A AgentCard served at /.well-known/agent-card.json (mirror of AgentCard)."""

    name: str
    description: str
    url: str
    version: str
    provider: str = "cio-advisory"
    skills: list[AgentSkillModel] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, card: m.AgentCard) -> AgentCardModel:
        data: dict[str, Any] = to_jsonable(card)
        return cls(**data)
