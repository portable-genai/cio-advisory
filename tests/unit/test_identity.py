"""Unit tests for the IdentityPort adapters (server-side, verified identity).

The local persona adapter is the offline (no IdP/AD/LDAP) identity source used for demos
and tests; the on-prem adapter is a fail-fast placeholder. These prove the identity seam
that replaces the old client-asserted ``actor``.
"""

from __future__ import annotations

import pytest

from cio_advisory.adapters.local.identity import LocalPersonaIdentityAdapter
from cio_advisory.adapters.onprem.identity import OnPremIdentityAdapter
from cio_advisory.config import Settings
from cio_advisory.domain.identity import IdentityError, Principal, RequestContext

_SETTINGS = Settings(profile="local")


def _adapter() -> LocalPersonaIdentityAdapter:
    return LocalPersonaIdentityAdapter(_SETTINGS)


def test_default_persona_when_no_header() -> None:
    principal = _adapter().resolve(RequestContext(headers={}))
    assert principal.subject == "demo.analyst@bank.example"
    assert principal.principals  # non-empty entitlements
    assert principal.tenant == "demo-bank"
    assert principal.actor == principal.subject  # audit actor is the verified subject


def test_persona_selected_by_header() -> None:
    principal = _adapter().resolve(RequestContext(headers={"x-dev-persona": "auditor"}))
    assert principal.subject == "demo.auditor@bank.example"
    assert principal.principals == ("group:audit",)


def test_cross_tenant_persona_is_seeded() -> None:
    # RequestContext lower-cases lookups, so a host that sends X-Dev-Persona still resolves.
    principal = _adapter().resolve(RequestContext(headers={"x-dev-persona": "other-tenant"}))
    assert principal.tenant == "other-bank"


def test_unknown_persona_raises() -> None:
    with pytest.raises(IdentityError):
        _adapter().resolve(RequestContext(headers={"x-dev-persona": "does-not-exist"}))


def test_personas_listing_for_picker() -> None:
    ids = {p["id"] for p in _adapter().personas()}
    assert {"analyst", "approver", "auditor", "other-tenant"} <= ids


def test_onprem_identity_fails_fast() -> None:
    adapter = OnPremIdentityAdapter(_SETTINGS)
    with pytest.raises(NotImplementedError):
        adapter.resolve(RequestContext(headers={}))


# --------------------------------------------------------------------------- #
# entitlement_principals narrows, never widens (defence against client-asserted ACL).
# --------------------------------------------------------------------------- #
def test_entitlement_principals_returns_all_when_unfiltered() -> None:
    p = Principal(subject="rm@bank.example", principals=("group:cio-analyst", "group:risk"))
    assert p.entitlement_principals() == ("group:cio-analyst", "group:risk")


def test_entitlement_principals_narrows_to_held_subset() -> None:
    p = Principal(subject="rm@bank.example", principals=("group:cio-analyst", "group:risk"))
    # A caller may narrow to least privilege but can never assert a principal it lacks.
    assert p.entitlement_principals(("group:risk", "group:cio-approver")) == ("group:risk",)
    assert p.entitlement_principals(("group:cio-approver",)) == ()
