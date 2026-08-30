"""FastAPI application for the B3 CIO Advisory Assistant.

Exposes the advisory artifacts (AdvisoryBriefing, TalkingPoint[], SuitabilityAssessment)
plus health, and publishes the A2A AgentCard at ``/.well-known/agent-card.json``. The
React/Next.js UI and the CLI consume this surface.

Design constraints:

* **Import-safe.** Building the :class:`~cio_advisory.config.Container` is deferred to
  request time via the ``deps`` factories, so importing this module (or ``app``) never
  touches Google Cloud. The on-prem/test profile imports it with no GCP SDK installed.
* **Guardrail blocks are not 500s.** A :class:`GuardrailBlockedError` from a service is
  translated to an HTTP 200 carrying an explicit blocked envelope flagged for human review.
* **Not advice.** Every briefing/talking-point response carries the mandatory non-advice
  disclaimer; B3 is decision-support, the RM is the human checker (P-06).
* **Server-verified identity.** Every artifact route resolves a verified Principal via the
  IdentityPort (``api/security.py``); a client-supplied ``actor`` is ignored. Embedding
  surface controls (CSP frame-ancestors + explicit CORS allowlist) are env-driven; see
  ``docs/embedding-and-identity.md``.
* **Region pinned** to ``asia-southeast1`` (Singapore) for residency (SPEC §2).

Run locally with ``python -m cio_advisory.api.app`` (uvicorn on :8091).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from hex_service_kit import cors_allowlist, resolve_bind_host
from hex_service_kit.web import add_loopback_exposure_guard

from ..config import end_user_auth_kind
from ..domain import models as m
from ..domain.errors import (
    ClientAccessDeniedError,
    GuardrailBlockedError,
    PortfolioUnavailableError,
    RetrievalEmptyError,
)
from ..domain.services import AdvisoryService
from ..envread import boolean_setting, read_env_setting, setting_or_default
from ..ports.identity import VERIFIED
from . import deps
from .schemas import (
    AdvisoryBriefingResponse,
    AgentCardModel,
    ClientListResponse,
    ClientRegistrationRequest,
    ClientRegistrationResponse,
    ClientRequest,
    HealthResponse,
    SuitabilityAssessmentModel,
    SuitabilityRequest,
    TalkingPointsResponse,
)
from .security import CurrentPrincipal

_DEV_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# Embedding-surface controls. In secure/embedded mode the assistant is served same-origin
# via the parent app's reverse-proxy (no CORS needed); for the cross-origin / standalone
# dev case, CIO_CORS_ORIGINS is an explicit per-tenant allowlist (never "*").
# CIO_FRAME_ANCESTORS is the CSP frame-ancestors allowlist of parent origins permitted to
# iframe the assistant UI.
_CORS_ORIGINS_ENV = "CIO_CORS_ORIGINS"
_FRAME_ANCESTORS_ENV = "CIO_FRAME_ANCESTORS"


#: Entries that are a wildcard by BEHAVIOUR rather than by spelling, so the asterisk test below
#: cannot see them. ``null`` is the one that matters: a sandboxed iframe presents a null origin,
#: so ``frame-ancestors null`` admits framing from a document whose own origin the browser has
#: already decided not to trust, and a null CORS origin trusts the same document WITH
#: credentials. ``'*'`` is the quoted form CSP also honours and ``*.*`` is the subdomain
#: wildcard; both carry an asterisk, and both are named here so the set reads as the complete
#: refusal rather than as a list of leftovers. Matching is exact, so ``https://nullify.example``
#: remains a perfectly good origin. The same four are refused in ``ui/lib/csp.mjs``.
_WILDCARD_TOKENS = frozenset({"*", "'*'", "null", "*.*"})


def _refuse_wildcard(origins: list[str] | tuple[str, ...], setting: str) -> None:
    """An origin policy naming everybody is not an allowlist, so refuse to boot with one.

    "never ``*``" was written in the comment above and enforced nowhere, which is the same
    as unenforced. ``*`` in the CORS allowlist trusts every origin WITH credentials, and in
    frame-ancestors it lets any page on the internet frame the console and drive it as the
    signed-in user. The rule catches a wildcard hiding inside an origin too
    (``https://*.example``): a legitimate origin has no ``*`` anywhere in it, so this
    refuses no configuration a deployment could correctly hold.

    The asterisk test alone was not the whole rule. ``null`` carries no asterisk, so it passed
    both allowlists and reached ``CORSMiddleware`` and the CSP directive verbatim: see
    :data:`_WILDCARD_TOKENS`. The two halves are a UNION, and the union is what
    ``ui/lib/csp.mjs`` already enforced for the document a browser actually frames, so until
    now the two surfaces disagreed about what an origin policy may hold.
    """
    offending = [origin for origin in origins if "*" in origin or origin in _WILDCARD_TOKENS]
    if offending:
        raise ValueError(
            f"{setting} origin policy must never contain a wildcard, got {offending}. "
            "Name each permitted origin in full."
        )


def _frame_ancestors(raw: str | None) -> str:
    """Three-state read of ``CIO_FRAME_ANCESTORS``; an emptied value REFUSES all framing.

    Unset keeps the shipped ``'self'``. A value naming no origin would emit the
    header ``Content-Security-Policy: frame-ancestors`` with an empty directive, which is a
    CSP parse error, so browsers dropped the directive and the clickjacking restriction went
    with it. An operator who empties the allowlist means "nobody may frame this", which is
    spelled ``'none'``, so that is what the emptied state now produces.

    A wildcard is the fourth state, and it refuses: see ``_refuse_wildcard``.
    """
    if raw is None:
        return "'self'"
    ancestors = raw.split()
    _refuse_wildcard(ancestors, _FRAME_ANCESTORS_ENV)
    return " ".join(ancestors) or "'none'"


_FRAME_ANCESTORS = _frame_ancestors(read_env_setting(_FRAME_ANCESTORS_ENV).raw)


def _cors_origins() -> list[str]:
    """Explicit allowlist, never "*", and a configured EMPTY allowlist refuses.

    Three-state, because "configured and empty" and "never configured" are different
    answers. Unset delegates to the shared hex-service-kit rule, whose localhost dev
    fallback is a RELAXATION and therefore keys off ``exposure_profile``: a run that named
    no profile gets no cross-origin trust. Set to a value naming no origin refuses every
    cross-origin request instead of falling back to the dev origins the operator was trying
    to remove.
    """
    raw = read_env_setting(_CORS_ORIGINS_ENV).raw
    if raw is not None:
        configured = [origin.strip() for origin in raw.split(",") if origin.strip()]
        _refuse_wildcard(configured, _CORS_ORIGINS_ENV)
        return configured
    resolved = cors_allowlist(
        deps.get_settings().exposure_profile,
        origins_env=_CORS_ORIGINS_ENV,
        dev_origins=tuple(_DEV_ORIGINS),
    )
    _refuse_wildcard(resolved, _CORS_ORIGINS_ENV)
    return resolved


app = FastAPI(
    title="B3 CIO Advisory Assistant",
    version="0.1.0",
    description=(
        "Grounded, suitability-checked, decision-support talking points for private-bank "
        "relationship managers, on the Gemini Enterprise Agent Platform. Decision-support, "
        "NOT financial advice : every output is suitability-tagged, carries a non-advice "
        "disclaimer, and is maker-checker gated (the RM is the human checker)."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Dev-Persona"],
)


def _frame_options(frame_ancestors: str) -> str:
    """The X-Frame-Options equivalent of ``frame_ancestors``, or "" where none exists.

    X-Frame-Options is the pre-CSP header, and browsers that understand frame-ancestors
    ignore it, so it is only a backstop for the ones that do not. It can express exactly two
    of the three states: ``'self'`` is SAMEORIGIN and ``'none'`` is DENY. It cannot express an
    allowlist (ALLOW-FROM was never widely implemented and is gone), so a named parent origin
    gets no backstop rather than a DENY that would break the embed it was configured for.

    The emptied state must not fall through here with no header at all, on top of a CSP
    directive the browser had already discarded as a parse error, which left the operator who
    asked for the STRICTEST posture with no clickjacking control whatsoever.
    """
    if frame_ancestors == "'self'":
        return "SAMEORIGIN"
    if frame_ancestors == "'none'":
        return "DENY"
    return ""


@app.middleware("http")
async def _security_headers(request: Request, call_next: Any) -> Any:
    """Emit embedding-surface headers: CSP frame-ancestors (who may iframe the assistant)."""
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = f"frame-ancestors {_FRAME_ANCESTORS}"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if deps.get_settings().profile in {"gcp", "platform"}:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    frame_options = _frame_options(_FRAME_ANCESTORS)
    if frame_options:
        response.headers["X-Frame-Options"] = frame_options
    return response


# A request arrives with nothing authenticating the END USER unless BOTH of these hold, and
# the guard bounds every case where either fails:
#
#   1. a profile was chosen. Absent that, nobody selected an identity scheme, the seeded
#      persona adapter refuses to construct, and every end-user route answers 401; but
#      /healthz and the agent card would still answer a stranger, and a deployment in that
#      state has no business being reachable at all. It is also the one case where a settings
#      file that bound a verifying adapter must NOT buy the relaxation: unset is not consent,
#      whatever the binding says;
#   2. the identity adapter the active binding names DECLARES that it verifies the end user.
#      Seeded personas arrive on the X-Dev-Persona header the caller wrote (client-asserted)
#      and the on-premises placeholder resolves nobody at all (unimplemented); neither
#      authenticates anyone, so neither may switch this off. Note that the seeded adapter is
#      bound under `live` as well as `local`, which a rule keyed on the profile string would
#      have missed.
#
# Note what is NOT in this expression: CIO_S2S_TOKEN. A service credential is evidence about a
# calling SERVICE and says nothing about the end-user routes, so setting one must not, and
# cannot, disable their bound. S2S routes are bounded by their own dependency, which is where
# a service credential belongs.
_END_USER_AUTHENTICATED = deps.get_settings().profile_explicit and end_user_auth_kind() == VERIFIED

# The RESTRICTION's profile string. `bind_profile` already reads an unconsented run as
# `local`; this widens the same rule to every posture that cannot authenticate an end user, so
# the start-up bound in `main()` and the request-time guard agree instead of one binding every
# interface while the other refuses every caller on it. Without this, `live` would bind
# 0.0.0.0 while the guard refused every peer that reached it.
_BIND_PROFILE = deps.get_settings().bind_profile if _END_USER_AUTHENTICATED else "local"

# Registered LAST, so it is the OUTERMOST middleware: an off-loopback caller is refused before
# CORS, before the header baseline and before any route or dependency runs. Bound to the APP
# OBJECT, not to `main()`: the Dockerfile CMD is
# `uvicorn cio_advisory.api.app:app --host 0.0.0.0`, so a guard reachable only from `main()`
# never runs in a shipped process and the seeded personas would be served to the LAN.
add_loopback_exposure_guard(
    app,
    unauthenticated=not _END_USER_AUTHENTICATED,
    insecure_demo_env="CIO_ALLOW_INSECURE_DEMO",
    # The EXPOSURE profile, so a run nobody configured names itself 'unconfigured' in the
    # refusal rather than borrowing the name of a profile an operator never chose.
    posture=deps.get_settings().exposure_profile,
)


def _blocked_response(client_id: str, reason: str) -> JSONResponse:
    """A 200 JSON body for a guardrail-blocked consequential request."""
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "client_id": client_id,
            "blocked": True,
            "requires_human_review": True,
            "detail": (
                "This request was blocked by the safety guardrail and was routed for human review."
            ),
            "reason": reason or "blocked",
        },
    )


def _unavailable_response(client_id: str, reason: str) -> JSONResponse:
    """A 200 JSON body when the client's portfolio/profile or house views are unavailable."""
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "client_id": client_id,
            "unavailable": True,
            "requires_human_review": True,
            "detail": "Could not build a grounded, suitability-checked briefing for this client.",
            "reason": reason,
        },
    )


