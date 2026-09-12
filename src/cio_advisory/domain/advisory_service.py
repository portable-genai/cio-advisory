"""AdvisoryService : the B3 advisory-briefing pipeline (SPEC §5).

Owns the deliverable for one client and calls only ports. Because B3 handles customer
PII / financial data, the FULL R1 safety pipeline applies (redact -> guardrail INPUT ->
... -> guardrail OUTPUT -> audit), exactly like C1/B1. The pipeline, in order:

    tracer.span("advisory.brief"):
      redact(inputs)                          [P-04 : PII never reaches model/store]
      -> guardrail.screen(INPUT)              [blocked -> audit BLOCKED + raise]
      -> portfolio.get_profile + get_portfolio
      -> house_view.retrieve (A2 governed RAG)
      -> TalkingPointsService.synthesise      [LLM + SuitabilityPolicy per point]
      -> drop/flag UNSUITABLE points
      -> compute PortfolioAlignment
      -> attach not-advice disclaimer
      -> guardrail.screen(OUTPUT)             [blocked -> audit BLOCKED + raise]
      -> CioReviewPolicy (always requires review)
      -> audit.record(redacted prompt + response)

An advisory briefing is consequential, so a blocked input/output or an unavailable
portfolio is a hard error : the service never returns a partial briefing an RM might act
on. Pure domain code : no Google Cloud / ADK / FastAPI imports.
"""

from __future__ import annotations

import contextlib
from contextlib import nullcontext
from typing import Any

from . import _grounded as g
from . import gap_analysis as ga
from .entitlements import assert_may_access_client, visible_house_views
from .errors import GuardrailBlockedError, PortfolioUnavailableError, RetrievalEmptyError
from .identity import Principal
from .models import (
    NOT_ADVICE_DISCLAIMER,
    AdvisoryBriefing,
    AuditEvent,
    Citation,
    ClientProfile,
    DataCitation,
    Decision,
    Direction,
    GapStatus,
    GuardrailVerdict,
    HouseView,
    ModelPortfolio,
    Portfolio,
    PortfolioAlignment,
    PortfolioSummary,
    RedactionResult,
    SuitabilityVerdict,
    TalkingPoint,
    ThemeSignal,
)
from .review_policy import CioReviewPolicy
from .suitability_policy import SuitabilityPolicy
from .talking_points_service import TalkingPointsService

_DEFAULT_TOP_K = 8


