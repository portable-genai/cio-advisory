"""IdentityPort : resolve a verified Principal from inbound transport context.

The hexagon boundary for authentication. The API layer hands the adapter a
:class:`RequestContext` (the request headers) and gets back a verified
:class:`Principal`, or an :class:`IdentityError`. The active profile picks the adapter:

* ``local`` resolves a seeded dev persona (no IdP/AD/LDAP) so demos and tests run offline,
* ``gcp`` verifies the Identity-Aware-Proxy-injected signed assertion (auth configured on
  the GCP service), and
* ``onprem`` is the placeholder for the client's own enterprise IdP (OIDC/SAML).

This keeps the per-user identity decision swappable by configuration, exactly like every
other port (P-02), and is the single seam where the client-asserted actor is replaced by a
server-verified one.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.identity import Principal, RequestContext


@runtime_checkable
class IdentityPort(Protocol):
    def resolve(self, ctx: RequestContext) -> Principal:
        """Resolve a VERIFIED principal from ``ctx``; raise ``IdentityError`` if missing/invalid."""
        ...


# --------------------------------------------------------------------------- #
# What an identity adapter DECLARES about the end-user authentication it provides.
#
# The exposure guard on the app object has one question to answer before it can decide
# anything: are this service's END-USER routes authenticated? Nothing else in the
# configuration answers it.
#
# * The PROFILE names an adapter family, not an authentication scheme. A deliberate ``local``
#   and an inherited one bind the same seeded personas, ``live`` binds those same personas
#   while reading as a non-local profile everywhere else, and a client's own IdP adapter can
#   be bound under ``onprem`` without the profile string changing at all.
# * The SERVICE-TO-SERVICE secret authenticates a calling SERVICE. It authenticates no end
#   user, so its presence is not evidence that an end-user route is protected. Deriving the
#   guard from it is how setting a credential came to SWITCH THE GUARD OFF for the very
#   routes it was protecting.
#
# The adapter bound to the identity port is the only thing that knows, so it says so here.
# --------------------------------------------------------------------------- #

#: The adapter verifies a server-side assertion; the client cannot assert who it is.
VERIFIED = "verified"
#: The adapter believes a header the client wrote. Useful offline, not authentication.
CLIENT_ASSERTED = "client-asserted"
#: The adapter resolves nobody: a placeholder for an identity provider not yet bound.
UNIMPLEMENTED = "unimplemented"

#: Every declaration this service understands. Anything else is read as CLIENT_ASSERTED.
END_USER_AUTH_KINDS: frozenset[str] = frozenset({VERIFIED, CLIENT_ASSERTED, UNIMPLEMENTED})

#: The class attribute an identity adapter sets to one of the values above. A CLASS attribute,
#: not an instance one, because the posture has to be readable WITHOUT constructing the
#: adapter: the seeded-persona adapter refuses to construct under an inherited profile, and a
#: posture that can only be computed by constructing something disappears exactly when it
#: matters most.
END_USER_AUTH_ATTR = "end_user_auth"


def declared_end_user_auth(adapter: object) -> str:
    """What ``adapter`` (a class or an instance) declares, defaulting to CLIENT_ASSERTED.

    An adapter that declares NOTHING is read as :data:`CLIENT_ASSERTED`, never
    :data:`VERIFIED`. Silence is not a claim to verify anything, and a guard that reads
    silence as "authenticated" switches itself off for every adapter somebody forgot to
    annotate, which is the fail-open shape this vocabulary exists to remove. An unrecognised
    value lands in the same place, so a typo cannot read as a verification claim.
    """
    declared = getattr(adapter, END_USER_AUTH_ATTR, None)
    if isinstance(declared, str) and declared in END_USER_AUTH_KINDS:
        return declared
    return CLIENT_ASSERTED
