"""Gap analysis: a gap is a distance from a published target, not the absence of a class.

Every number here is arithmetic a reviewer can redo by hand, which is the same standard the
suitability policy is held to, and the reason this is domain code rather than a prompt.

What the old alignment did, and what each test here would have caught:

* it called a theme a "gap" when the portfolio held NOTHING in its asset class, so a client
  one point short of target and a client with none looked identical, and a client at twice
  their target read as "in line";
* it produced no figure at all: not the points, not the money, so a briefing could not say
  how far short anything was;
* it linked a theme to holdings by asking the model, so a talking point could name a fund
  the client does not own and nothing noticed.

The shipped book is the fixture on purpose: these are the clients the demo shows, so a
change that makes the demo narrate something different fails here first.
"""

from __future__ import annotations

import pytest

from cio_advisory import demo_book
from cio_advisory.domain import gap_analysis as ga
from cio_advisory.domain.models import (
    AllocationTarget,
    AssetClass,
    GapStatus,
    Holding,
    HouseView,
    ModelPortfolio,
    Portfolio,
    RiskAppetite,
    Stance,
    ThemeSignal,
)

_PROFILES = demo_book.profiles()
_PORTFOLIOS = demo_book.portfolios()


def _model(appetite: RiskAppetite) -> ModelPortfolio:
    """The shipped model portfolio for a risk profile, built from the same rows the store serves."""
    rows = [r for r in demo_book.rows("model_portfolios") if r["risk_appetite"] == appetite.value]
    assert rows, f"the book ships no model portfolio for {appetite.value}"
    return ModelPortfolio(
        model_id=rows[0]["model_id"],
        risk_appetite=appetite,
        targets=tuple(
            AllocationTarget(
                asset_class=AssetClass(r["asset_class"]),
                target_weight=r["target_weight"],
                min_weight=r["min_weight"],
                max_weight=r["max_weight"],
            )
            for r in rows
        ),
        effective_from=rows[0]["effective_from"],
        source=rows[0]["source"],
    )


def _gap(gaps: tuple, asset_class: AssetClass):
    return next(g for g in gaps if g.asset_class is asset_class)


# --------------------------------------------------------------------------- #
# The band decides, not zero
# --------------------------------------------------------------------------- #
def test_a_class_inside_its_band_is_in_range_even_when_off_target() -> None:
    assert ga.status_for(0.40, 0.35, 0.55) is GapStatus.IN_RANGE
    assert ga.status_for(0.30, 0.35, 0.55) is GapStatus.UNDER
    assert ga.status_for(0.60, 0.35, 0.55) is GapStatus.OVER


def test_rounding_is_not_drift() -> None:
    """A hundredth of a basis point below the floor is float noise, not an under-allocation."""
    assert ga.status_for(0.35 - 1e-9, 0.35, 0.55) is GapStatus.IN_RANGE
    assert ga.status_for(0.34, 0.35, 0.55) is GapStatus.UNDER


def test_the_balanced_client_is_short_of_equity_by_a_number_a_reader_can_check() -> None:
    """client-000042: equity 30% against a 45% target, on a 1.2m book, so 180k short."""
    portfolio = _PORTFOLIOS["client-000042"]
    gaps = ga.allocation_gaps(portfolio, _model(RiskAppetite.BALANCED))
    equity = _gap(gaps, AssetClass.EQUITY)
    assert equity.status is GapStatus.UNDER
    assert equity.current_weight == pytest.approx(0.30)
    assert equity.target_weight == pytest.approx(0.45)
    assert equity.drift == pytest.approx(-0.15)
    assert equity.value_gap == pytest.approx(180_000, abs=1.0)
    assert equity.current_value == pytest.approx(360_000)

    cash = _gap(gaps, AssetClass.CASH)
    assert cash.status is GapStatus.OVER, "35% cash against a 0 to 10% band"
    assert cash.drift > 0


def test_holding_nothing_and_holding_a_little_are_different_answers() -> None:
    """The distinction the old alignment could not make, on one profile."""
    model = _model(RiskAppetite.BALANCED)
    none_held = Portfolio(
        client_id="c",
        holdings=(Holding("Cash Reserve", AssetClass.CASH, 1_000.0, 1.0),),
        total_value=1_000.0,
    )
    some_held = Portfolio(
        client_id="c",
        holdings=(
            Holding("Alt Fund", AssetClass.ALTERNATIVES, 80.0, 0.08),
            Holding("Cash Reserve", AssetClass.CASH, 920.0, 0.92),
        ),
        total_value=1_000.0,
    )
    absent = _gap(ga.allocation_gaps(none_held, model), AssetClass.ALTERNATIVES)
    present = _gap(ga.allocation_gaps(some_held, model), AssetClass.ALTERNATIVES)
    assert absent.status is GapStatus.UNDER and present.status is GapStatus.IN_RANGE
    assert absent.drift < present.drift


def test_a_class_the_model_does_not_name_is_still_reported() -> None:
    """Real money in an unnamed class is a fact, not something to leave out of the picture."""
    model = ModelPortfolio(
        model_id="m",
        risk_appetite=RiskAppetite.BALANCED,
        targets=(AllocationTarget(AssetClass.EQUITY, 1.0, 0.9, 1.0),),
    )
    portfolio = Portfolio(
        client_id="c",
        holdings=(
            Holding("Equity", AssetClass.EQUITY, 900.0, 0.9),
            Holding("REIT", AssetClass.REAL_ASSETS, 100.0, 0.1),
        ),
        total_value=1_000.0,
    )
    gaps = ga.allocation_gaps(portfolio, model)
    unnamed = _gap(gaps, AssetClass.REAL_ASSETS)
    assert unnamed.status is GapStatus.OVER
    assert unnamed.current_value == pytest.approx(100.0)


