"""Under ``gcp`` a briefing is grounded on the managed store and cites it, never the local corpus.

At the service boundary: the real ``AdvisoryService`` wiring (``api.deps.build_advisory_service``)
with the ``gcp`` profile's own house-view binding over ``tests/fixtures/fake_agent_search.py``,
loaded by the real loader script. The other ports are the offline ``local`` adapters, because
this file is about where the house views come from and nothing else. The local corpus readers
are made to raise for the briefing itself, so a silent fallback to the shipped corpus is a
failure rather than a coincidence of matching ids. All values are fictional.
"""

from __future__ import annotations

import dataclasses
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from cio_advisory import demo_book
from cio_advisory.adapters.gcp.file_search_house_views import (
    FileSearchHouseViewAdapter,
    house_view_record,
)
from cio_advisory.adapters.local.house_views import LocalFtsHouseViewAdapter
from cio_advisory.api.deps import build_advisory_service
from cio_advisory.config import Container
from cio_advisory.domain.errors import RetrievalEmptyError
from cio_advisory.domain.identity import Principal
from tests.contract.test_port_parity import _settings
from tests.fixtures.fake_agent_search import FakeAgentSearch
from tests.fixtures.sample_clients import BALANCED_CLIENT_ID

PROJECT = "fictional-wealth-project"
#: The tenant the local client book's rows carry, so this principal may brief the client.
TENANT = "demo-bank"
FOREIGN_ID = "cio-2026q3-another-banks-view"
PRINCIPAL = Principal(
    subject="managed-rm@bank.test", principals=("group:cio-analyst",), tenant=TENANT, source="test"
)
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ingest_house_views.py"


def _gcp_house_view(monkeypatch) -> FileSearchHouseViewAdapter:
    monkeypatch.delenv("CIO_HOUSE_VIEWS_LOCATION", raising=False)
    settings = dataclasses.replace(_settings("gcp"), project_id=PROJECT)
    adapter = Container(settings).house_view
    assert type(adapter) is FileSearchHouseViewAdapter, "gcp must bind the managed adapter itself"
    return adapter


def _service(house_view):
    local = Container(_settings("local"))
    wiring = SimpleNamespace(
        house_view=house_view,
        portfolio=local.portfolio,
        llm=local.llm,
        guardrail=local.guardrail,
        redaction=local.redaction,
        tracer=local.tracer,
        audit=local.audit,
        review_router=local.review_router,
        settings=local.settings,
    )
    service = build_advisory_service(wiring)  # type: ignore[arg-type]
    wiring.portfolio.get_profile(BALANCED_CLIENT_ID)  # seed the book before the corpus is fenced
    return service


def _load(tenant: str) -> None:
    spec = importlib.util.spec_from_file_location("ingest_house_views", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(["--project", PROJECT, "--tenant", tenant]) == 0


def _fence_the_local_corpus(monkeypatch) -> None:
    def refuse(*_args, **_kwargs):
        raise AssertionError("the gcp briefing reached the shipped local corpus")

    monkeypatch.setattr(LocalFtsHouseViewAdapter, "__init__", refuse)
    monkeypatch.setattr(LocalFtsHouseViewAdapter, "retrieve", refuse)
    monkeypatch.setattr(demo_book, "house_view_rows", refuse)
    monkeypatch.setattr(demo_book, "house_views", refuse)


def test_a_gcp_briefing_cites_the_documents_the_managed_store_holds(monkeypatch) -> None:
    store = FakeAgentSearch(project=PROJECT, location="us").install(monkeypatch)
    house_view = _gcp_house_view(monkeypatch)
    _load(TENANT)
    foreign = dataclasses.replace(demo_book.house_views()[0], id=FOREIGN_ID)
    store.put(FOREIGN_ID, house_view_record(foreign, "demo-bank-other"))
    loaded = {doc_id for doc_id, doc in store.documents.items() if doc["tenant"] == TENANT}
    service = _service(house_view)
    _fence_the_local_corpus(monkeypatch)

    briefing = service.brief(BALANCED_CLIENT_ID, PRINCIPAL)

    assert store.searches and set(store.searches) == {store.serving_config}
    considered = {view.id for view in briefing.house_views_considered}
    assert considered == loaded, "the briefing must weigh exactly this tenant's managed documents"
    cited = {c.source_id for tp in briefing.talking_points for c in tp.citations}
    assert cited, "a managed briefing must still be cited"
    assert cited <= loaded, f"cited {sorted(cited - loaded)} the managed store does not hold"
    assert FOREIGN_ID not in considered | cited, "another tenant's house view reached a briefing"


def test_an_empty_managed_store_refuses_the_briefing_instead_of_falling_back(monkeypatch) -> None:
    FakeAgentSearch(project=PROJECT, location="us").install(monkeypatch)
    service = _service(_gcp_house_view(monkeypatch))
    _fence_the_local_corpus(monkeypatch)

    with pytest.raises(RetrievalEmptyError):
        service.brief(BALANCED_CLIENT_ID, PRINCIPAL)


def test_a_store_holding_only_another_tenants_views_refuses_the_briefing(monkeypatch) -> None:
    store = FakeAgentSearch(project=PROJECT, location="us").install(monkeypatch)
    house_view = _gcp_house_view(monkeypatch)
    _load("demo-bank-other")
    service = _service(house_view)
    _fence_the_local_corpus(monkeypatch)

    with pytest.raises(RetrievalEmptyError):
        service.brief(BALANCED_CLIENT_ID, PRINCIPAL)
    assert store.searches, "the refusal must come from what the store returned, not from no search"
