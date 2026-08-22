"""Local IdentityPort adapter: seeded dev personas, NO IdP / AD / LDAP.

The SDK-free ``local`` profile must run with zero authentication so demos and tests work
fully offline. This adapter resolves a :class:`Principal` from a small set of seeded
personas, selected by the ``X-Dev-Persona`` request header (the UI's persona picker),
defaulting to the first persona when none is supplied. It lets you exercise per-user
authorization (different entitlement principals and tenants, including a cross-tenant
persona) without standing up any identity provider. It is bound ONLY under the local
profile; secure mode uses the IAP adapter, which verifies a real assertion.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.identity import IdentityError, Principal, RequestContext
from ...ports.identity import CLIENT_ASSERTED

_PERSONA_HEADER = "x-dev-persona"

# Seeded dev personas. Ordered; the first entry is the default when no persona is selected.
# The persona id is the suffix of ``source`` after the colon. The ids, subjects and tenants
# are shared across the catalog repos so cross-repo demos stay uniform.
_PERSONAS: tuple[Principal, ...] = (
    Principal(
        subject="demo.analyst@bank.example",
        principals=("group:cio-analyst", "group:risk"),
        tenant="demo-bank",
        assurance="local-demo",
        source="local-persona:analyst",
    ),
    Principal(
        subject="demo.approver@bank.example",
        principals=("group:cio-analyst", "group:risk", "group:cio-approver"),
        tenant="demo-bank",
        assurance="local-demo",
        source="local-persona:approver",
    ),
    Principal(
        subject="demo.auditor@bank.example",
        principals=("group:audit",),
        tenant="demo-bank",
        assurance="local-demo",
        source="local-persona:auditor",
    ),
    Principal(
        subject="user@other-tenant.example",
        principals=("group:cio-analyst",),
        tenant="other-bank",
        assurance="local-demo",
        source="local-persona:other-tenant",
    ),
)


def _persona_id(principal: Principal) -> str:
    _, _, suffix = principal.source.partition(":")
    return suffix or principal.subject


class LocalPersonaProfileError(IdentityError):
    """Raised when seeded dev personas would be served under a profile nobody chose."""


class LocalPersonaIdentityAdapter:
    """Resolve a Principal from a seeded dev persona (local profile only, no auth)."""

    #: The persona arrives on ``X-Dev-Persona``, a header the CALLER writes, so a caller
    #: chooses who it is. That is a picker, not authentication, and the exposure guard reads
    #: this declaration to keep the routes it serves off the LAN. Bound under ``live`` as well
    #: as ``local``, which is why the guard asks the BINDING rather than the profile string.
    end_user_auth = CLIENT_ASSERTED

    def __init__(self, settings: Settings) -> None:
        # These personas are an UNAUTHENTICATED grant of the analyst and approver
        # entitlements, so the adapter refuses to construct unless the no-auth posture was
        # actually chosen. Reading a missing CIO_PROFILE as "local" would bind this adapter
        # and hand every caller the first seeded persona. It is an IdentityError subclass so
        # the API turns the refusal into a 401 rather than a 500.
        if not settings.profile_explicit:
            raise LocalPersonaProfileError(
                "CIO_PROFILE is not set, so the local profile was inherited rather than "
                "chosen; seeded dev personas authenticate nobody and are refused. Set "
                "CIO_PROFILE=local deliberately for a dev or demo run, or CIO_PROFILE=gcp "
                "for a real deployment."
            )
        self._settings = settings
        self._by_id: dict[str, Principal] = {_persona_id(p): p for p in _PERSONAS}
        self._default: Principal = _PERSONAS[0]

    def resolve(self, ctx: RequestContext) -> Principal:
        chosen = ctx.header(_PERSONA_HEADER).strip()
        if not chosen:
            return self._default
        persona = self._by_id.get(chosen)
        if persona is None:
            raise IdentityError(
                f"unknown dev persona {chosen!r}; valid personas: {sorted(self._by_id)}"
            )
        return persona

    def personas(self) -> tuple[dict[str, str], ...]:
        """List the seeded personas for the local persona picker (id, subject, tenant)."""
        return tuple(
            {
                "id": _persona_id(p),
                "subject": p.subject,
                "tenant": p.tenant,
                "principals": ", ".join(p.principals),
            }
            for p in _PERSONAS
        )
