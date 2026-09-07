"""The live profile's audience-data behaviours.

Pinned here:

* the live profile draws the line between fiction that may appear and fiction that may
  not: the fictional CLIENT book seeds (it is the subject of a briefing) and the fictional
  HOUSE VIEWS do not (they are the evidence a talking point cites, and live claims real
  research). This test used to assert the portfolio store started empty too, which was the
  behaviour before the 2026-09-07 decision: a live lane with no book could only brief a
  portfolio registered a minute earlier, so the gaps a briefing is about had nowhere to come
  from. The half that still holds is asserted harder here, because it is the half that would
  put an invented CIO publication behind a real-looking citation;
* client registration stamps the VERIFIED principal's tenant (never the body), the
  registered client is then briefable by its own tenant, and the template downloads;
* the grounded research adapter maps structured themes onto cited HouseViews, drops
  any theme without a real source URL, and serves from its on-disk cache.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cio_advisory.adapters.live.house_views import LiveGroundedHouseViewAdapter
from cio_advisory.adapters.local.house_views import LocalFtsHouseViewAdapter
from cio_advisory.adapters.local.portfolio import LocalPortfolioAdapter
from cio_advisory.api import deps
from cio_advisory.api.app import app
from cio_advisory.config import LiveSettings, LocalSettings, Settings
from cio_advisory.domain.models import Stance


def _settings(profile: str, **live_kwargs) -> Settings:
    base = Settings.load("config/settings.yaml")
    return Settings(
        profile=profile,
        adapters=base.adapters,
        suitability=base.suitability,
        local=LocalSettings(db_path=":memory:", audit_path=":memory:", book_path=":memory:"),
        live=LiveSettings(**live_kwargs) if live_kwargs else base.live,
    )


# --------------------------------------------------------------------------- #
# What fiction may appear under live, and what may not
# --------------------------------------------------------------------------- #
def test_the_client_book_serves_under_live_exactly_as_it_does_under_local() -> None:
    """The subject of a briefing is the same book on both laptop profiles."""
    local = LocalPortfolioAdapter(_settings("local"))
    live = LocalPortfolioAdapter(_settings("live"))
    assert live.get_profile("client-000042") == local.get_profile("client-000042")
    assert live.get_portfolio("client-000418") == local.get_portfolio("client-000418")
    assert live.client_ids("demo-bank") == local.client_ids("demo-bank")
    assert live.client_ids("demo-bank"), "an empty book leaves the live lane nothing to brief"


def test_live_house_view_index_does_not_self_seed_fiction() -> None:
    """The EVIDENCE half of the rule, and the one that would forge a citation if it broke."""
    adapter = LocalFtsHouseViewAdapter(_settings("live"))
    assert adapter.retrieve("cash equity outlook", top_k=5) == []
    seeded = LocalFtsHouseViewAdapter(_settings("local"))
    assert seeded.retrieve("cash equity outlook", top_k=5), "local must still ground offline"


# --------------------------------------------------------------------------- #
# Grounded research mapping + cache
# --------------------------------------------------------------------------- #
_THEMES = [
    {
        "theme": "Broadening equity exposure",
        "stance": "overweight",
        "asset_class": "equity",
        "rationale": "Published outlooks favour broadening beyond mega-caps.",
        "source_title": "2026 Mid-year outlook",
        "source_url": "https://publisher.example/outlook-2026",
    },
    {
        "theme": "No source theme",
        "stance": "neutral",
        "asset_class": "cash",
        "rationale": "This one has no URL and must be dropped.",
        "source_title": "",
        "source_url": "",
    },
]


def test_grounded_themes_map_to_cited_house_views_via_the_cache(tmp_path: Path) -> None:
    cache = tmp_path / "research.json"
    cache.write_text(json.dumps(_THEMES), encoding="utf-8")
    adapter = LiveGroundedHouseViewAdapter(
        _settings("live", research_cache_path=str(cache), research_cache_ttl_seconds=3600)
    )
    views = adapter.retrieve("current outlook", top_k=5)
    assert len(views) == 1, "a theme without a real source must be dropped"
    view = views[0]
    assert view.stance is Stance.OVERWEIGHT
    assert view.citation is not None
    assert view.citation.url == "https://publisher.example/outlook-2026"
    assert view.citation.title == "2026 Mid-year outlook"


# --------------------------------------------------------------------------- #
# Client registration API (audience data)
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("CIO_PROFILE", "local")
    monkeypatch.setenv("CIO_LOCAL_DB", ":memory:")
    monkeypatch.setenv("CIO_LOCAL_AUDIT", ":memory:")
    monkeypatch.setenv("CIO_LOCAL_BOOK", ":memory:")
    deps.get_container.cache_clear()
    try:
        with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
            yield test_client
    finally:
        deps.get_container.cache_clear()


_REGISTRATION = {
    "client_id": "client-audience-0001",
    "risk_appetite": "balanced",
    "objectives": ["capital-growth"],
    "holdings": [
        {"name": "Global Equity Fund", "asset_class": "equity", "value": 600000, "weight": 0.6},
        {"name": "Cash Reserve", "asset_class": "cash", "value": 400000, "weight": 0.4},
    ],
}


def test_client_template_downloads_and_registration_enables_briefing(
    client: TestClient,
) -> None:
    template = client.get("/v1/clients/template")
    assert template.status_code == 200
    assert "attachment" in template.headers["content-disposition"]
    assert "client_id" in template.json()

    created = client.post("/v1/clients", json=_REGISTRATION, headers={"X-Dev-Persona": "analyst"})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["tenant"] == "demo-bank", "tenant must come from the verified principal"
    assert body["holdings"] == 2
    assert body["total_value"] == pytest.approx(1_000_000)

    listed = client.get("/v1/clients", headers={"X-Dev-Persona": "analyst"})
    assert "client-audience-0001" in listed.json()["clients"]

    briefing = client.post(
        "/v1/briefing",
        json={"client_id": "client-audience-0001"},
        headers={"X-Dev-Persona": "analyst"},
    )
    assert briefing.status_code == 200, briefing.text


def test_registration_rejects_unknown_enums(client: TestClient) -> None:
    bad = dict(_REGISTRATION, risk_appetite="yolo")
    response = client.post("/v1/clients", json=bad, headers={"X-Dev-Persona": "analyst"})
    assert response.status_code == 422