def _denied_response(exc: ClientAccessDeniedError) -> JSONResponse:
    """403 for a failed server-side client entitlement check (object authZ; never a leak).

    The body carries only the denial detail: no client profile, portfolio/PII, or briefing,
    because the service raises before any of those are loaded or generated.
    """
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": str(exc)},
    )


# --------------------------------------------------------------------------- #
# Client registration (the audience-data path)
# --------------------------------------------------------------------------- #
# Client profiles and portfolios are inherently private data with no public source, so
# a real demo runs on what the audience brings: an opaque-reference profile plus its
# holdings, registered here. The owning tenant is stamped from the VERIFIED principal,
# which is exactly what the fail-closed client-authorization gate reads.
_CLIENT_TEMPLATE = """{
  "client_id": "client-demo-0001",
  "risk_appetite": "balanced",
  "objectives": ["capital-growth", "income"],
  "knowledge_experience": "informed",
  "constraints": [],
  "jurisdiction": "SG",
  "currency": "USD",
  "holdings": [
    {"name": "Global Equity Fund", "asset_class": "equity", "value": 350000, "weight": 0.35},
    {"name": "IG Bond Fund", "asset_class": "fixed_income", "value": 400000, "weight": 0.40},
    {"name": "Cash Reserve", "asset_class": "cash", "value": 250000, "weight": 0.25}
  ]
}
"""