def test_no_model_portfolio_means_no_gaps_rather_than_gaps_against_nothing() -> None:
    assert ga.allocation_gaps(_PORTFOLIOS["client-000042"], None) == ()
    summary = ga.summarise(_PORTFOLIOS["client-000042"], None, RiskAppetite.BALANCED)
    assert summary.allocation_gaps == ()
    assert summary.model_portfolio is None
    assert summary.total_value == pytest.approx(1_200_000)


# --------------------------------------------------------------------------- #
# Themes against the portfolio
# --------------------------------------------------------------------------- #
def test_the_signal_is_derived_from_the_stance_and_cannot_disagree_with_it() -> None:
    def view(stance: Stance) -> HouseView:
        return HouseView(id="i", theme="t", stance=stance, asset_class=AssetClass.EQUITY)

    assert view(Stance.OVERWEIGHT).signal is ThemeSignal.OPPORTUNITY
    assert view(Stance.UNDERWEIGHT).signal is ThemeSignal.THREAT
    assert view(Stance.NEUTRAL).signal is ThemeSignal.WATCH


def test_an_opportunity_in_an_under_allocated_class_addresses_that_gap() -> None:
    portfolio = _PORTFOLIOS["client-000042"]
    gaps = ga.allocation_gaps(portfolio, _model(RiskAppetite.BALANCED))
    ai = HouseView(
        id="cio-ai",
        theme="AI infrastructure build-out",
        stance=Stance.OVERWEIGHT,
        asset_class=AssetClass.EQUITY,
    )
    link = ga.align_theme(ai, portfolio, gaps)
    assert link.signal is ThemeSignal.OPPORTUNITY
    assert link.addresses is not None
    assert link.addresses.asset_class is AssetClass.EQUITY
    assert link.addresses.value_gap == pytest.approx(180_000, abs=1.0)


def test_a_threat_reports_the_exposure_the_client_has_and_none_when_they_have_none() -> None:
    cash_threat = HouseView(
        id="cio-cash",
        theme="Reduce excess cash",
        stance=Stance.UNDERWEIGHT,
        asset_class=AssetClass.CASH,
    )
    heavy = _PORTFOLIOS["client-000042"]  # 35 percent cash
    gaps = ga.allocation_gaps(heavy, _model(RiskAppetite.BALANCED))
    assert ga.align_theme(cash_threat, heavy, gaps).exposure is not None

    no_cash = Portfolio(
        client_id="c",
        holdings=(Holding("Equity", AssetClass.EQUITY, 1_000.0, 1.0),),
        total_value=1_000.0,
    )
    gaps = ga.allocation_gaps(no_cash, _model(RiskAppetite.BALANCED))
    link = ga.align_theme(cash_threat, no_cash, gaps)
    assert link.exposure is None, (
        "a threat about a class the client does not hold is not an exposure"
    )


def test_a_theme_names_the_tagged_holding_rather_than_every_holding_in_its_class() -> None:
    """client-000113 holds two equity funds; only one carries the mega-cap tag."""
    portfolio = _PORTFOLIOS["client-000113"]
    tagged = HouseView(
        id="cio-megacap",
        theme="Concentration in mega-cap technology",
        stance=Stance.UNDERWEIGHT,
        asset_class=AssetClass.EQUITY,
        tags=("megacap-tech",),
    )
    names = [h.instrument for h in ga.related_holdings(tagged, portfolio)]
    assert names == ["US Mega-cap Technology ETF"]

    untagged = HouseView(
        id="cio-eq", theme="Equities", stance=Stance.OVERWEIGHT, asset_class=AssetClass.EQUITY
    )
    fallback = [h.instrument for h in ga.related_holdings(untagged, portfolio)]
    assert len(fallback) == 2, "with no tags the asset class is the honest fallback"


def test_a_gap_no_theme_addresses_is_named_rather_than_quietly_dropped() -> None:
    portfolio = _PORTFOLIOS["client-000042"]
    gaps = ga.allocation_gaps(portfolio, _model(RiskAppetite.BALANCED))
    only_equity = HouseView(
        id="cio-ai", theme="AI", stance=Stance.OVERWEIGHT, asset_class=AssetClass.EQUITY
    )
    links = (ga.align_theme(only_equity, portfolio, gaps),)
    uncovered = ga.uncovered(gaps, links)
    assert "equity" not in uncovered, "the equity gap IS addressed by this theme"
    assert "alternatives" in uncovered and "real_assets" in uncovered


# --------------------------------------------------------------------------- #
# Prompt rendering carries the same figures the console shows
# --------------------------------------------------------------------------- #
def test_the_rendered_gaps_quote_the_computed_figures() -> None:
    portfolio = _PORTFOLIOS["client-000042"]
    gaps = ga.allocation_gaps(portfolio, _model(RiskAppetite.BALANCED))
    text = ga.render_gaps(gaps)
    assert "equity: holds 30%, target 45%, under by 15%" in text
    assert "180,000 to add" in text
    assert ga.render_gaps(()) == "(no model portfolio, so no allocation gaps computed)"


def test_the_rendered_model_portfolio_names_its_edition() -> None:
    text = ga.render_model_portfolio(_model(RiskAppetite.CONSERVATIVE))
    assert "sg-conservative-2026q3" in text
    assert "2026-07-01" in text
    assert ga.render_model_portfolio(None).startswith("(no model portfolio")
