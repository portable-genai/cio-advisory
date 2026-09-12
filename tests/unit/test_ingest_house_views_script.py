"""``scripts/ingest_house_views.py`` loads through the gcp adapter, names a tenant, re-runs safely.

Against ``tests/fixtures/fake_agent_search.py``: no credentials, no SDK, nothing leaves the
process. All values are fictional.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from tests.fixtures.fake_agent_search import FakeAgentSearch

from cio_advisory import demo_book

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ingest_house_views.py"
PROJECT = "fictional-wealth-project"
TENANT = "fictional-bank"


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ingest_house_views", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _default_location(monkeypatch) -> None:
    monkeypatch.delenv("CIO_HOUSE_VIEWS_LOCATION", raising=False)


def test_a_dry_run_prints_what_a_load_would_write_and_needs_no_sdk(monkeypatch, capsys) -> None:
    # Importing the SDK now fails outright, so a dry run that reached for it would raise.
    for name in ("google.cloud", "google.cloud.discoveryengine_v1", "google.api_core"):
        monkeypatch.setitem(sys.modules, name, None)

    assert _script().main(["--project", PROJECT, "--tenant", TENANT, "--dry-run"]) == 0

    out = capsys.readouterr().out
    records = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    assert [r["id"] for r in records] == [v.id for v in demo_book.house_views()]
    assert {r["tenant"] for r in records} == {TENANT}
    assert (
        f"projects/{PROJECT}/locations/us/collections/default_collection"
        "/dataStores/cio-house-views/branches/default_branch" in out
    )
    assert "us-discoveryengine.googleapis.com" in out


def test_a_load_writes_through_the_adapter_to_the_configured_location_once(
    monkeypatch, capsys
) -> None:
    monkeypatch.setenv("CIO_HOUSE_VIEWS_LOCATION", "eu")
    store = FakeAgentSearch(project=PROJECT, location="eu").install(monkeypatch)
    shipped = demo_book.house_views()

    assert _script().main(["--project", PROJECT, "--tenant", TENANT]) == 0
    assert sorted(store.documents) == sorted(v.id for v in shipped)
    assert {d["tenant"] for d in store.documents.values()} == {TENANT}
    assert set(store.hosts) == {"eu-discoveryengine.googleapis.com"}
    writes = len(store.writes)

    assert _script().main(["--project", PROJECT, "--tenant", TENANT]) == 0
    assert len(store.writes) == writes, "a second load must write nothing"
    assert f"unchanged: {len(shipped)}" in capsys.readouterr().out


def test_the_tenant_is_required_and_never_empty(monkeypatch) -> None:
    store = FakeAgentSearch(project=PROJECT).install(monkeypatch)
    with pytest.raises(SystemExit) as missing:
        _script().main(["--project", PROJECT])
    assert missing.value.code == 2
    with pytest.raises(SystemExit, match="names nothing"):
        _script().main(["--project", PROJECT, "--tenant", "  "])
    assert store.writes == []


@pytest.mark.parametrize("flag", ["--location", "--data-store"])
def test_the_load_cannot_be_pointed_anywhere_the_api_does_not_read(flag) -> None:
    with pytest.raises(SystemExit) as refused:
        _script().main(["--project", PROJECT, "--tenant", TENANT, flag, "global"])
    assert refused.value.code == 2


def test_a_load_without_a_project_is_refused_before_any_call(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    store = FakeAgentSearch(project=PROJECT).install(monkeypatch)
    with pytest.raises(SystemExit, match="--project is required"):
        _script().main(["--tenant", TENANT])
    assert store.hosts == []
