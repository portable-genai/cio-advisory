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
        )


class PortfolioAlignmentModel(BaseModel):
    themes_in_line: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    overweights: list[str] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, a: m.PortfolioAlignment) -> PortfolioAlignmentModel:
        return cls(**to_jsonable(a))


class AdvisoryBriefingResponse(BaseModel):
    """The advisory briefing for one client (mirror of AdvisoryBriefing)."""

    client_id: str
    talking_points: list[TalkingPointModel] = Field(default_factory=list)
    alignment: PortfolioAlignmentModel = Field(default_factory=PortfolioAlignmentModel)
    not_advice_disclaimer: str
    requires_human_review: bool = True
    generated_at: str = ""

    @classmethod
    def from_domain(cls, briefing: m.AdvisoryBriefing) -> AdvisoryBriefingResponse:
        return cls(
            client_id=briefing.client_id,
            talking_points=[TalkingPointModel.from_domain(t) for t in briefing.talking_points],
            alignment=PortfolioAlignmentModel.from_domain(briefing.alignment),
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


class ClientListResponse(BaseModel):
    """The registered client ids visible to the caller's tenant."""

    clients: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """Liveness/readiness of the assistant and its active profile."""

    status: str = "ok"
    profile: str = "local"
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
