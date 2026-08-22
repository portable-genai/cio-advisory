"""Unit tests for the SuitabilityPolicy : the regulatory heart of B3 (SPEC §5).

The policy decides whether a CIO house-view theme is SUITABLE / REVIEW / UNSUITABLE for a
client given their risk appetite, constraints, knowledge and the portfolio's concentration.
These are the tests a CRO would care most about: an aggressive theme must never come back
SUITABLE for a conservative client, a hard exclusion must force UNSUITABLE, and a
concentration breach must force at least REVIEW.
"""

from __future__ import annotations

import pytest
from tests.conftest import load_policy

from cio_advisory.domain.models import (
    AssetClass,
    ClientProfile,
    Holding,
    HouseView,
    Portfolio,
    RiskAppetite,
    Stance,
    SuitabilityVerdict,
)


def _policy(limit: float = 0.40):
    return load_policy("SuitabilityPolicy")(concentration_limit=limit)


def _house_view(
    asset_class: AssetClass,
    stance: Stance = Stance.OVERWEIGHT,
    theme: str = "Test theme",
) -> HouseView:
    return HouseView(id="hv-1", theme=theme, stance=stance, asset_class=asset_class)


def _profile(
    appetite: RiskAppetite,
    constraints: tuple[str, ...] = (),
    knowledge: str = "informed",
) -> ClientProfile:
    return ClientProfile(
        id="client-test",
        risk_appetite=appetite,
        objectives=("capital-growth",),
        knowledge_experience=knowledge,
        constraints=constraints,
    )


def _portfolio(*weights: tuple[AssetClass, float]) -> Portfolio:
    holdings = tuple(
        Holding(f"H-{i}", ac, w * 1_000_000, w, "USD") for i, (ac, w) in enumerate(weights)
    )
    return Portfolio(
        client_id="client-test", holdings=holdings, total_value=1_000_000, currency="USD"
    )


# --------------------------------------------------------------------------- #
# Risk-appetite gating : the core suitability rule.
# --------------------------------------------------------------------------- #
def test_aggressive_theme_unsuitable_for_conservative_client():
    policy = _policy()
    hv = _house_view(AssetClass.EQUITY, Stance.OVERWEIGHT)
    assessment = policy.assess(hv, _profile(RiskAppetite.CONSERVATIVE), _portfolio())
    assert assessment.verdict is SuitabilityVerdict.UNSUITABLE


def test_aggressive_theme_review_for_balanced_client():
    policy = _policy()
    hv = _house_view(AssetClass.EQUITY, Stance.OVERWEIGHT)
    assessment = policy.assess(hv, _profile(RiskAppetite.BALANCED), _portfolio())
    assert assessment.verdict is SuitabilityVerdict.REVIEW


def test_aggressive_theme_suitable_for_aggressive_client():
    policy = _policy()
    hv = _house_view(AssetClass.EQUITY, Stance.OVERWEIGHT)
    # An aggressive client with an equity overweight, no concentration breach, is SUITABLE.
    assessment = policy.assess(
        hv, _profile(RiskAppetite.AGGRESSIVE, knowledge="professional"), _portfolio()
    )
    assert assessment.verdict is SuitabilityVerdict.SUITABLE


def test_neutral_fixed_income_theme_suitable_for_conservative_client():
    policy = _policy()
    hv = _house_view(AssetClass.FIXED_INCOME, Stance.OVERWEIGHT, theme="Quality credit")
    assessment = policy.assess(hv, _profile(RiskAppetite.CONSERVATIVE), _portfolio())
    # Fixed income is not an aggressive asset class, so a conservative client is fine.
    assert assessment.verdict is SuitabilityVerdict.SUITABLE


# --------------------------------------------------------------------------- #
# Constraints : hard exclusions and ESG-only.
# --------------------------------------------------------------------------- #
def test_no_illiquid_constraint_makes_alternatives_unsuitable():
    policy = _policy()
    hv = _house_view(AssetClass.ALTERNATIVES, Stance.OVERWEIGHT, theme="Private markets")
    assessment = policy.assess(
        hv,
        _profile(RiskAppetite.AGGRESSIVE, constraints=("no-illiquid",), knowledge="professional"),
        _portfolio(),
    )
    assert assessment.verdict is SuitabilityVerdict.UNSUITABLE


