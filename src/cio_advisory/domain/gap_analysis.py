"""Gap analysis: what this portfolio is short of, and which CIO themes speak to it.

Pure arithmetic and pure matching. Given a portfolio and the model portfolio for the
client's risk profile, it says how far each asset class sits from its target and whether
that is inside the published band. Given the day's house views on top, it says which theme
would move an under-allocated class towards its target, which theme bears on a class the
client is already heavy in, and which gaps today's report says nothing about.

Two properties this module exists to hold, both of which a model would get wrong at some
rate that nobody could measure:

**A gap is a distance, not an absence.** The old alignment called a theme a "gap" when the
portfolio held nothing at all in its asset class, and "in line" when it held anything. So a
client one point under target and a client with nothing looked identical, a client at twice
their target looked in line, and neither number a relationship manager would actually say
out loud, points and money, existed anywhere.

**A theme is linked to holdings by its tags, never by a model's opinion.** The instrument
reference data carries theme tags and so does the house view; the link is set intersection,
falling back to the asset class. A talking point may still name holdings, but only ones the
client owns: the pipeline filters the rest.

Standard library only, no imports beyond the domain models. Every number here is replayable
by a reviewer, which is the same standard the suitability policy is held to.
"""

from __future__ import annotations

from .models import (
    AllocationGap,
    AssetClass,
    GapStatus,
    Holding,
    HouseView,
    ModelPortfolio,
    Portfolio,
    PortfolioSummary,
    Stance,
    ThemeAlignment,
    ThemeSignal,
)

#: Weight differences below this are rounding, not drift. One hundredth of a percentage
#: point: far below anything a portfolio is rebalanced over, and above float noise.
_TOLERANCE = 1e-4


def status_for(weight: float, minimum: float, maximum: float) -> GapStatus:
    """Where ``weight`` sits against a band, with rounding treated as inside it."""
    if weight < minimum - _TOLERANCE:
        return GapStatus.UNDER
    if weight > maximum + _TOLERANCE:
        return GapStatus.OVER
    return GapStatus.IN_RANGE


def allocation_gaps(
    portfolio: Portfolio, model: ModelPortfolio | None
) -> tuple[AllocationGap, ...]:
    """Every asset class the model portfolio names, against what the client holds.

    Ordered by the model portfolio, so two clients on the same profile read the same way.
    An asset class the client holds that the model does not name is appended with a zero
    target: it is real money and pretending otherwise would understate the picture. With no
    model portfolio there is nothing to be short of, so the result is empty rather than a
    set of gaps measured against a target nobody published.
    """
    if model is None:
        return ()
    total = portfolio.total_value or sum(h.value for h in portfolio.holdings)
    gaps: list[AllocationGap] = []
    named: set[AssetClass] = set()
    for target in model.targets:
        named.add(target.asset_class)
        weight = portfolio.weight_in(target.asset_class)
        gaps.append(
            AllocationGap(
                asset_class=target.asset_class,
                current_weight=weight,
                target_weight=target.target_weight,
                min_weight=target.min_weight,
                max_weight=target.max_weight,
                status=status_for(weight, target.min_weight, target.max_weight),
                current_value=round(
                    sum(h.value for h in portfolio.holdings if h.asset_class is target.asset_class),
                    2,
                ),
                total_value=total,
            )
        )
    for asset_class in sorted({h.asset_class for h in portfolio.holdings} - named, key=str):
        weight = portfolio.weight_in(asset_class)
        gaps.append(
            AllocationGap(
                asset_class=asset_class,
                current_weight=weight,
                target_weight=0.0,
                min_weight=0.0,
                max_weight=0.0,
                status=status_for(weight, 0.0, 0.0),
                current_value=round(
                    sum(h.value for h in portfolio.holdings if h.asset_class is asset_class), 2
                ),
                total_value=total,
            )
        )
    return tuple(gaps)


def summarise(
    portfolio: Portfolio,
    model: ModelPortfolio | None,
    risk_appetite: object,
) -> PortfolioSummary:
    """The before-picture: holdings, and every asset class against its band."""
    from .models import RiskAppetite  # local import keeps the signature readable

    appetite = risk_appetite if isinstance(risk_appetite, RiskAppetite) else RiskAppetite.BALANCED
    return PortfolioSummary(
        client_id=portfolio.client_id,
        risk_appetite=appetite,
        total_value=portfolio.total_value or sum(h.value for h in portfolio.holdings),
        currency=portfolio.currency,
        holdings=portfolio.holdings,
        allocation_gaps=allocation_gaps(portfolio, model),
        model_portfolio=model,
    )


def related_holdings(house_view: HouseView, portfolio: Portfolio) -> tuple[Holding, ...]:
    """The positions a theme is actually about: tag overlap first, asset class otherwise.

    Tags are the precise answer and the asset class is the honest fallback. A theme tagged
    ``megacap-tech`` picks out the one fund carrying that tag rather than every equity the
    client owns, which is the difference between naming a concentration and gesturing at one.
    """
    tags = {t.strip().lower() for t in house_view.tags if t.strip()}
    if tags:
        tagged = tuple(h for h in portfolio.holdings if tags & {t.strip().lower() for t in h.tags})
        if tagged:
            return tagged
    return tuple(h for h in portfolio.holdings if h.asset_class is house_view.asset_class)


