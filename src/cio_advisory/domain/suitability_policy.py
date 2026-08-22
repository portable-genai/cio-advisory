"""SuitabilityPolicy : the regulatory suitability heart of B3 (SPEC §5).

Pure decision logic. Given a CIO house view (theme, stance, asset class), the client's
profile (risk appetite, objectives, knowledge/experience, constraints) and the client's
portfolio, it returns a :class:`SuitabilityAssessment` with a verdict
(SUITABLE | REVIEW | UNSUITABLE), the factors that drove it, a plain-language rationale,
and citations back to the house view and the portfolio.

The policy is deliberately conservative : it only ever *raises* the bar, never lowers it.
The worst (most cautious) verdict across all triggered factors wins. Key rules:

* Aggressive-tilted house views (an OVERWEIGHT stance on equity or alternatives) are
  REVIEW for a BALANCED client and UNSUITABLE for a CONSERVATIVE client.
* A constraint breach (e.g. an ESG-only client and a theme the house view ties to a
  non-ESG asset class, or a no-illiquid client and an alternatives theme) forces at
  least REVIEW, and UNSUITABLE when the constraint is a hard exclusion.
* A concentration breach : acting on the theme would push, or already keeps, a single
  asset class above the concentration limit : forces REVIEW.
* Knowledge/experience below the complexity of the asset class forces REVIEW.

No Google Cloud / framework imports : only the domain models and the standard library.
This module is the most heavily tested part of B3 because it is where the regulatory
suitability obligation lives.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    RISK_APPETITE_RANK,
    AssetClass,
    Citation,
    ClientProfile,
    HouseView,
    Portfolio,
    RiskAppetite,
    SourceType,
    Stance,
    SuitabilityAssessment,
    SuitabilityFactor,
    SuitabilityVerdict,
)

# Knowledge/experience tiers, ordered least to most sophisticated.
_KNOWLEDGE_RANK: dict[str, int] = {"retail": 0, "informed": 1, "professional": 2}

#: Verdict severity so the policy can pick the most cautious outcome.
_VERDICT_RANK: dict[SuitabilityVerdict, int] = {
    SuitabilityVerdict.SUITABLE: 0,
    SuitabilityVerdict.REVIEW: 1,
    SuitabilityVerdict.UNSUITABLE: 2,
}


def _worst(verdicts: list[SuitabilityVerdict]) -> SuitabilityVerdict:
    """Return the most cautious verdict, defaulting to SUITABLE for an empty list."""
    if not verdicts:
        return SuitabilityVerdict.SUITABLE
    return max(verdicts, key=lambda v: _VERDICT_RANK[v])


@dataclass(frozen=True, slots=True)
class SuitabilityPolicy:
    """Assess whether a house-view theme is suitable for a client (SPEC §5).

    Args:
        concentration_limit: maximum single-asset-class weight before a theme that
            adds to it is flagged REVIEW. Default 0.40 (40 percent).
    """

    concentration_limit: float = 0.40
    aggressive_asset_classes: frozenset[AssetClass] = frozenset(
        {AssetClass.EQUITY, AssetClass.ALTERNATIVES, AssetClass.REAL_ASSETS}
    )
    complex_asset_classes: frozenset[AssetClass] = frozenset(
        {AssetClass.ALTERNATIVES, AssetClass.REAL_ASSETS}
    )

    def assess(
        self,
        house_view: HouseView,
        client: ClientProfile,
        portfolio: Portfolio,
    ) -> SuitabilityAssessment:
        """Assess ``house_view`` for ``client`` given their ``portfolio``.

        Returns a :class:`SuitabilityAssessment`. The verdict is the most cautious of
        all triggered factors; the rationale names each factor that pushed the bar up.
        """
        factors: list[SuitabilityFactor] = []
        verdicts: list[SuitabilityVerdict] = []
        reasons: list[str] = []

        self._assess_risk_appetite(house_view, client, factors, verdicts, reasons)
        self._assess_constraints(house_view, client, factors, verdicts, reasons)
        self._assess_concentration(house_view, portfolio, factors, verdicts, reasons)
        self._assess_knowledge(house_view, client, factors, verdicts, reasons)

        verdict = _worst(verdicts)
        rationale = self._rationale(verdict, house_view, reasons)
        citations = self._citations(house_view)
        return SuitabilityAssessment(
            theme=house_view.theme,
            verdict=verdict,
            factors=tuple(factors),
            rationale=rationale,
            citations=citations,
        )

    # ------------------------------------------------------------------ #
    # Individual factor checks
    # ------------------------------------------------------------------ #
    def _assess_risk_appetite(
        self,
        house_view: HouseView,
        client: ClientProfile,
        factors: list[SuitabilityFactor],
        verdicts: list[SuitabilityVerdict],
        reasons: list[str],
    ) -> None:
        """Aggressive-tilted house views are gated against the client's appetite."""
        aggressive = (
            house_view.stance is Stance.OVERWEIGHT
            and house_view.asset_class in self.aggressive_asset_classes
        )
        triggered = False
        if aggressive:
            appetite = RISK_APPETITE_RANK[client.risk_appetite]
            if client.risk_appetite is RiskAppetite.CONSERVATIVE:
                triggered = True
                verdicts.append(SuitabilityVerdict.UNSUITABLE)
                reasons.append(
                    "an aggressive overweight theme is unsuitable for a conservative client"
                )
            elif appetite < RISK_APPETITE_RANK[RiskAppetite.AGGRESSIVE]:
                triggered = True
                verdicts.append(SuitabilityVerdict.REVIEW)
                reasons.append(
                    "an aggressive overweight theme needs review for a "
                    f"{client.risk_appetite.value} client"
                )
        factors.append(
            SuitabilityFactor(
                name="risk_appetite_alignment",
                weight=0.4,
                present=not triggered,
                detail=(
                    f"house-view stance {house_view.stance.value} on "
                    f"{house_view.asset_class.value} vs client appetite "
                    f"{client.risk_appetite.value}"
                ),
            )
        )

    def _assess_constraints(
        self,
        house_view: HouseView,
        client: ClientProfile,
        factors: list[SuitabilityFactor],
        verdicts: list[SuitabilityVerdict],
        reasons: list[str],
    ) -> None:
        """Client constraints (ESG-only, no-illiquid, no-leverage) gate themes."""
        constraints = {c.strip().lower() for c in client.constraints}
        triggered = False

        # A no-illiquid client and an alternatives/real-assets theme is a hard exclusion.
        if {"no-illiquid", "no-alternatives"} & constraints and house_view.asset_class in (
            AssetClass.ALTERNATIVES,
            AssetClass.REAL_ASSETS,
        ):
            triggered = True
            verdicts.append(SuitabilityVerdict.UNSUITABLE)
            reasons.append(
                "the client excludes illiquid/alternative assets, which this theme requires"
            )

        # An ESG-only client and a theme not flagged ESG needs review (RM judgement).
        if "esg-only" in constraints and "esg" not in house_view.theme.lower():
            triggered = True
            verdicts.append(SuitabilityVerdict.REVIEW)
            reasons.append("the client is ESG-only; this theme is not flagged ESG")

        factors.append(
            SuitabilityFactor(
                name="constraint_compliance",
                weight=0.3,
                present=not triggered,
                detail=f"client constraints {sorted(constraints) or 'none'}",
            )
        )

    def _assess_concentration(
        self,
        house_view: HouseView,
        portfolio: Portfolio,
        factors: list[SuitabilityFactor],
        verdicts: list[SuitabilityVerdict],
        reasons: list[str],
    ) -> None:
        """Acting on an overweight theme that breaches concentration forces REVIEW."""
        current = portfolio.weight_in(house_view.asset_class)
        breach = house_view.stance is Stance.OVERWEIGHT and current >= self.concentration_limit
        if breach:
            verdicts.append(SuitabilityVerdict.REVIEW)
            reasons.append(
                f"the portfolio already holds {current:.0%} in "
                f"{house_view.asset_class.value}, at or above the "
                f"{self.concentration_limit:.0%} concentration limit"
            )
        factors.append(
            SuitabilityFactor(
                name="concentration",
                weight=0.2,
                present=not breach,
                detail=(
                    f"current {house_view.asset_class.value} weight {current:.0%}, "
                    f"limit {self.concentration_limit:.0%}"
                ),
            )
        )

    def _assess_knowledge(
        self,
        house_view: HouseView,
        client: ClientProfile,
        factors: list[SuitabilityFactor],
        verdicts: list[SuitabilityVerdict],
        reasons: list[str],
    ) -> None:
        """A complex asset class needs an informed-or-above client."""
        complex_theme = house_view.asset_class in self.complex_asset_classes
        knowledge = _KNOWLEDGE_RANK.get(client.knowledge_experience.strip().lower(), 0)
        gap = complex_theme and knowledge < _KNOWLEDGE_RANK["informed"]
        if gap:
            verdicts.append(SuitabilityVerdict.REVIEW)
            reasons.append(
                f"this {house_view.asset_class.value} theme is complex but the client's "
                f"knowledge/experience is '{client.knowledge_experience}'"
            )
        factors.append(
            SuitabilityFactor(
                name="knowledge_experience",
                weight=0.1,
                present=not gap,
                detail=(
                    f"asset class {house_view.asset_class.value}, client knowledge "
                    f"'{client.knowledge_experience}'"
                ),
            )
        )

    # ------------------------------------------------------------------ #
    # Assembly helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _rationale(verdict: SuitabilityVerdict, house_view: HouseView, reasons: list[str]) -> str:
        if verdict is SuitabilityVerdict.SUITABLE:
            return (
                f"The theme '{house_view.theme}' aligns with the client's profile on every "
                "checked factor (risk appetite, constraints, concentration, knowledge)."
            )
        joined = "; ".join(dict.fromkeys(reasons)) or "one or more suitability factors"
        prefix = (
            "Not suitable to present as a recommendation"
            if verdict is SuitabilityVerdict.UNSUITABLE
            else "Present only with an explicit caveat; the RM must judge"
        )
        return f"{prefix}: {joined}."

    @staticmethod
    def _citations(house_view: HouseView) -> tuple[Citation, ...]:
        out: list[Citation] = []
        if house_view.citation is not None:
            out.append(house_view.citation)
        else:
            out.append(
                Citation(
                    source_id=house_view.id,
                    source_type=SourceType.HOUSE_VIEW,
                    title=house_view.theme,
                )
            )
        return tuple(out)
