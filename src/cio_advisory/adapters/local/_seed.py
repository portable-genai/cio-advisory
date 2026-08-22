"""Built-in synthetic corpus for the ``local`` profile.

A tiny, clearly-fictional set of CIO house views plus a couple of synthetic clients
and their portfolios, so the local house-view retrieval and portfolio adapters have
something to ground a briefing on out of the box, and the end-to-end CLI smoke run
returns a real, cited, suitability-tagged artifact with no external data. The text is
invented; the source ids / themes are plausible but fictional and must not be treated
as a real CIO publication. All client references are opaque non-PII ids.

This mirrors ``tests/fixtures/sample_clients`` so the local adapters and the unit-test
fixtures share one deterministic corpus, but it lives under ``src`` (not ``tests``) so
the shipped package can seed itself without importing the test tree.
"""

from __future__ import annotations

from ...domain.models import (
    AssetClass,
    Citation,
    ClientProfile,
    Holding,
    HouseView,
    Portfolio,
    RiskAppetite,
    SourceType,
    Stance,
)


def _hv_citation(source_id: str, title: str) -> Citation:
    return Citation(
        source_id=source_id,
        source_type=SourceType.HOUSE_VIEW,
        title=title,
        url=f"https://example.test/cio/{source_id}",
        page=1,
        snippet=f"CIO house view: {title}.",
        score=0.9,
    )


# --------------------------------------------------------------------------- #
# CIO house views (as retrieved from the A2 governed KB)
# --------------------------------------------------------------------------- #
SEED_HOUSE_VIEWS: tuple[HouseView, ...] = (
    HouseView(
        id="cio-2026q2-ai-infrastructure",
        theme="AI infrastructure build-out",
        stance=Stance.OVERWEIGHT,
        asset_class=AssetClass.EQUITY,
        rationale=(
            "Structural demand for compute and power favours selected equity exposure to "
            "the AI infrastructure supply chain over the cycle."
        ),
        citation=_hv_citation("cio-2026q2-ai-infrastructure", "AI infrastructure build-out"),
    ),
    HouseView(
        id="cio-2026q2-quality-credit",
        theme="Quality investment-grade credit",
        stance=Stance.OVERWEIGHT,
        asset_class=AssetClass.FIXED_INCOME,
        rationale=(
            "With yields elevated, high-quality investment-grade credit offers attractive "
            "carry for income-oriented portfolios."
        ),
        citation=_hv_citation("cio-2026q2-quality-credit", "Quality investment-grade credit"),
    ),
    HouseView(
        id="cio-2026q2-private-markets",
        theme="Selective private markets",
        stance=Stance.OVERWEIGHT,
        asset_class=AssetClass.ALTERNATIVES,
        rationale=(
            "Selective private-market exposure can diversify return drivers for suitable, "
            "longer-horizon clients who can bear illiquidity."
        ),
        citation=_hv_citation("cio-2026q2-private-markets", "Selective private markets"),
    ),
    HouseView(
        id="cio-2026q2-cash-drag",
        theme="Reduce excess cash",
        stance=Stance.UNDERWEIGHT,
        asset_class=AssetClass.CASH,
        rationale=(
            "Holding excess cash risks a drag on long-term real returns as rates normalise."
        ),
        citation=_hv_citation("cio-2026q2-cash-drag", "Reduce excess cash"),
    ),
)

# --------------------------------------------------------------------------- #
# Clients and their portfolios (opaque ids only)
# --------------------------------------------------------------------------- #
BALANCED_CLIENT_ID = "client-000042"
CONSERVATIVE_CLIENT_ID = "client-000077"

BALANCED_PROFILE = ClientProfile(
    id=BALANCED_CLIENT_ID,
    risk_appetite=RiskAppetite.BALANCED,
    objectives=("capital-growth", "income"),
    knowledge_experience="informed",
    constraints=(),
    jurisdiction="SG",
)

CONSERVATIVE_PROFILE = ClientProfile(
    id=CONSERVATIVE_CLIENT_ID,
    risk_appetite=RiskAppetite.CONSERVATIVE,
    objectives=("capital-preservation", "income"),
    knowledge_experience="retail",
    constraints=("no-illiquid", "esg-only"),
    jurisdiction="SG",
)

BALANCED_PORTFOLIO = Portfolio(
    client_id=BALANCED_CLIENT_ID,
    holdings=(
        Holding("Global Equity Fund", AssetClass.EQUITY, 350_000.0, 0.35, "USD"),
        Holding("IG Bond Fund", AssetClass.FIXED_INCOME, 400_000.0, 0.40, "USD"),
        Holding("Cash Reserve", AssetClass.CASH, 250_000.0, 0.25, "USD"),
    ),
    total_value=1_000_000.0,
    currency="USD",
)

CONSERVATIVE_PORTFOLIO = Portfolio(
    client_id=CONSERVATIVE_CLIENT_ID,
    holdings=(
        Holding("Short-Duration Bond Fund", AssetClass.FIXED_INCOME, 600_000.0, 0.60, "USD"),
        Holding("Cash Reserve", AssetClass.CASH, 400_000.0, 0.40, "USD"),
    ),
    total_value=1_000_000.0,
    currency="USD",
)

SEED_PROFILES: dict[str, ClientProfile] = {
    BALANCED_CLIENT_ID: BALANCED_PROFILE,
    CONSERVATIVE_CLIENT_ID: CONSERVATIVE_PROFILE,
}
SEED_PORTFOLIOS: dict[str, Portfolio] = {
    BALANCED_CLIENT_ID: BALANCED_PORTFOLIO,
    CONSERVATIVE_CLIENT_ID: CONSERVATIVE_PORTFOLIO,
}