class AdvisoryService:
    """Build a suitability-checked advisory briefing for one client (SPEC §5)."""

    def __init__(
        self,
        house_view: Any,
        portfolio: Any,
        llm: Any,
        guardrail: Any,
        redaction: Any,
        tracer: Any,
        audit: Any,
        suitability_policy: SuitabilityPolicy | None = None,
        review_policy: CioReviewPolicy | None = None,
        review_router: Any = None,
    ) -> None:
        self._house_view = house_view
        self._portfolio = portfolio
        self._llm = llm
        self._guardrail = guardrail
        self._redaction = redaction
        self._tracer = tracer
        self._audit = audit
        self._suitability = suitability_policy or SuitabilityPolicy()
        self._review = review_policy or CioReviewPolicy()
        # Rule R8: when the briefing requires human review it is routed to human-review-console (the
        # maker-checker
        # console), not left as a boolean. Optional so unit tests and the CLI can omit it; when
        # unset the escalation still audits ESCALATED, it just is not forwarded to a console.
        self._review_router = review_router
        self._talking_points = TalkingPointsService(
            llm=llm, tracer=tracer, suitability_policy=self._suitability
        )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def brief(self, client_id: str, principal: Principal) -> AdvisoryBriefing:
        """Build the advisory briefing for ``client_id`` on behalf of ``principal``.

        ``principal`` is the server-VERIFIED identity (never client-asserted); the audit
        actor is derived from it. Object-level authorization is enforced inside the
        pipeline: a principal not entitled to this client raises
        :class:`~cio_advisory.domain.errors.ClientAccessDeniedError` before any portfolio
        is loaded or anything is generated (covers the CLI and agent callers too).
        """
        actor = principal.actor
        span = self._tracer.span("advisory.brief", action="briefing", actor=actor)
        with span if span is not None else nullcontext():
            return self._brief_inner(client_id, principal)

    def talking_points(self, client_id: str, principal: Principal) -> list[TalkingPoint]:
        """Return just the suitability-checked talking points for ``client_id``.

        Enforces the same server-side object authorization as :meth:`brief`.
        """
        actor = principal.actor
        span = self._tracer.span("advisory.talking_points", action="talking_points", actor=actor)
        with span if span is not None else nullcontext():
            return self._brief_inner(client_id, principal).talking_points_list()

    # ------------------------------------------------------------------ #
    # Pipeline (R1 full safety)
    # ------------------------------------------------------------------ #
    def _brief_inner(self, client_id: str, principal: Principal) -> _Briefing:
        actor = principal.actor

        # 1) Redact the inputs (P-04) before they touch a model or the audit log.
        redaction: RedactionResult = self._redaction.redact(client_id)
        redacted_id = redaction.text

        # 2) Guardrail screen (INPUT). Blocked -> audit BLOCKED + raise.
        in_verdict: GuardrailVerdict = self._guardrail.screen(redacted_id, Direction.INPUT)
        if not in_verdict.allowed:
            self._write_audit(actor, redacted_id, "", Decision.BLOCKED)
            raise GuardrailBlockedError(
                in_verdict.reason or "advisory request blocked by guardrail"
            )

        # 3) Load the client's profile (cheap), then enforce OBJECT-LEVEL AUTHORIZATION
        #    (C2) against the verified principal BEFORE loading the portfolio or generating
        #    anything: a client id is not a capability, so a principal not entitled to this
        #    client (wrong tenant, no explicit grant) can read neither its holdings/PII nor
        #    a briefing. Fail-closed: an owner-less client is denied. Maps to HTTP 403.
        profile = self._load_profile(client_id)
        assert_may_access_client(principal, profile)
        portfolio = self._load_portfolio(client_id)

        #    The ideal allocation for this client's risk profile, and the arithmetic against
        #    it. Both are optional: a bank that has published no model portfolio gets a
        #    briefing with no allocation gaps rather than gaps against invented targets.
        model = self._load_model_portfolio(profile)
        summary = ga.summarise(
            portfolio, model, profile.risk_appetite, self._read_provenance(client_id)
        )

        # 4) Retrieve CIO house views from the governed KB (A2). Empty -> hard error.
        #    A view another tenant owns is dropped here, in the domain, so no adapter or store
        #    can place it in this principal's briefing; nothing left is the same hard error as
        #    nothing retrieved, and says nothing about what the other tenant publishes.
        query = self._build_query(profile, portfolio)
        house_views: list[HouseView] = visible_house_views(
            principal,
            g.retrieve_house_views(self._house_view, query, top_k=_DEFAULT_TOP_K),
        )
        if not house_views:
            self._write_audit(actor, redacted_id, "", Decision.ESCALATED)
            raise RetrievalEmptyError(f"no CIO house views retrieved for client {client_id!r}")

        # 5) Order the themes by what each means for THIS portfolio, then synthesise talking
        #    points (LLM) + attach suitability; drop UNSUITABLE. Ordering, never filtering:
        #    a briefing should open with the theme that closes this client's largest gap, and
        #    an RM should still see the whole house view rather than a version of the report
        #    edited down for them. What the model is handed first is what it writes about
        #    first, and that ordering is arithmetic rather than the model's judgement.
        ranked = ga.rank_by_relevance(house_views, portfolio, summary.allocation_gaps)
        points = self._talking_points.synthesise(profile, portfolio, ranked, summary=summary)

        # 6) Compute portfolio alignment: every asset class against the model portfolio's
        #    band, and every theme against the gap it would close or the exposure it bears
        #    on. Arithmetic and set intersection, so a reviewer can replay it.
        alignment = self._alignment(ranked, portfolio, summary)

        # 7) Output guardrail screen on the assembled briefing text (R1).
        out_text = self._briefing_text(points, alignment)
        out_verdict: GuardrailVerdict = self._guardrail.screen(out_text, Direction.OUTPUT)
        if not out_verdict.allowed:
            self._write_audit(actor, redacted_id, "", Decision.BLOCKED, direction=Direction.OUTPUT)
            raise GuardrailBlockedError(
                out_verdict.reason or "advisory output blocked by guardrail"
            )

        # 8) Maker-checker: a briefing always requires review; escalate on REVIEW/UNSUITABLE.
        requires_review = self._review.requires_review(tuple(points))
        escalates = self._review.escalates(tuple(points))

        briefing = _Briefing(
            client_id=client_id,
            talking_points=tuple(points),
            alignment=alignment,
            portfolio_summary=summary,
            house_views_considered=tuple(ranked),
            not_advice_disclaimer=NOT_ADVICE_DISCLAIMER,
            requires_human_review=requires_review,
        )

        # 9) Audit (already-redacted prompt + response).
        decision = Decision.ESCALATED if escalates else Decision.ALLOWED
        self._audit_briefing(actor, redacted_id, briefing, decision)

        # 10) Rule R8: route the consequential briefing to the human-review-console maker-checker
        # console. The
        #     adapter redacts before the wire. Best-effort: a console outage must not fail an
        #     already-assembled, already-audited briefing (the audit ESCALATED record is the
        #     durable escalation of record, and the outbox path retries).
        if self._review_router is not None and briefing.requires_human_review:
            with contextlib.suppress(Exception):
                self._review_router.route(briefing, maker=actor, tenant=principal.tenant)
        return briefing

    # ------------------------------------------------------------------ #
    # Loading
    # ------------------------------------------------------------------ #
    def _load_profile(self, client_id: str) -> ClientProfile:
        try:
            profile = self._portfolio.get_profile(client_id)
        except NotImplementedError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalise to a domain error
            raise PortfolioUnavailableError(
                f"could not load profile for client {client_id!r}: {exc}"
            ) from exc
        if profile is None:
            raise PortfolioUnavailableError(f"no profile for client {client_id!r}")
        return profile

    def _load_portfolio(self, client_id: str) -> Portfolio:
        try:
            portfolio = self._portfolio.get_portfolio(client_id)
        except NotImplementedError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalise to a domain error
            raise PortfolioUnavailableError(
                f"could not load portfolio for client {client_id!r}: {exc}"
            ) from exc
        if portfolio is None:
            raise PortfolioUnavailableError(f"no portfolio for client {client_id!r}")
        return portfolio

    def _read_provenance(self, client_id: str) -> DataCitation | None:
        """What the bound portfolio adapter says it did to answer this client.

        Optional in exactly the way :meth:`_load_model_portfolio` is, and for the same
        reason: an adapter that cannot report its read costs the briefing a provenance
        line, not the briefing. The on-prem placeholder's NotImplementedError propagates,
        because that profile exists to fail loudly rather than to look complete.
        """
        reader = getattr(self._portfolio, "read_provenance", None)
        if reader is None:
            return None
        try:
            return reader(client_id)  # type: ignore[no-any-return]
        except NotImplementedError:
            raise
        except Exception:  # noqa: BLE001 - an unreportable read is a missing line, not an error
            return None

    def _load_model_portfolio(self, profile: ClientProfile) -> ModelPortfolio | None:
        """The published allocation for this profile, or ``None`` when there is none.

        An adapter that has not implemented this yet, or a store with no row for the
        profile, is not a reason to refuse a briefing: the briefing simply carries no
        allocation gaps, and every consumer of them treats that as "not published" rather
        than "no gaps". The on-prem placeholder's NotImplementedError is the one case that
        still propagates, because that profile exists to fail loudly.
        """
        getter = getattr(self._portfolio, "get_model_portfolio", None)
        if getter is None:
            return None
        try:
            return getter(profile.risk_appetite, profile.jurisdiction)
        except NotImplementedError:
            raise
        except Exception:  # noqa: BLE001 - an unpublished allocation is not a failed briefing
            return None

    # ------------------------------------------------------------------ #
    # Alignment & query
    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_query(profile: ClientProfile, portfolio: Portfolio) -> str:
        objectives = ", ".join(profile.objectives) or "general wealth"
        classes = ", ".join(sorted({h.asset_class.value for h in portfolio.holdings})) or "mixed"
        return (
            f"current CIO house views relevant to a {profile.risk_appetite.value} client "
            f"with objectives {objectives} holding {classes}"
        )

    def _alignment(
        self,
        house_views: list[HouseView],
        portfolio: Portfolio,
        summary: PortfolioSummary,
    ) -> PortfolioAlignment:
        """Set every theme against the portfolio, and every asset class against its band.

        The three name lists keep their names and change their meaning, which is the whole
        point of this change. A theme is a GAP when the asset class it is about sits below
        the model portfolio's published band, not when the portfolio holds none of it; it is
        IN LINE when that class is inside the band; and it is an OVERWEIGHT when the class
        is above the band, or above the concentration limit, whichever bites first. The
        concentration limit still applies on top: it is a policy ceiling, and a portfolio can
        breach it while sitting inside a band that was published before the limit was set.
        """
        gaps_by_class = summary.allocation_gaps
        limit = self._suitability.concentration_limit
        links = tuple(ga.align_theme(hv, portfolio, gaps_by_class) for hv in house_views)

        in_line: list[str] = []
        gaps: list[str] = []
        overweights: list[str] = []
        for link in links:
            weight = portfolio.weight_in(link.asset_class)
            if link.addresses is not None:
                gaps.append(link.theme)
            elif link.status is GapStatus.IN_RANGE and link.signal is not ThemeSignal.THREAT:
                in_line.append(link.theme)
            if link.status is GapStatus.OVER or weight >= limit:
                overweights.append(link.theme)
        return PortfolioAlignment(
            themes_in_line=tuple(dict.fromkeys(in_line)),
            gaps=tuple(dict.fromkeys(gaps)),
            overweights=tuple(dict.fromkeys(overweights)),
            theme_links=links,
            allocation_gaps=gaps_by_class,
            uncovered_gaps=ga.uncovered(gaps_by_class, links),
        )

    @staticmethod
    def _briefing_text(points: list[TalkingPoint], alignment: PortfolioAlignment) -> str:
        """Flatten the briefing into a single string for the output guardrail screen."""
        chunks = [NOT_ADVICE_DISCLAIMER]
        for p in points:
            chunks.append(f"{p.headline}\n{p.body}")
        chunks.append(
            "alignment: in-line="
            + ", ".join(alignment.themes_in_line)
            + "; gaps="
            + ", ".join(alignment.gaps)
            + "; overweights="
            + ", ".join(alignment.overweights)
            + "; uncovered="
            + ", ".join(alignment.uncovered_gaps)
        )
        return "\n\n".join(chunks)

    # ------------------------------------------------------------------ #
    # Audit
    # ------------------------------------------------------------------ #
    def _audit_briefing(
        self,
        actor: str,
        redacted_prompt: str,
        briefing: _Briefing,
        decision: Decision,
    ) -> None:
        summary = "; ".join(p.headline for p in briefing.talking_points)
        citations = tuple(c for p in briefing.talking_points for c in p.citations)
        self._write_audit(
            actor,
            redacted_prompt,
            summary,
            decision,
            citations=citations,
            metadata={
                "n_talking_points": str(len(briefing.talking_points)),
                "requires_human_review": str(briefing.requires_human_review).lower(),
                "n_review_or_unsuitable": str(self._count_flagged(briefing.talking_points)),
            },
        )

    @staticmethod
    def _count_flagged(points: tuple[TalkingPoint, ...]) -> int:
        flagged = (SuitabilityVerdict.REVIEW, SuitabilityVerdict.UNSUITABLE)
        return sum(
            1 for p in points if p.suitability is not None and p.suitability.verdict in flagged
        )

    def _write_audit(
        self,
        actor: str,
        redacted_prompt: str,
        redacted_response: str,
        decision: Decision,
        citations: tuple[Citation, ...] = (),
        metadata: dict[str, str] | None = None,
        direction: Direction = Direction.INPUT,
    ) -> None:
        event = AuditEvent(
            action="briefing",
            actor=actor,
            decision=decision,
            redacted_prompt=redacted_prompt,
            redacted_response=redacted_response,
            citations=citations,
            metadata={**(metadata or {}), "direction": direction.value},
        )
        try:
            self._audit.record(event)
        except Exception:  # noqa: BLE001 - audit failure must not crash the request
            return


class _Briefing(AdvisoryBriefing):
    """AdvisoryBriefing with a tiny list accessor for the talking-points endpoint.

    AdvisoryBriefing is a frozen dataclass; this thin subclass only adds a convenience
    accessor so :meth:`AdvisoryService.talking_points` can reuse the full pipeline and
    return the list without re-deriving it.
    """

    __slots__ = ()

    def talking_points_list(self) -> list[TalkingPoint]:
        return list(self.talking_points)