def align_theme(
    house_view: HouseView,
    portfolio: Portfolio,
    gaps: tuple[AllocationGap, ...],
) -> ThemeAlignment:
    """Set one theme against the portfolio: what it would close, or what it bears on."""
    gap = next((g for g in gaps if g.asset_class is house_view.asset_class), None)
    status = gap.status if gap is not None else GapStatus.IN_RANGE
    signal = house_view.signal
    addresses = gap if (signal is ThemeSignal.OPPORTUNITY and status is GapStatus.UNDER) else None
    # A threat is about what the client already holds, so it reports an exposure whenever
    # there is one, and reports none rather than a zero when the client holds nothing.
    held = gap is not None and gap.current_weight > 0
    exposure = gap if (signal is ThemeSignal.THREAT and held) else None
    if signal is ThemeSignal.OPPORTUNITY and status is GapStatus.OVER and gap is not None:
        exposure = gap  # an opportunity in a class already over its band is a caution too
    return ThemeAlignment(
        theme=house_view.theme,
        signal=signal,
        asset_class=house_view.asset_class,
        status=status,
        addresses=addresses,
        exposure=exposure,
        related_holdings=tuple(h.instrument for h in related_holdings(house_view, portfolio)),
        citation=house_view.citation,
    )


def relevance_rank(link: ThemeAlignment) -> tuple[int, float]:
    """Sort key: the gap it closes first, then the exposure it flags, then the rest.

    Within the first group the largest gap comes first, measured in weight, because that is
    the one an RM would open with. The key is total and deterministic, so two runs over the
    same portfolio order the briefing the same way.
    """
    if link.addresses is not None:
        return (0, link.addresses.drift)  # most negative drift = biggest shortfall first
    if link.exposure is not None:
        return (1, -link.exposure.current_weight)  # heaviest exposure first
    return (2, 0.0)


def rank_by_relevance(
    house_views: list[HouseView],
    portfolio: Portfolio,
    gaps: tuple[AllocationGap, ...],
) -> list[HouseView]:
    """Order the day's themes by what each means for this portfolio.

    Ordering, not filtering. Every theme the retrieval returned survives, because an RM
    reading the house view should see the house view; what changes is which one the briefing
    opens with. With no gaps computed (no model portfolio published) the original order is
    kept rather than invented.
    """
    if not gaps:
        return list(house_views)
    decorated = [
        (relevance_rank(align_theme(hv, portfolio, gaps)), i, hv)
        for i, hv in enumerate(house_views)
    ]
    return [hv for _, _, hv in sorted(decorated, key=lambda d: (d[0], d[1]))]


def addressable_gaps(
    gaps: tuple[AllocationGap, ...], house_views: list[HouseView]
) -> tuple[AssetClass, ...]:
    """The under-allocated classes today's report actually offers an opportunity for.

    The denominator of gap coverage. A gap the report is silent on cannot be held against a
    briefing, and a gap whose only theme is unsuitable for this client must not be either:
    the alternative would reward showing a client something the suitability engine refused.
    """
    offered = {hv.asset_class for hv in house_views if hv.signal is ThemeSignal.OPPORTUNITY}
    return tuple(
        gap.asset_class
        for gap in gaps
        if gap.status is GapStatus.UNDER and gap.asset_class in offered
    )


def uncovered(
    gaps: tuple[AllocationGap, ...], links: tuple[ThemeAlignment, ...]
) -> tuple[str, ...]:
    """The under-allocated asset classes no opportunity in today's report addresses.

    Named so a briefing can say the report is silent on a real gap, rather than leaving the
    reader to notice the omission or a model to fill it.
    """
    addressed = {link.addresses.asset_class for link in links if link.addresses is not None}
    return tuple(
        gap.asset_class.value
        for gap in gaps
        if gap.status is GapStatus.UNDER and gap.asset_class not in addressed
    )


def render_model_portfolio(model: ModelPortfolio | None) -> str:
    """The model portfolio as prompt context, one line per asset class."""
    if model is None or not model.targets:
        return "(no model portfolio published for this risk profile)"
    lines = [f"model_portfolio={model.model_id} (effective {model.effective_from or 'undated'})"]
    for target in model.targets:
        lines.append(
            f"  - {target.asset_class.value}: target {target.target_weight:.0%} "
            f"(range {target.min_weight:.0%} to {target.max_weight:.0%})"
        )
    return "\n".join(lines)


def render_gaps(gaps: tuple[AllocationGap, ...]) -> str:
    """The allocation gaps as prompt context, in the same words the console shows."""
    if not gaps:
        return "(no model portfolio, so no allocation gaps computed)"
    lines: list[str] = []
    for gap in gaps:
        if gap.status is GapStatus.IN_RANGE:
            detail = "in range"
        else:
            short = gap.status is GapStatus.UNDER
            direction = "under" if short else "over"
            money = "to add" if short else "above target"
            detail = f"{direction} by {abs(gap.drift):.0%} ({abs(gap.value_gap):,.0f} {money})"
        lines.append(
            f"  - {gap.asset_class.value}: holds {gap.current_weight:.0%}, "
            f"target {gap.target_weight:.0%}, {detail}"
        )
    return "\n".join(lines)


#: Re-exported so callers do not import Stance just to reason about a signal.
__all__ = [
    "Stance",
    "align_theme",
    "allocation_gaps",
    "related_holdings",
    "render_gaps",
    "render_model_portfolio",
    "status_for",
    "summarise",
    "uncovered",
]
