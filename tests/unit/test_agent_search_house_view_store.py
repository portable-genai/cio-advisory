"""The gcp house-view adapter reads and writes the Agent Search store where it actually lives.

Driven against ``tests/fixtures/fake_agent_search.py``, which refuses a request at a location the
store is not at and a client whose host does not serve the location it names. Every value is
fictional and nothing leaves the process.
"""

from __future__ import annotations

import dataclasses
import sys

import pytest
from tests.fixtures.fake_agent_search import FakeAgentSearch, NotFound, WrongHost

from cio_advisory import demo_book
from cio_advisory.adapters.gcp.file_search_house_views import (
    FileSearchHouseViewAdapter,
    HouseViewStoreConflictError,
    api_endpoint,
    house_view_record,
)
from cio_advisory.config import HouseViewSettings, Settings
from cio_advisory.domain.models import Citation, HouseView

PROJECT = "fictional-wealth-project"
TENANT = "fictional-bank"


def _adapter(location: str = "us") -> FileSearchHouseViewAdapter:
    return FileSearchHouseViewAdapter(
        Settings(
            project_id=PROJECT, profile="gcp", house_views=HouseViewSettings(location=location)
        )
    )


@pytest.mark.parametrize(
    ("location", "host"),
    [
        ("us", "us-discoveryengine.googleapis.com"),
        ("eu", "eu-discoveryengine.googleapis.com"),
        ("global", "discoveryengine.googleapis.com"),
    ],
)
def test_each_agent_search_location_is_reached_through_its_own_host(location, host) -> None:
    assert api_endpoint(location) == host
    assert _adapter(location).endpoint == host


@pytest.mark.parametrize("location", ["asia-southeast1", "us-central1", "US", "", "global "])
def test_a_location_agent_search_does_not_serve_is_refused_before_any_call(location) -> None:
    with pytest.raises(ValueError, match="not an Agent Search location"):
        HouseViewSettings(location=location)
    with pytest.raises(ValueError, match="not an Agent Search location"):
        api_endpoint(location)


def test_the_fake_refuses_a_client_left_on_the_default_host(monkeypatch) -> None:
    """The trap the adapter must avoid, shown on the fake itself so its guard is known to bite."""
    store = FakeAgentSearch(project=PROJECT, location="us").install(monkeypatch)
    de = sys.modules["google.cloud.discoveryengine_v1"]
    client = de.SearchServiceClient()  # type: ignore[attr-defined]
    with pytest.raises(WrongHost):
        client.search(de.SearchRequest(serving_config=store.serving_config, page_size=1))  # type: ignore[attr-defined]


def test_retrieval_searches_the_engine_at_the_configured_location(monkeypatch) -> None:
    store = FakeAgentSearch(project=PROJECT, location="us").install(monkeypatch)
    view = demo_book.house_views()[0]
    store.put(view.id, house_view_record(view, TENANT))

    views = _adapter("us").retrieve("anything", top_k=5)

    assert [v.id for v in views] == [view.id]
    assert store.searches == [store.serving_config], "retrieval must search the ENGINE"
    assert store.hosts == ["us-discoveryengine.googleapis.com"]


def test_a_query_at_another_location_fails_loudly_rather_than_finding_nothing(monkeypatch) -> None:
    store = FakeAgentSearch(project=PROJECT, location="us").install(monkeypatch)
    view = demo_book.house_views()[0]
    store.put(view.id, house_view_record(view, TENANT))

    with pytest.raises(NotFound):
        _adapter("eu").retrieve("anything", top_k=5)


def test_what_the_loader_writes_is_exactly_what_retrieval_reads_back(monkeypatch) -> None:
    FakeAgentSearch(project=PROJECT).install(monkeypatch)
    shipped = demo_book.house_views()
    # Vacuity guard: a round trip over a corpus that leaves a field at its default proves nothing
    # about that field, and a field added later with a default would slip through unexamined.
    for cls, values in ((HouseView, shipped), (Citation, [v.citation for v in shipped])):
        for f in dataclasses.fields(cls):
            if f.name == "tenant":
                continue
            assert any(getattr(v, f.name) != f.default for v in values), (
                f"no shipped house view sets {cls.__name__}.{f.name}, so this round trip "
                "cannot show the store carries it"
            )

    adapter = _adapter()
    adapter.sync(shipped, TENANT)

    assert adapter.retrieve("", top_k=50) == [
        dataclasses.replace(v, tenant=TENANT) for v in shipped
    ]


def test_a_second_load_writes_nothing_and_a_changed_view_is_updated(monkeypatch) -> None:
    store = FakeAgentSearch(project=PROJECT).install(monkeypatch)
    shipped = demo_book.house_views()

    first = _adapter().sync(shipped, TENANT)
    assert first.created == tuple(v.id for v in shipped)
    assert len(store.writes) == len(shipped)

    second = _adapter().sync(shipped, TENANT)
    assert second.writes == 0
    assert second.unchanged == tuple(v.id for v in shipped)
    assert len(store.writes) == len(shipped), "an identical re-run must not write"

    revised = dataclasses.replace(shipped[0], rationale=shipped[0].rationale + " Revised.")
    third = _adapter().sync((revised, *shipped[1:]), TENANT)
    assert third.updated == (shipped[0].id,)
    assert store.writes[-1] == ("update", shipped[0].id)
    assert store.documents[shipped[0].id]["rationale"].endswith("Revised.")


@pytest.mark.parametrize("owner", ["fictional-bank-other", None])
def test_a_document_another_tenant_owns_stops_the_load_before_any_write(monkeypatch, owner) -> None:
    store = FakeAgentSearch(project=PROJECT).install(monkeypatch)
    shipped = demo_book.house_views()
    held = house_view_record(shipped[-1], "placeholder")
    if owner is None:
        del held["tenant"]
    else:
        held["tenant"] = owner
    store.put(shipped[-1].id, held)

    with pytest.raises(HouseViewStoreConflictError, match=shipped[-1].id):
        _adapter().sync(shipped, TENANT)
    assert store.writes == []


def test_a_load_names_its_tenant(monkeypatch) -> None:
    store = FakeAgentSearch(project=PROJECT).install(monkeypatch)
    with pytest.raises(ValueError, match="owning tenant"):
        _adapter().sync(demo_book.house_views(), "   ")
    assert store.writes == []


def test_documents_the_corpus_no_longer_names_are_reported_and_kept(monkeypatch) -> None:
    store = FakeAgentSearch(project=PROJECT).install(monkeypatch)
    shipped = demo_book.house_views()
    retired = dataclasses.replace(shipped[0], id="cio-2026q2-retired-theme")
    foreign = dataclasses.replace(shipped[0], id="cio-2026q3-another-banks-view")
    store.put(retired.id, house_view_record(retired, TENANT))
    store.put(foreign.id, house_view_record(foreign, "fictional-bank-other"))

    report = _adapter().sync(shipped, TENANT)

    assert report.stale == (retired.id,), "only this tenant's leftovers are this load's to report"
    assert retired.id in store.documents and foreign.id in store.documents
