"""Server-side client entitlements: who may read a client's portfolio, decided here.

The advisory pipeline is keyed by a ``client_id``, but a client id is NEVER a capability.
A request names a client (subject id); access is granted only after :func:`may_access_client`
passes against the VERIFIED :class:`~cio_advisory.domain.identity.Principal` (resolved by the
IdentityPort, never client-asserted) and the client's server-side owner. Combined with the
owning tenant the portfolio adapter stamps onto each :class:`ClientProfile`, this closes the
object-level authorization gap (C2): an authenticated relationship manager cannot read another
tenant's client portfolio / PII by guessing (or iterating) client ids.

Access model (deliberately simple, override per deployment):

* an explicit ``client:<id>`` entitlement on the principal always grants access
  (fine-grained grants provisioned by the IdP / entitlement system); otherwise
* membership of one of the ``advisory_roles`` grants access to clients WITHIN the
  principal's own tenant (``principal.tenant == profile.tenant``).

Fail-closed: a client with no known owner (``profile.tenant == ""``) is never reachable
by role, only by an explicit grant. Pure stdlib; raising :class:`ClientAccessDeniedError`
maps to HTTP 403 at the API layer, and the service raises it BEFORE loading the portfolio
or generating anything, so a denied caller gets neither PII nor a briefing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .errors import ClientAccessDeniedError
from .identity import Principal

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .models import ClientProfile

#: Roles whose members may work on clients (within their own tenant). Deployments with
#: finer-grained needs provision explicit ``client:<id>`` entitlements instead.
DEFAULT_ADVISORY_ROLES: frozenset[str] = frozenset(
    {"group:cio-analyst", "group:cio-approver", "group:audit"}
)


def may_access_client(
    principal: Principal,
    profile: ClientProfile,
    roles: frozenset[str] = DEFAULT_ADVISORY_ROLES,
) -> bool:
    """True when the verified principal is entitled to this client's profile/portfolio.

    An explicit ``client:<id>`` grant always wins (fine-grained entitlement). Otherwise the
    principal must hold a permitted advisory role AND share the client's owning tenant. An
    owner-less client (``profile.tenant == ""``) is fail-closed: never role-accessible.
    """
    held = principal.entitlement_principals()
    if f"client:{profile.id}" in held:
        return True
    if not profile.tenant:  # fail-closed: an owner-less client is never role-accessible
        return False
    if principal.tenant != profile.tenant:  # tenant isolation
        return False
    return any(p in roles for p in held)


def assert_may_access_client(
    principal: Principal,
    profile: ClientProfile,
    roles: frozenset[str] = DEFAULT_ADVISORY_ROLES,
) -> None:
    """Raise :class:`ClientAccessDeniedError` unless the principal may access the client.

    Called by the service after loading the (cheap) profile and BEFORE loading the
    portfolio or generating anything, so a denied caller never triggers PII access or a
    briefing. The message names the actor and client but leaks no client attributes.
    """
    if not may_access_client(principal, profile, roles):
        raise ClientAccessDeniedError(
            f"{principal.actor} is not entitled to client {profile.id!r} "
            "(no explicit client grant and no advisory role in the client's tenant)"
        )