@app.get("/v1/clients/template", tags=["clients"], response_class=Response)
def client_template() -> Response:
    """A downloadable JSON template for registering a client (opaque ids, never PII)."""
    return Response(
        content=_CLIENT_TEMPLATE,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="client-template.json"'},
    )


@app.get("/v1/clients", response_model=ClientListResponse, tags=["clients"])
def list_clients(principal: CurrentPrincipal) -> ClientListResponse:
    """The registered client ids owned by the caller's tenant (for the UI picker)."""
    portfolio = deps.get_container().portfolio
    lister = getattr(portfolio, "client_ids", None)
    ids: list[str] = list(lister(principal.tenant)) if lister is not None else []
    return ClientListResponse(clients=ids)


@app.post(
    "/v1/clients",
    response_model=ClientRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["clients"],
)
def register_client(
    request: ClientRegistrationRequest,
    principal: CurrentPrincipal,
) -> ClientRegistrationResponse | JSONResponse:
    """Register an audience-provided client profile + portfolio for briefings."""
    if not principal.tenant:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": "a tenant-less principal cannot own a client"},
        )
    try:
        appetite = m.RiskAppetite(request.risk_appetite.lower())
        holdings = tuple(h.to_domain() for h in request.holdings)
    except ValueError as exc:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": f"unknown enum value: {exc}"},
        )
    portfolio_port = deps.get_container().portfolio
    register = getattr(portfolio_port, "register", None)
    if register is None:
        return JSONResponse(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            content={"detail": "client registration is not available under this profile"},
        )
    total = sum(h.value for h in holdings)
    profile = m.ClientProfile(
        id=request.client_id,
        risk_appetite=appetite,
        objectives=tuple(request.objectives),
        knowledge_experience=request.knowledge_experience,
        constraints=tuple(request.constraints),
        jurisdiction=request.jurisdiction,
        tenant=principal.tenant,
    )
    portfolio = m.Portfolio(
        client_id=request.client_id,
        holdings=holdings,
        total_value=total,
        currency=request.currency,
    )
    register(profile, portfolio, principal.tenant)
    return ClientRegistrationResponse(
        client_id=request.client_id,
        tenant=principal.tenant,
        holdings=len(holdings),
        total_value=total,
    )


