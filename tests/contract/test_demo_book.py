"""The demo book: one set of shipped rows, served identically by every store that reads it.

Pinned here:

* the shipped book is internally consistent, and the console's picker names only clients
  the book serves (it used to list two the server did not have);
* the managed BigQuery adapter selects only columns the Terraform schema declares, and the
  schema declares the ``tenant`` column the entitlement gate reads (it did not);
* the DuckDB store the ``local`` and ``live`` profiles read serves exactly the shipped rows,
  under BOTH profiles, and a registered client sits beside them;
* the tenant gate holds on the book: the ``other-bank`` client is invisible to ``demo-bank``;
* the loader's overwrite guard refuses a store that holds rows and no fictional manifest.

Every check here was watched failing first: the picker ids against the two-client seed, the
``tenant`` column against ``bigquery.tf`` as it was, and the live-profile reads against the
adapter that deliberately served nothing under ``live``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from cio_advisory import demo_book
from cio_advisory.adapters.gcp import bigquery_portfolio
from cio_advisory.adapters.local.portfolio import LocalPortfolioAdapter
from cio_advisory.config import LocalSettings, Settings
from cio_advisory.domain.models import ClientProfile, Portfolio, RiskAppetite

_REPO = Path(__file__).resolve().parents[2]
_TF = _REPO / "infra" / "terraform" / "bigquery.tf"
_PICKER = _REPO / "ui" / "components" / "ClientPanel.tsx"


def _settings(profile: str) -> Settings:
    base = Settings.load("config/settings.yaml")
    return Settings(
        profile=profile,
        adapters=base.adapters,
        suitability=base.suitability,
        bigquery=base.bigquery,
        local=LocalSettings(db_path=":memory:", audit_path=":memory:", book_path=":memory:"),
    )


# --------------------------------------------------------------------------- #
# The shipped rows
# --------------------------------------------------------------------------- #
def test_the_shipped_book_is_internally_consistent() -> None:
    demo_book.validate()
    ids = set(demo_book.profiles())
    assert ids == set(demo_book.portfolios())
    assert len(ids) == 7
    assert demo_book.manifest()["fictional"] is True


def test_every_client_the_console_picker_names_exists_in_the_book() -> None:
    picker_ids = set(re.findall(r"client-\d{6}", _PICKER.read_text(encoding="utf-8")))
    assert picker_ids, "the picker names no sample clients; the regex or the file moved"
    missing = sorted(picker_ids - set(demo_book.profiles()))
    assert not missing, f"the console offers clients the server does not serve: {missing}"


def test_the_validator_can_see_a_broken_book(monkeypatch: pytest.MonkeyPatch) -> None:
    good = demo_book.rows

    def broken(table: str):  # type: ignore[no-untyped-def]
        out = good(table)
        if table == "holdings":
            out[0] = dict(out[0], weight=float(out[0]["weight"]) + 0.5)
        return out

    monkeypatch.setattr(demo_book, "rows", broken)
    with pytest.raises(demo_book.BookError, match="not 1.0"):
        demo_book.validate()


# --------------------------------------------------------------------------- #
# The managed schema
# --------------------------------------------------------------------------- #
def _terraform_tables() -> dict[str, set[str]]:
    """``table_id -> column names`` for every table ``bigquery.tf`` declares."""
    text = _TF.read_text(encoding="utf-8")
    blocks = re.findall(
        r'resource\s+"google_bigquery_table"\s+"\w+"\s*\{(.*?)\n\}', text, flags=re.DOTALL
    )
    assert blocks, "no google_bigquery_table blocks found; the regex or the file moved"
    tables: dict[str, set[str]] = {}
    for block in blocks:
        table_id = re.search(r'table_id\s*=\s*"(\w+)"', block)
        assert table_id is not None, "a table block without a table_id"
        tables[table_id.group(1)] = set(re.findall(r'name\s*=\s*"(\w+)"', block))
    return tables


def test_the_managed_adapter_selects_only_columns_the_terraform_declares() -> None:
    declared = _terraform_tables()
    for table_key, columns in bigquery_portfolio.SELECTED_COLUMNS.items():
        table_id = getattr(_settings("gcp").bigquery, table_key)
        assert table_id in declared, f"{table_key} -> {table_id!r} is not a Terraform table"
        undeclared = sorted(set(columns) - declared[table_id])
        assert not undeclared, f"{table_id} selects columns Terraform never declares: {undeclared}"


def test_the_profile_table_declares_the_tenant_column_the_gate_reads() -> None:
    assert "tenant" in _terraform_tables()["client_profiles"]


def test_the_terraform_declares_every_table_the_book_ships() -> None:
    assert set(demo_book.TABLES) <= set(_terraform_tables())


# --------------------------------------------------------------------------- #
# The DuckDB store, under both laptop profiles
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("profile", ["local", "live"])
def test_the_store_serves_exactly_the_shipped_rows(profile: str) -> None:
    store = LocalPortfolioAdapter(_settings(profile))
    expected_profiles = demo_book.profiles()
    expected_portfolios = demo_book.portfolios()
    for client_id, profile_row in expected_profiles.items():
        got_profile: ClientProfile = store.get_profile(client_id)
        got_portfolio: Portfolio = store.get_portfolio(client_id)
        assert got_profile == profile_row, client_id
        assert got_portfolio == expected_portfolios[client_id], client_id
    with pytest.raises(KeyError):
        store.get_profile("client-does-not-exist")


def test_the_book_is_seeded_once_and_survives_a_second_open(tmp_path: Path) -> None:
    base = Settings.load("config/settings.yaml")
    path = str(tmp_path / "book.duckdb")

    def settings() -> Settings:
        return Settings(
            profile="local",
            adapters=base.adapters,
            suitability=base.suitability,
            local=LocalSettings(db_path=":memory:", audit_path=":memory:", book_path=path),
        )

    first = LocalPortfolioAdapter(settings())
    assert first.get_profile("client-000418").risk_appetite is RiskAppetite.AGGRESSIVE
    first.close()
    second = LocalPortfolioAdapter(settings())
    assert second.client_ids("demo-bank") == first_ids_expected()
    second.close()


def first_ids_expected() -> list[str]:
    return sorted(
        cid for cid, p in demo_book.profiles().items() if p.tenant == demo_book.SHIPPED_TENANT
    )


def test_the_other_tenant_client_is_invisible_to_the_demo_bank() -> None:
    store = LocalPortfolioAdapter(_settings("live"))
    assert "client-000999" not in store.client_ids("demo-bank")
    assert store.client_ids("other-bank") == ["client-000999"]
    assert store.get_profile("client-000999").tenant == "other-bank"


def test_a_registered_client_sits_beside_the_book_under_live() -> None:
    store = LocalPortfolioAdapter(_settings("live"))
    registered = demo_book.profiles()["client-000042"]
    profile = ClientProfile(
        id="client-audience-0001",
        risk_appetite=registered.risk_appetite,
        objectives=registered.objectives,
        tenant="",
    )
    portfolio = demo_book.portfolios()["client-000042"]
    portfolio = Portfolio(
        client_id="client-audience-0001",
        holdings=portfolio.holdings,
        total_value=portfolio.total_value,
        currency=portfolio.currency,
    )
    store.register(profile, portfolio, tenant="demo-bank")
    assert "client-audience-0001" in store.client_ids("demo-bank")
    assert store.get_profile("client-audience-0001").tenant == "demo-bank"
    assert store.get_portfolio("client-audience-0001").holdings == portfolio.holdings
    assert store.get_profile("client-000042") == registered, "the book is untouched"


# --------------------------------------------------------------------------- #
# The loader's overwrite guard
# --------------------------------------------------------------------------- #
def test_the_guard_refuses_a_populated_store_without_a_fictional_manifest() -> None:
    assert demo_book.may_overwrite({"holdings": 0, "client_profiles": 0}, []) is True
    assert demo_book.may_overwrite({"holdings": 12, "client_profiles": 3}, []) is False
    assert (
        demo_book.may_overwrite({"holdings": 12, "client_profiles": 3}, [{"fictional": False}])
        is False
    )
    assert (
        demo_book.may_overwrite({"holdings": 12, "client_profiles": 3}, [{"fictional": True}])
        is True
    )