def test_esg_only_constraint_forces_review_for_non_esg_theme():
    policy = _policy()
    hv = _house_view(AssetClass.FIXED_INCOME, Stance.OVERWEIGHT, theme="Quality credit")
    assessment = policy.assess(
        hv, _profile(RiskAppetite.BALANCED, constraints=("esg-only",)), _portfolio()
    )
    assert assessment.verdict is SuitabilityVerdict.REVIEW


def test_esg_only_constraint_allows_esg_flagged_theme():
    policy = _policy()
    hv = _house_view(AssetClass.FIXED_INCOME, Stance.OVERWEIGHT, theme="ESG green bonds")
    assessment = policy.assess(
        hv, _profile(RiskAppetite.BALANCED, constraints=("esg-only",)), _portfolio()
    )
    assert assessment.verdict is SuitabilityVerdict.SUITABLE


# --------------------------------------------------------------------------- #
# Concentration : breaching the limit forces at least REVIEW.
# --------------------------------------------------------------------------- #
def test_concentration_breach_forces_review():
    policy = _policy(limit=0.40)
    hv = _house_view(AssetClass.FIXED_INCOME, Stance.OVERWEIGHT, theme="Quality credit")
    # The portfolio already holds 50% fixed income, above the 40% limit.
    portfolio = _portfolio((AssetClass.FIXED_INCOME, 0.50), (AssetClass.CASH, 0.50))
    assessment = policy.assess(hv, _profile(RiskAppetite.BALANCED), portfolio)
    assert assessment.verdict is SuitabilityVerdict.REVIEW
    assert any(f.name == "concentration" and not f.present for f in assessment.factors)


def test_below_concentration_limit_is_suitable():
    policy = _policy(limit=0.40)
    hv = _house_view(AssetClass.FIXED_INCOME, Stance.OVERWEIGHT, theme="Quality credit")
    portfolio = _portfolio((AssetClass.FIXED_INCOME, 0.30), (AssetClass.CASH, 0.70))
    assessment = policy.assess(hv, _profile(RiskAppetite.BALANCED), portfolio)
    assert assessment.verdict is SuitabilityVerdict.SUITABLE


# --------------------------------------------------------------------------- #
# Knowledge / experience : complex assets need an informed-or-above client.
# --------------------------------------------------------------------------- #
def test_complex_asset_with_retail_knowledge_forces_review():
    policy = _policy()
    hv = _house_view(AssetClass.REAL_ASSETS, Stance.NEUTRAL, theme="Infrastructure")
    # NEUTRAL stance so the risk-appetite gate does not also fire; isolate the knowledge gate.
    assessment = policy.assess(
        hv, _profile(RiskAppetite.AGGRESSIVE, knowledge="retail"), _portfolio()
    )
    assert assessment.verdict is SuitabilityVerdict.REVIEW
    assert any(f.name == "knowledge_experience" and not f.present for f in assessment.factors)


# --------------------------------------------------------------------------- #
# Worst-verdict-wins : the most cautious factor dominates.
# --------------------------------------------------------------------------- #
def test_worst_verdict_wins_unsuitable_over_review():
    policy = _policy()
    # Aggressive overweight alternatives (REVIEW for balanced) + no-illiquid (UNSUITABLE).
    hv = _house_view(AssetClass.ALTERNATIVES, Stance.OVERWEIGHT, theme="Private markets")
    assessment = policy.assess(
        hv, _profile(RiskAppetite.BALANCED, constraints=("no-illiquid",)), _portfolio()
    )
    assert assessment.verdict is SuitabilityVerdict.UNSUITABLE


# --------------------------------------------------------------------------- #
# Assessment shape : factors, rationale and citations are always populated.
# --------------------------------------------------------------------------- #
def test_assessment_carries_factors_rationale_and_citations():
    policy = _policy()
    hv = _house_view(AssetClass.EQUITY, Stance.OVERWEIGHT)
    assessment = policy.assess(hv, _profile(RiskAppetite.CONSERVATIVE), _portfolio())
    assert assessment.factors, "every assessment records the factors it checked"
    assert assessment.rationale, "every assessment has a plain-language rationale"
    assert assessment.citations, "every assessment cites the house view it assessed"
    assert assessment.theme == hv.theme


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