# --------------------------------------------------------------------------- #
# Artifact endpoints
# --------------------------------------------------------------------------- #
@app.post("/v1/briefing", response_model=AdvisoryBriefingResponse, tags=["artifacts"])
def briefing(
    request: ClientRequest,
    principal: CurrentPrincipal,
    service: Annotated[AdvisoryService, Depends(deps.get_advisory_service)],
) -> JSONResponse | AdvisoryBriefingResponse:
    """Build the suitability-checked advisory briefing for one client (not advice)."""
    try:
        result = service.brief(request.client_id, principal)
    except ClientAccessDeniedError as exc:
        return _denied_response(exc)
    except GuardrailBlockedError as exc:
        return _blocked_response(request.client_id, str(exc))
    except (RetrievalEmptyError, PortfolioUnavailableError) as exc:
        return _unavailable_response(request.client_id, str(exc))
    return AdvisoryBriefingResponse.from_domain(result)


@app.post("/v1/talking-points", response_model=TalkingPointsResponse, tags=["artifacts"])
def talking_points(
    request: ClientRequest,
    principal: CurrentPrincipal,
    service: Annotated[AdvisoryService, Depends(deps.get_advisory_service)],
) -> JSONResponse | TalkingPointsResponse:
    """Generate the suitability-checked talking points for one client (not advice)."""
    try:
        points = service.talking_points(request.client_id, principal)
    except ClientAccessDeniedError as exc:
        return _denied_response(exc)
    except GuardrailBlockedError as exc:
        return _blocked_response(request.client_id, str(exc))
    except (RetrievalEmptyError, PortfolioUnavailableError) as exc:
        return _unavailable_response(request.client_id, str(exc))
    return TalkingPointsResponse.from_domain(request.client_id, points)


