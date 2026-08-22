"""API-boundary identity tests: the verified Principal replaces any client-sent actor.

Exercises the FastAPI surface end to end under the ``local`` profile (seeded dev
personas, no IdP): the default persona is the audit actor, a body-supplied ``actor`` is
ignored, an unknown ``X-Dev-Persona`` is a 401, and ``/v1/personas`` feeds the UI picker.
The advisory service dependency is overridden with the same recording local adapters the
unit suite uses, so the audit sink is inspectable and nothing touches ``~/.cio_advisory``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tests.conftest import (
    RecordingAudit,
    RecordingGuardrail,
    RecordingHouseView,
    RecordingLLM,
    RecordingPortfolio,
    RecordingRedaction,
    RecordingTracer,
)

from cio_advisory.api import deps
from cio_advisory.api.app import app
from cio_advisory.config import LocalSettings, Settings
from cio_advisory.domain.services import AdvisoryService

_DEFAULT_SUBJECT = "demo.analyst@bank.example"  # first seeded persona = local default


def _settings() -> Settings:
    return Settings(
        profile="local",
        local=LocalSettings(db_path=":memory:", audit_path=":memory:"),
    )


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch):
    """TestClient wired to the real local container (persona identity) + recording service."""
    monkeypatch.setenv("CIO_PROFILE", "local")
    monkeypatch.setenv("CIO_LOCAL_DB", ":memory:")
    monkeypatch.setenv("CIO_LOCAL_AUDIT", ":memory:")
    deps.get_container.cache_clear()

    settings = _settings()
    audit = RecordingAudit(settings)
    service = AdvisoryService(
        house_view=RecordingHouseView(settings),
        portfolio=RecordingPortfolio(settings),
        llm=RecordingLLM(settings),
        guardrail=RecordingGuardrail(settings),
        redaction=RecordingRedaction(settings),
        tracer=RecordingTracer(settings),
        audit=audit,
    )
    app.dependency_overrides[deps.get_advisory_service] = lambda: service
    yield TestClient(app, client=("127.0.0.1", 50000)), audit
    app.dependency_overrides.clear()
    deps.get_container.cache_clear()


def test_healthz_reports_local_profile(api) -> None:
    client, _ = api
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["profile"] == "local"  # the UI persona picker gates on this
    assert body["region"] == "asia-southeast1"


def test_personas_listing_feeds_the_picker(api) -> None:
    client, _ = api
    response = client.get("/v1/personas")
    assert response.status_code == 200
    personas = response.json()
    assert [p["id"] for p in personas][:1] == ["analyst"]  # first persona is the default
    assert {p["id"] for p in personas} == {"analyst", "approver", "auditor", "other-tenant"}


def test_an_unconsented_run_refuses_the_seeded_personas(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED before the three-state fix: an unset CIO_PROFILE was read as "chose local".

    ``local`` binds the seeded-persona identity adapter, which authenticates nobody, so a
    process that merely lost an environment variable served the whole advisory API to any
    caller. It now answers 401, and the persona picker lists nothing.
    """
    monkeypatch.delenv("CIO_PROFILE", raising=False)
    monkeypatch.setenv("CIO_LOCAL_DB", ":memory:")
    monkeypatch.setenv("CIO_LOCAL_AUDIT", ":memory:")
    deps.get_container.cache_clear()
    try:
        client = TestClient(app, client=("127.0.0.1", 50000))
        refused = client.post("/v1/briefing", json={"client_id": "client-000042"})
        listed = client.get("/v1/personas")
    finally:
        deps.get_container.cache_clear()

    assert refused.status_code == 401
    assert listed.json() == []


def test_unknown_dev_persona_is_401(api) -> None:
    client, _ = api
    response = client.post(
        "/v1/briefing",
        json={"client_id": "client-000042"},
        headers={"X-Dev-Persona": "does-not-exist"},
    )
    assert response.status_code == 401


def test_body_actor_is_ignored_default_persona_is_audit_actor(api) -> None:
    client, audit = api
    response = client.post(
        "/v1/briefing",
        json={"client_id": "client-000042", "actor": "spoofed@attacker.example"},
    )
    assert response.status_code == 200
    assert response.json()["requires_human_review"] is True
    actors = {event.actor for event in audit.events}
    assert actors == {_DEFAULT_SUBJECT}, "audit actor must be the verified principal"
    assert "spoofed@attacker.example" not in actors


def test_selected_persona_becomes_audit_actor(api) -> None:
    client, audit = api
    response = client.post(
        "/v1/talking-points",
        json={"client_id": "client-000042"},
        headers={"X-Dev-Persona": "auditor"},
    )
    assert response.status_code == 200
    assert {event.actor for event in audit.events} == {"demo.auditor@bank.example"}


# --------------------------------------------------------------------------- #
# Object-level authorization (C2): a client_id is not a capability. The verified
# principal must be entitled to the client (own tenant or explicit grant), enforced
# server-side inside the service, so an authenticated RM in ANOTHER tenant cannot read
# a demo-bank client's portfolio/PII by guessing its id.
# --------------------------------------------------------------------------- #
_DEMO_BANK_CLIENT = "client-000042"  # seeded, owned by tenant demo-bank
_THEME = "AI infrastructure build-out"
_HOLDING_MARKERS = ("Global Equity Fund", "IG Bond Fund", "Cash Reserve")

_ARTIFACT_REQUESTS = (
    ("/v1/briefing", {"client_id": _DEMO_BANK_CLIENT}),
    ("/v1/talking-points", {"client_id": _DEMO_BANK_CLIENT}),
    ("/v1/suitability", {"client_id": _DEMO_BANK_CLIENT, "theme": _THEME}),
)


def test_cross_tenant_persona_is_denied_403_and_leaks_nothing(api) -> None:
    # The other-bank persona holds an advisory role but not tenant:demo-bank and no
    # explicit client grant, so every artifact route must fail closed with 403.
    client, audit = api
    for path, body in _ARTIFACT_REQUESTS:
        response = client.post(path, json=body, headers={"X-Dev-Persona": "other-tenant"})
        assert response.status_code == 403, f"{path} must deny a cross-tenant caller"
        text = response.text
        assert "talking_points" not in text, f"{path} leaked a briefing to a denied caller"
        assert not any(marker in text for marker in _HOLDING_MARKERS), (
            f"{path} leaked client portfolio PII to a denied caller"
        )
    # Fail-closed: a denied request generates and audits nothing (no briefing was built).
    assert audit.events == [], "a denied cross-tenant request must not produce/audit a briefing"


def test_same_tenant_rm_is_allowed_200(api) -> None:
    # The assigned same-tenant RM (analyst @ demo-bank) is entitled to the demo-bank client.
    client, _ = api
    for path, body in _ARTIFACT_REQUESTS:
        response = client.post(path, json=body, headers={"X-Dev-Persona": "analyst"})
        assert response.status_code == 200, f"{path} must allow the assigned same-tenant RM"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
