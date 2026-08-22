"""TalkingPointsService : synthesise talking points and attach suitability (SPEC §5).

Given a client profile, their portfolio, and the CIO house views retrieved from the
governed KB (A2), this service asks the LLM to synthesise personalised talking points,
maps each back to its cited house views, runs the :class:`SuitabilityPolicy` for the
linked house-view theme, and attaches the resulting :class:`SuitabilityAssessment`.
UNSUITABLE points are dropped (never presented as a recommendation); REVIEW points are
kept but flagged so the RM applies extra scrutiny.

Every talking point is ``is_advice=False`` by construction : B3 is decision-support, not
advice. Pure domain code : no Google Cloud / ADK imports.
"""

from __future__ import annotations

from typing import Any

from . import _grounded as g
from .models import (
    ClientProfile,
    HouseView,
    Portfolio,
    SourceType,
    SuitabilityAssessment,
    SuitabilityVerdict,
    TalkingPoint,
)
from .prompts import _NOT_ADVICE_RULES, TALKING_POINTS_SYSTEM, TALKING_POINTS_USER
from .suitability_policy import SuitabilityPolicy

_TALKING_POINTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "headline": {"type": "string"},
                    "body": {"type": "string"},
                    "house_view_theme": {"type": "string"},
                    "linked_holdings": {"type": "array", "items": {"type": "string"}},
                    "used_source_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["headline", "body", "house_view_theme"],
            },
        }
    },
    "required": ["items"],
}


class TalkingPointsService:
    """Synthesise suitability-checked talking points. Signature fixed by SPEC §5."""

    def __init__(
        self,
        llm: Any,
        tracer: Any,
        suitability_policy: SuitabilityPolicy | None = None,
    ) -> None:
        self._llm = llm
        self._tracer = tracer
        self._suitability = suitability_policy or SuitabilityPolicy()

    def synthesise(
        self,
        profile: ClientProfile,
        portfolio: Portfolio,
        house_views: list[HouseView],
    ) -> list[TalkingPoint]:
        """Synthesise talking points, attach suitability, drop UNSUITABLE ones.

        The caller (AdvisoryService) has already redacted and screened the inputs and
        retrieved the house views; this method owns only synthesis + suitability.
        """
        house_view_block = g.render_house_views(house_views)
        system = TALKING_POINTS_SYSTEM.format(not_advice_rules=_NOT_ADVICE_RULES)
        user = TALKING_POINTS_USER.format(
            profile=g.render_profile(profile),
            portfolio=g.render_portfolio(portfolio),
            house_views=house_view_block,
        )
        request = g.build_llm_request(
            system_instruction=system,
            user_content=user,
            model=None,  # adapter default => reasoning model gemini-3.5-flash
            response_schema=_TALKING_POINTS_SCHEMA,
        )
        response = self._llm.generate(request)
        g.maybe_record_usage(self._tracer, response)

        parsed = g.parse_structured(response)
        return self._build_points(parsed, profile, portfolio, house_views)

    # ------------------------------------------------------------------ #
    # Assembly
    # ------------------------------------------------------------------ #
    def _build_points(
        self,
        parsed: dict[str, Any],
        profile: ClientProfile,
        portfolio: Portfolio,
        house_views: list[HouseView],
    ) -> list[TalkingPoint]:
        raw_items = parsed.get("items")
        if not isinstance(raw_items, list):
            return []
        by_theme = {hv.theme: hv for hv in house_views}
        by_id = {hv.id: hv for hv in house_views}
        out: list[TalkingPoint] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            headline = str(raw.get("headline") or "").strip()
            body = str(raw.get("body") or "").strip()
            if not headline or not body:
                continue
            theme = str(raw.get("house_view_theme") or "").strip()
            used_ids = g.as_str_list(raw.get("used_source_ids"))

            house_view = self._resolve_house_view(theme, used_ids, by_theme, by_id)
            assessment = self._assess(house_view, profile, portfolio)

            # Drop UNSUITABLE points : they must never be presented as a recommendation.
            if assessment is not None and assessment.verdict is SuitabilityVerdict.UNSUITABLE:
                continue

            citations = g.citations_for_source_ids(used_ids, house_views)
            out.append(
                TalkingPoint(
                    headline=headline,
                    body=body,
                    house_view_theme=house_view.theme if house_view else theme,
                    linked_holdings=tuple(g.as_str_list(raw.get("linked_holdings"))),
                    suitability=assessment,
                    citations=citations,
                    is_advice=False,
                )
            )
        return out

    @staticmethod
    def _resolve_house_view(
        theme: str,
        used_ids: list[str],
        by_theme: dict[str, HouseView],
        by_id: dict[str, HouseView],
    ) -> HouseView | None:
        """Find the house view a talking point relates to (by theme, else by id)."""
        if theme in by_theme:
            return by_theme[theme]
        for sid in used_ids:
            if sid in by_id:
                return by_id[sid]
        return None

    def _assess(
        self,
        house_view: HouseView | None,
        profile: ClientProfile,
        portfolio: Portfolio,
    ) -> SuitabilityAssessment | None:
        if house_view is None:
            return None
        return self._suitability.assess(house_view, profile, portfolio)

    # Exposed so the AdvisoryService and tests can reuse the same source-type tag.
    SOURCE_TYPE = SourceType.HOUSE_VIEW