@app.post("/v1/suitability", response_model=SuitabilityAssessmentModel, tags=["artifacts"])
def suitability(
    request: SuitabilityRequest,
    principal: CurrentPrincipal,
    service: Annotated[AdvisoryService, Depends(deps.get_advisory_service)],
) -> JSONResponse | SuitabilityAssessmentModel:
    """Assess the suitability of one CIO house-view theme for a client."""
    try:
        briefing_result = service.brief(request.client_id, principal)
    except ClientAccessDeniedError as exc:
        return _denied_response(exc)
    except GuardrailBlockedError as exc:
        return _blocked_response(request.client_id, str(exc))
    except (RetrievalEmptyError, PortfolioUnavailableError) as exc:
        return _unavailable_response(request.client_id, str(exc))

    wanted = request.theme.strip().lower()
    for point in briefing_result.talking_points:
        assessment = point.suitability
        if assessment is not None and assessment.theme.strip().lower() == wanted:
            return SuitabilityAssessmentModel.from_domain(assessment)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "client_id": request.client_id,
            "theme": request.theme,
            "verdict": "review",
            "detail": (
                "No suitable, in-scope talking point matched this theme for the client; the "
                "RM should review the full briefing."
            ),
        },
    )


# --------------------------------------------------------------------------- #
# Health & governance
# --------------------------------------------------------------------------- #
@app.get("/healthz", response_model=HealthResponse, tags=["ops"])
def healthz() -> HealthResponse:
    """Liveness/readiness probe. Reports the active profile and pinned region."""
    settings = deps.get_settings()
    return HealthResponse(
        status="ok",
        profile=settings.profile,
        runtime=settings.runtime,
        generator_model=settings.generator_model,
        region=settings.region,
    )


@app.get("/v1/personas", tags=["ops"])
def personas() -> list[dict[str, str]]:
    """List seeded dev personas for the local persona picker (empty outside local profile).

    Local mode runs with no IdP; the UI uses this to let a demo/test pick an identity
    (and thus exercise per-user authorization) via the ``X-Dev-Persona`` header. Secure
    profiles resolve identity from the IAP assertion, so this returns an empty list.
    """
    # A relaxation (it publishes unauthenticated identities), so a run that chose no profile
    # lists nothing rather than constructing the persona adapter, which refuses under exactly
    # this condition. Every chosen profile keeps its previous answer.
    if not deps.get_settings().profile_explicit:
        return []
    identity = deps.get_container().identity
    lister = getattr(identity, "personas", None)
    if lister is None:
        return []
    return [dict(p) for p in lister()]


@app.get("/.well-known/agent-card.json", response_model=AgentCardModel, tags=["governance"])
def agent_card() -> AgentCardModel:
    """Publish this assistant's A2A AgentCard for discovery (A3 Registry / interop)."""
    from ..agent.agent_card import build_agent_card

    settings = deps.get_settings()
    card = build_agent_card(settings)
    return AgentCardModel.from_domain(card)


def main() -> None:
    """Run the API locally with uvicorn (Cloud Run / Agent Runtime use this app object)."""
    import uvicorn

    uvicorn.run(
        "cio_advisory.api.app:app",
        # Fail-closed bind (shared hex-service-kit rule): a posture that
        # authenticates no end user binds loopback unless CIO_ALLOW_INSECURE_DEMO=1; a
        # verifying one keeps 0.0.0.0 (container-local; ingress is fronted by the platform).
        # This is a RESTRICTION, so it reads _BIND_PROFILE rather than the raw profile: a run
        # that named no profile, and any run whose identity binding cannot verify an end user,
        # must look local here and stay confined. That is the opposite direction from the CORS
        # relaxation above, and it is the same value the request-time guard was built with, so
        # the two cannot disagree.
        host=resolve_bind_host(
            _BIND_PROFILE,
            host_env="CIO_API_HOST",
            insecure_demo_env="CIO_ALLOW_INSECURE_DEMO",
        ),
        port=int(setting_or_default("PORT", "8091")),
        reload=boolean_setting("CIO_API_RELOAD"),
    )


if __name__ == "__main__":
    main()
