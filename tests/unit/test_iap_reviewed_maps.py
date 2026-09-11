"""The reviewed maps that turn a verified IAP caller into a tenant and a role.

A deployment loads its client book under a tenant id it chose, and signs users in from Workspace
domains whose names are nothing like it. With the hosted domain as the only source of a tenant,
every verified user resolved to their own domain, every client row belonged to the loaded tenant,
and the entitlement gate failed closed for everybody: authentication working and every briefing
refused. The caller also held no role, because an IAP assertion grants ``user:<subject>`` and
nothing else while the gate asks for ``group:cio-analyst``.

Observed failing first: this file failed at import, because the adapter held one literal policy
and a deployment had no way to say either thing. Deleting the env reads from
``_federation_policy`` turns the mapped-domain and machine-caller tests red again.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from hex_service_kit.federation import IAP_ASSERTION_HEADER, IAP_ISSUER

from cio_advisory.adapters.gcp.iap_identity import IapIdentityAdapter, _federation_policy
from cio_advisory.domain.entitlements import may_access_client
from cio_advisory.domain.identity import RequestContext
from cio_advisory.domain.models import ClientProfile, RiskAppetite

_AUDIENCE = "/projects/1234567890/global/backendServices/42"
_TENANTS = "CIO_IAP_TENANT_DOMAINS_JSON"
_GROUPS = "CIO_IAP_GROUPS_JSON"
_MACHINES = "CIO_IAP_MACHINE_TENANTS_JSON"
_E2E = "portal-e2e@fictional-project.iam.gserviceaccount.com"


@pytest.fixture(autouse=True)
def _no_reviewed_maps(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (_TENANTS, _GROUPS, _MACHINES):
        monkeypatch.delenv(name, raising=False)


def _token() -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256"}).encode()).decode().rstrip("=")
    return f"{header}.e30.c2ln"


def _claims(**overrides: Any) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "iss": IAP_ISSUER,
        "aud": _AUDIENCE,
        "sub": "accounts.google.com:100000000000000000001",
        "email": "avery.stone@example-bank.test",
        "hd": "example-bank.test",
        "exp": 4102444800,
    }
    claims.update(overrides)
    return {name: value for name, value in claims.items() if value is not None}


def _resolve(claims: dict[str, Any]) -> Any:
    """The shipped claim half with the cryptography stubbed, as the claim-half suite does."""
    adapter = object.__new__(IapIdentityAdapter)
    adapter._settings = None
    adapter._audience = _AUDIENCE
    adapter._audience_configured_empty = False
    object.__setattr__(adapter, "_verify", lambda assertion: dict(claims))
    return adapter.resolve(RequestContext(headers={IAP_ASSERTION_HEADER: _token()}))


def _profile() -> ClientProfile:
    return ClientProfile(
        id="client-000418",
        risk_appetite=RiskAppetite.BALANCED,
        objectives=(),
        knowledge_experience="informed",
        constraints=(),
        jurisdiction="SG",
        tenant="reference-bank",
    )


def test_unset_maps_leave_the_hosted_domain_passthrough_unchanged() -> None:
    policy = _federation_policy()
    assert policy.tenant_from_hosted_domain is True
    assert dict(policy.domain_tenants) == {}
    assert dict(policy.domain_groups) == {}
    assert dict(policy.machine_tenants) == {}
    assert _resolve(_claims()).tenant == "example-bank.test"


def test_without_the_maps_a_verified_user_is_refused_the_loaded_book() -> None:
    """The control: the maps are load-bearing, not decoration."""
    assert may_access_client(_resolve(_claims()), _profile()) is False


def test_a_mapped_domain_reaches_the_tenant_and_role_the_book_was_loaded_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_TENANTS, json.dumps({"Example-Bank.TEST": "reference-bank"}))
    monkeypatch.setenv(_GROUPS, json.dumps({"example-bank.test": ["group:cio-analyst"]}))
    principal = _resolve(_claims())
    assert principal.tenant == "reference-bank"
    assert "group:cio-analyst" in principal.principals
    assert may_access_client(principal, _profile()) is True


def test_a_machine_caller_is_tenanted_by_its_exact_account_and_never_by_its_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_MACHINES, json.dumps({_E2E: "reference-bank"}))
    assert _resolve(_claims(hd=None, email=_E2E)).tenant == "reference-bank"
    sibling = "some-other-runner@fictional-project.iam.gserviceaccount.com"
    assert _resolve(_claims(hd=None, email=sibling)).tenant == ""


@pytest.mark.parametrize("name", [_TENANTS, _GROUPS, _MACHINES])
def test_an_emptied_map_is_a_configuration_error_not_an_absent_one(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv(name, "")
    with pytest.raises(ValueError, match=name):
        _federation_policy()


@pytest.mark.parametrize(
    "name,value",
    [
        (_TENANTS, "not json"),
        (_TENANTS, "[]"),
        (_TENANTS, json.dumps({"": "reference-bank"})),
        (_TENANTS, json.dumps({"*": "reference-bank"})),
        (_TENANTS, json.dumps({"example-bank.test": ""})),
        (_GROUPS, json.dumps({"example-bank.test": "group:cio-analyst"})),
        (_GROUPS, json.dumps({"example-bank.test": []})),
        (_MACHINES, json.dumps({_E2E: None})),
    ],
)
def test_a_malformed_map_refuses_rather_than_mapping_nothing(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        _federation_policy()
