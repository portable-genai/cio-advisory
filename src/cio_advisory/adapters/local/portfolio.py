"""Local portfolio adapter (PortfolioPort): in-process client profile + holdings store.

The ``local`` profile's stand-in for the **BigQuery / AlloyDB** portfolio store: a small
in-process map of opaque client ids to their synthetic :class:`ClientProfile` and
:class:`Portfolio`, seeded from the built-in corpus and deterministic. This is internal
customer data, so there is no cross-service hop even in the managed profile; here it is
served entirely off-cloud. An unknown client id raises ``KeyError`` (the AdvisoryService
normalises that to a domain ``PortfolioUnavailableError``). SDK-free and unconditional.

Object-authorization owner (C2): the adapter is the server-side authority on which tenant
OWNS each client. ``get_profile`` stamps that owning tenant onto the returned profile so
the entitlement gate (``domain/entitlements.py``) can decide access from the VERIFIED
principal. The demo/fixture clients belong to tenant ``demo-bank``; a client absent from
``_CLIENT_OWNERS`` keeps whatever tenant its profile carries (default ``""``: owner-less),
and an owner-less client fails closed at the gate. The owner is stamped server-side, never
taken from a client-supplied field.
"""

from __future__ import annotations

from dataclasses import replace

from ...config import Settings
from ...domain.models import ClientProfile, Portfolio
from ._seed import SEED_PORTFOLIOS, SEED_PROFILES

# Server-side client -> owning-tenant map. The seeded synthetic clients are booked to the
# "demo-bank" tenant; this is the object-authZ linkage the entitlement gate reads.
_CLIENT_OWNERS: dict[str, str] = {client_id: "demo-bank" for client_id in SEED_PROFILES}


class LocalPortfolioAdapter:
    """Serve synthetic clients by opaque id; raise KeyError for an unknown client."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # The fictional sample clients seed only outside the live profile: live serves
        # ONLY audience-registered clients, so a briefing can never cite an invented
        # portfolio as if it were real.
        seed_fiction = settings.profile != "live"
        self._profiles: dict[str, ClientProfile] = dict(SEED_PROFILES) if seed_fiction else {}
        self._portfolios: dict[str, Portfolio] = dict(SEED_PORTFOLIOS) if seed_fiction else {}
        self._owners: dict[str, str] = dict(_CLIENT_OWNERS) if seed_fiction else {}

    def register(self, profile: ClientProfile, portfolio: Portfolio, tenant: str) -> None:
        """Add one audience-provided client (the API derives ``tenant`` server-side).

        In-process like the rest of this store: a registration lives for the server's
        lifetime, which is the demo scope. The owner map is what the fail-closed
        object-authorization gate reads, so the verified tenant stamp here is what
        makes the new client reachable to its own tenant only.
        """
        self._profiles[profile.id] = profile
        self._portfolios[profile.id] = portfolio
        self._owners[profile.id] = tenant

    def client_ids(self, tenant: str) -> list[str]:
        """The registered client ids owned by ``tenant`` (for the UI's picker)."""
        return sorted(cid for cid, owner in self._owners.items() if owner == tenant)

    def seed(
        self,
        profiles: dict[str, ClientProfile] | None = None,
        portfolios: dict[str, Portfolio] | None = None,
        owners: dict[str, str] | None = None,
    ) -> None:
        """Replace the in-process store (deterministic test/CLI seed).

        ``owners`` overrides the client -> owning-tenant map; when omitted the seeded
        clients stay booked to ``demo-bank`` so authorization tests are not vacuous.
        """
        if profiles is not None:
            self._profiles = dict(profiles)
        if portfolios is not None:
            self._portfolios = dict(portfolios)
        if owners is not None:
            self._owners = dict(owners)

    def get_profile(self, client_id: str) -> ClientProfile:
        profile = self._profiles[client_id]
        owner = self._owners.get(client_id, profile.tenant)
        # Stamp the server-side owner (never client-asserted). An owner-less client (no map
        # entry and no profile tenant) stays "" and fails closed at the entitlement gate.
        if owner and owner != profile.tenant:
            return replace(profile, tenant=owner)
        return profile

    def get_portfolio(self, client_id: str) -> Portfolio:
        return self._portfolios[client_id]
