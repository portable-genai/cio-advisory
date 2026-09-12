"""The loader writes into the schema the table already has, rather than replacing it.

A BigQuery load with ``WRITE_TRUNCATE`` and no schema autodetects one from the rows and
**replaces** the table's. Nothing fails at the time: the rows land and the demo reads them. What
it costs arrives at the next `terraform plan`, where every table it touched reports
``must be replaced`` -- because the live schema now has its columns in the order the JSON
happened to serialise them and every mode relaxed to NULLABLE, while ``infra/terraform``
declares them REQUIRED in its own order. BigQuery cannot narrow a mode in place, so Terraform's
only move is to destroy and recreate, and a recreated table holds no rows.

Found on 2026-09-12 by planning this stack before its first full apply: all five tables of the
demo book, loaded on 2026-09-09, planned as replacements. The rows are fictional and shipped in
this repository, so they are reloadable; the silent schema rewrite is the defect.

Driven against a fake client rather than BigQuery, because what is asserted is the job
configuration the loader builds, and a real client would need credentials the offline gate
refuses. Watched failing first: dropping the ``schema=`` argument leaves the fake's schema unset,
which is exactly the configuration that replaced the live schema.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

_LOADER = Path(__file__).resolve().parents[2] / "scripts" / "load_demo_book.py"

DECLARED_SCHEMA = ("client_id", "instrument_id", "line_no")


class _FakeTable:
    def __init__(self, schema: tuple[str, ...]) -> None:
        self.schema = schema
        self.num_rows = 0


class _FakeJob:
    def result(self) -> None:
        return None


class _FakeClient:
    """Records the job configuration every load was given."""

    def __init__(self) -> None:
        self.loads: list[Any] = []

    def get_table(self, _ref: Any) -> _FakeTable:
        return _FakeTable(DECLARED_SCHEMA)

    def load_table_from_json(self, _rows: Any, _ref: Any, job_config: Any) -> _FakeJob:
        self.loads.append(job_config)
        return _FakeJob()

    def query(self, _sql: str) -> Any:  # pragma: no cover - the guard path is tested elsewhere
        raise AssertionError("this test never reaches the overwrite guard")


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("load_demo_book_under_test", _LOADER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _install_fake_bigquery(monkeypatch: Any, client: _FakeClient) -> None:
    """Stand in for google.cloud.bigquery, which this repo's venv deliberately does not hold."""

    class WriteDisposition:
        WRITE_TRUNCATE = "WRITE_TRUNCATE"

    class LoadJobConfig:
        def __init__(self, **kwargs: Any) -> None:
            self.schema = kwargs.get("schema")
            self.write_disposition = kwargs.get("write_disposition")
            self.schema_update_options = kwargs.get("schema_update_options")

    class TableReference:
        @staticmethod
        def from_string(value: str) -> str:
            return value

    fake = types.SimpleNamespace(
        Client=lambda **_kwargs: client,
        LoadJobConfig=LoadJobConfig,
        WriteDisposition=WriteDisposition,
        TableReference=TableReference,
    )
    cloud = types.ModuleType("google.cloud")
    cloud.bigquery = fake  # type: ignore[attr-defined]
    google = sys.modules.get("google") or types.ModuleType("google")
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.bigquery", fake)
    exceptions = types.ModuleType("google.api_core.exceptions")
    exceptions.NotFound = type("NotFound", (Exception,), {})  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google.api_core", types.ModuleType("google.api_core"))
    monkeypatch.setitem(sys.modules, "google.api_core.exceptions", exceptions)


def test_every_load_carries_the_tables_own_schema(monkeypatch: Any) -> None:
    module = _load_module()
    client = _FakeClient()
    _install_fake_bigquery(monkeypatch, client)
    monkeypatch.setattr(module, "_existing", lambda *_a, **_k: dict.fromkeys(module._TABLES, 0))
    monkeypatch.setattr(module, "_manifest_rows", lambda *_a, **_k: [])
    rows = {table: [] for table in module._TABLES}

    module.load("fictional-project", "wealth_portfolio", rows, "asia-southeast1")

    assert client.loads, "the loader ran no load job"
    for config in client.loads:
        assert config.write_disposition == "WRITE_TRUNCATE"
        assert config.schema == DECLARED_SCHEMA, (
            "every load must pass the schema the table already has. Without it BigQuery "
            "autodetects a schema from the rows and replaces the declared one, and the next "
            "terraform plan then reports the table as must-be-replaced, which destroys its rows"
        )
