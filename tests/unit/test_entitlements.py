"""Object-level authorization (C2): server-side client entitlements + tenant isolation.

Covers the object-authZ fix: access to a client's profile/portfolio is decided server-side
(``domain/entitlements.py``) from the VERIFIED principal against the client's owning tenant,
never from the request body. An authenticated RM in another tenant is denied a demo-bank
client it merely names, and an owner-less client is fail-closed (deny).
"""

from __future__ import annotations

import pytest

from cio_advisory.domain import entitlements
from cio_advisory.domain.errors import ClientAccessDeniedError
from cio_advisory.domain.identity import Principal
from cio_advisory.domain.models import ClientProfile, RiskAppetite

# --------------------------------------------------------------------------- #
# Verified principals (server-resolved; mirror the seeded local personas).
# --------------------------------------------------------------------------- #
ANALYST = Principal(
    subject="demo.analyst@bank.example",
    principals=("group:cio-analyst", "group:risk"),
    tenant="demo-bank",
)
OTHER_TENANT = Principal(
    subject="user@other-tenant.example",
    principals=("group:cio-analyst",),
    tenant="other-bank",
)
NO_ROLE = Principal(subject="viewer@bank.example", principals=("group:hr",), tenant="demo-bank")
# An explicit per-client grant admits access regardless of tenant (fine-grained entitlement).
EXPLICIT_GRANT = Principal(
    subject="temp@bank.example", principals=("client:client-000042",), tenant="other-bank"
)

# --------------------------------------------------------------------------- #
# Client profiles carrying their server-side owner (stamped by the portfolio adapter).
# --------------------------------------------------------------------------- #
DEMO_BANK_CLIENT = ClientProfile(
    id="client-000042", risk_appetite=RiskAppetite.BALANCED, tenant="demo-bank"
)
OWNERLESS_CLIENT = ClientProfile(id="client-999999", risk_appetite=RiskAppetite.BALANCED, tenant="")


# --------------------------------------------------------------------------- #
# Entitlement rules
# --------------------------------------------------------------------------- #
def test_same_tenant_advisory_role_grants_access() -> None:
    assert entitlements.may_access_client(ANALYST, DEMO_BANK_CLIENT) is True


def test_explicit_client_grant_always_grants_even_cross_tenant() -> None:
    assert entitlements.may_access_client(EXPLICIT_GRANT, DEMO_BANK_CLIENT) is True


def test_explicit_grant_is_scoped_to_its_client() -> None:
    other = ClientProfile(
        id="client-000077", risk_appetite=RiskAppetite.BALANCED, tenant="demo-bank"
    )
    # The grant is for client-000042; against a different client only role+tenant can admit.
    assert entitlements.may_access_client(EXPLICIT_GRANT, other) is False


def test_cross_tenant_role_holder_is_denied() -> None:
    # A permitted advisory role but the wrong tenant: object authZ denies (no leak by id).
    assert entitlements.may_access_client(OTHER_TENANT, DEMO_BANK_CLIENT) is False


def test_wrong_role_same_tenant_is_denied() -> None:
    assert entitlements.may_access_client(NO_ROLE, DEMO_BANK_CLIENT) is False


def test_ownerless_client_is_fail_closed() -> None:
    # No known owner => never role-accessible, even for an in-tenant advisory role.
    assert entitlements.may_access_client(ANALYST, OWNERLESS_CLIENT) is False


# --------------------------------------------------------------------------- #
# assert_may_access_client raises for the denied cases (maps to HTTP 403)
# --------------------------------------------------------------------------- #
def test_assert_raises_for_cross_tenant_principal() -> None:
    with pytest.raises(ClientAccessDeniedError):
        entitlements.assert_may_access_client(OTHER_TENANT, DEMO_BANK_CLIENT)


def test_assert_raises_for_ownerless_client_fail_closed() -> None:
    with pytest.raises(ClientAccessDeniedError):
        entitlements.assert_may_access_client(ANALYST, OWNERLESS_CLIENT)


def test_assert_allows_entitled_same_tenant_rm() -> None:
    # Does not raise.
    entitlements.assert_may_access_client(ANALYST, DEMO_BANK_CLIENT)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
