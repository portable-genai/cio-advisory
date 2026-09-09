"""Local portfolio adapter (PortfolioPort): the laptop's DuckDB client book.

The ``local`` and ``live`` profiles' stand-in for the **BigQuery** portfolio store. It is a
DuckDB file holding the same tables the managed dataset does, in the same column order, so
the offline store answers the same shapes the BigQuery adapter reads and the two can be
compared rather than merely coexist. DuckDB is an embedded engine in a wheel: no service, no
credentials, nothing to start, which is what keeps the offline gate honest.

The book self-seeds from the shipped NDJSON under ``cio_advisory/data/demo_book/`` when the
store is empty, so an out-of-the-box run has clients to brief, and it seeds under ``live``
too (org decision, 2026-09-07). The rule that decision refined: what may never enter a live
briefing is the fictional CIO *corpus*, because a house view is the evidence a talking point
cites. Client records are the SUBJECT rather than the evidence, the console labels the book
as fictional, and without them the live lane can only show a portfolio typed in a minute
earlier. The house-view index still refuses to self-seed under ``live``; that half of the
decision is unchanged and is enforced in ``house_views.py``.

Seeding never overwrites a populated store that does not declare itself fictional
(``demo_book.may_overwrite``), because this same guard is what the managed loader runs and a
guard proved in one place only is a guard that drifts.

Object-authorization owner (C2): the adapter is the server-side authority on which tenant
OWNS each client. Every profile row carries its owning tenant and ``get_profile`` returns it
stamped, so the entitlement gate (``domain/entitlements.py``) decides access from the
VERIFIED principal. An audience registration is stamped with the registering principal's
tenant. The owner is never taken from a client-supplied field, and a client whose row has no
tenant fails closed at the gate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hex_service_kit.demobook import DuckDbStore

from ... import demo_book
from ...config import Settings
from ...domain.models import (
    AllocationTarget,
    AssetClass,
    ClientProfile,
    DataCitation,
    Holding,
    ModelPortfolio,
    Portfolio,
    RiskAppetite,
)

#: Default on-disk location for the laptop book (overridable via settings.local.book_path).
_DEFAULT_BOOK_PATH = Path.home() / ".cio_advisory" / "book.duckdb"

#: The tables the store holds, their column order and their DDL all come from the book's own
#: :class:`~hex_service_kit.demobook.Table` declarations now. They used to be a second copy in
#: this module: a DDL string per table, a column order derived from it by splitting the DDL,
#: and a date-column set beside them. Three descriptions of one schema, none of which any test
#: could hold against the BigQuery schema they were meant to mirror.
_COLUMNS: dict[str, tuple[str, ...]] = {
    table.name: table.columns for table in demo_book.BOOK.load_order()
}

_DATE_COLUMNS = frozenset(
    column for table in demo_book.BOOK.load_order() for column in table.date_columns
)


class LocalPortfolioAdapter:
    """Serve client profiles and portfolios from the laptop's DuckDB book."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        path = getattr(getattr(settings, "local", None), "book_path", "") or str(_DEFAULT_BOOK_PATH)
        self._path = path
        # The store, the schema, the self-seed and the overwrite guard all come from the kit
        # now. It creates the tables from the book's own column declarations, seeds when the
        # store holds nothing at all, and leaves a populated store exactly as it is whoever
        # wrote it: re-seeding on every open would discard the clients an audience registered
        # in an earlier run of the same demo. It seeds under every laptop profile including
        # `live`, because the fictional CLIENTS are the subject of a briefing rather than the
        # evidence it cites and the console labels them; the fictional house views are a
        # different matter and stay out of `live` entirely (`house_views.py`).
        demo_book.validate()
        self._store = DuckDbStore(demo_book.BOOK, path)
        self._conn = self._store.connection

    # ------------------------------------------------------------------ #
    # Seeding
    # ------------------------------------------------------------------ #
    def seed_shipped_book(self) -> None:
        """Replace this store's contents with the shipped demo book.

        Refuses a populated store whose manifest does not declare it fictional, which is the
        same guard, in the same function, that the managed loader runs before it truncates a
        BigQuery dataset. One rule proved in one place, called from two, and since the kit
        owns it that is now one place across five repositories rather than this one.
        """
        self._store.seed_shipped_book()

    def _insert(self, table: str, rows: list[dict[str, Any]]) -> None:
        """Insert rows the ADAPTER wrote (an audience registration), in declared order."""
        self._store.insert(demo_book.BOOK.table(table), rows)

    def close(self) -> None:
        """Close the DuckDB connection (the CLI and tests reopen the same file)."""
        self._store.close()

    # ------------------------------------------------------------------ #
    # Audience registration
    # ------------------------------------------------------------------ #
    def register(self, profile: ClientProfile, portfolio: Portfolio, tenant: str) -> None:
        """Add or replace one audience-provided client (the API derives ``tenant``).

        The registration is written to the same tables the book occupies, so a registered
        client and a shipped one are indistinguishable to every read below. Its instruments
        are registered too, under generated ids, because a holding names an instrument row.
        """
        as_of = demo_book.manifest()["as_of_date"]
        self._conn.execute("DELETE FROM holdings WHERE client_id = ?", [profile.id])
        self._conn.execute("DELETE FROM client_profiles WHERE client_id = ?", [profile.id])
        self._insert(
            "client_profiles",
            [
                {
                    "client_id": profile.id,
                    "tenant": tenant,
                    "risk_appetite": profile.risk_appetite.value,
                    "objectives": list(profile.objectives),
                    "knowledge_experience": profile.knowledge_experience,
                    "constraints": list(profile.constraints),
                    "jurisdiction": profile.jurisdiction,
                    "currency": portfolio.currency,
                    "segment": "registered",
                    "time_horizon_years": None,
                    "last_review_date": None,
                    "as_of_date": as_of,
                }
            ],
        )
        for line_no, holding in enumerate(portfolio.holdings, start=1):
            instrument_id = self._instrument_id(holding)
            self._insert(
                "holdings",
                [
                    {
                        "client_id": profile.id,
                        "instrument_id": instrument_id,
                        "line_no": line_no,
                        "value": holding.value,
                        "weight": holding.weight,
                        "currency": holding.currency,
                        "as_of_date": as_of,
                    }
                ],
            )

    def _instrument_id(self, holding: Holding) -> str:
        """The id of a registered holding's instrument, creating the row when it is new.

        A registered portfolio names its instruments by display name, so an existing row
        with that name and asset class is reused and anything else becomes a new
        ``REG-`` instrument. Reuse matters: it is what lets a registered client's holding
        carry the same theme tags a shipped one does.
        """
        found = self._conn.execute(
            "SELECT instrument_id FROM instruments WHERE name = ? AND asset_class = ? LIMIT 1",
            [holding.instrument, holding.asset_class.value],
        ).fetchone()
        if found is not None:
            return str(found[0])
        instrument_id = f"REG-{abs(hash((holding.instrument, holding.asset_class.value))):012x}"
        self._insert(
            "instruments",
            [
                {
                    "instrument_id": instrument_id,
                    "name": holding.instrument,
                    "asset_class": holding.asset_class.value,
                    "sub_class": None,
                    "region": None,
                    "theme_tags": [],
                    "esg": None,
                    "liquidity": None,
                }
            ],
        )
        return instrument_id

    def seed(
        self,
        profiles: dict[str, ClientProfile] | None = None,
        portfolios: dict[str, Portfolio] | None = None,
        owners: dict[str, str] | None = None,
    ) -> None:
        """Replace the store with an explicit set of clients (deterministic test/CLI seed)."""
        if profiles is None and portfolios is None:
            return
        self._conn.execute("DELETE FROM holdings")
        self._conn.execute("DELETE FROM client_profiles")
        for client_id, profile in (profiles or {}).items():
            portfolio = (portfolios or {}).get(client_id, Portfolio(client_id=client_id))
            tenant = (owners or {}).get(client_id) or profile.tenant or demo_book.SHIPPED_TENANT
            self.register(profile, portfolio, tenant)

    # ------------------------------------------------------------------ #
    # PortfolioPort
    # ------------------------------------------------------------------ #
    def client_ids(self, tenant: str) -> list[str]:
        """The client ids owned by ``tenant`` (for the UI's picker)."""
        rows = self._conn.execute(
            "SELECT client_id FROM client_profiles WHERE tenant = ? ORDER BY client_id",
            [tenant],
        ).fetchall()
        return [str(row[0]) for row in rows]

    def get_profile(self, client_id: str) -> ClientProfile:
        row = self._conn.execute(
            "SELECT risk_appetite, objectives, knowledge_experience, constraints, "
            "jurisdiction, tenant FROM client_profiles WHERE client_id = ?",
            [client_id],
        ).fetchone()
        if row is None:
            raise KeyError(client_id)
        appetite, objectives, knowledge, constraints, jurisdiction, tenant = row
        return ClientProfile(
            id=client_id,
            risk_appetite=RiskAppetite(str(appetite)),
            objectives=tuple(str(o) for o in objectives or ()),
            knowledge_experience=str(knowledge or "informed"),
            constraints=tuple(str(c) for c in constraints or ()),
            jurisdiction=str(jurisdiction or "SG"),
            tenant=str(tenant or ""),
        )

    def get_portfolio(self, client_id: str) -> Portfolio:
        rows = self._conn.execute(
            "SELECT i.name, i.asset_class, h.value, h.weight, h.currency, "
            "h.instrument_id, i.theme_tags "
            "FROM holdings h JOIN instruments i USING (instrument_id) "
            "WHERE h.client_id = ? ORDER BY h.line_no",
            [client_id],
        ).fetchall()
        if not rows:
            raise KeyError(client_id)
        holdings = tuple(
            Holding(
                instrument=str(name),
                asset_class=AssetClass(str(asset_class)),
                value=float(value),
                weight=float(weight),
                currency=str(currency or "USD"),
                instrument_id=str(instrument_id),
                tags=tuple(str(t) for t in tags or ()),
            )
            for name, asset_class, value, weight, currency, instrument_id, tags in rows
        )
        return Portfolio(
            client_id=client_id,
            holdings=holdings,
            total_value=sum(h.value for h in holdings),
            currency=holdings[0].currency,
        )

    def read_provenance(self, client_id: str) -> DataCitation:
        """The DuckDB read behind this client's holdings, named as DuckDB and not as BigQuery.

        The as-of date comes from the store's own manifest rather than from the shipped
        package, so a book somebody loaded themselves reports THEIR date. A store with no
        manifest row reports an empty date, which reads as "the store does not say".
        """
        manifest = self._store.manifest_rows()
        as_of = ""
        for row in manifest:
            value = row.get("as_of_date")
            if value:
                as_of = str(value)[:10]
                break
        return DataCitation(
            store="duckdb",
            dataset=Path(self._path).stem if self._path != ":memory:" else ":memory:",
            table="holdings",
            predicate=f"client_id = '{client_id}'",
            row_count=0,  # the caller knows how many rows it received; this states the read
            as_of=as_of,
        )

    def get_model_portfolio(
        self, risk_appetite: RiskAppetite, jurisdiction: str = "SG"
    ) -> ModelPortfolio | None:
        """The most recent published allocation for a profile, or None if there is none.

        Most recent by effective date: a bank republishes its strategic allocation and a
        briefing must measure against the edition in force, not the first one loaded.
        """
        rows = self._conn.execute(
            "SELECT model_id, asset_class, target_weight, min_weight, max_weight, "
            "effective_from, source FROM model_portfolios "
            "WHERE risk_appetite = ? AND (jurisdiction = ? OR jurisdiction IS NULL) "
            "AND effective_from = ("
            "  SELECT max(effective_from) FROM model_portfolios "
            "  WHERE risk_appetite = ? AND (jurisdiction = ? OR jurisdiction IS NULL)"
            ") ORDER BY asset_class",
            [risk_appetite.value, jurisdiction, risk_appetite.value, jurisdiction],
        ).fetchall()
        if not rows:
            return None
        targets = tuple(
            AllocationTarget(
                asset_class=AssetClass(str(asset_class)),
                target_weight=float(target),
                min_weight=float(low),
                max_weight=float(high),
            )
            for _, asset_class, target, low, high, _, _ in rows
        )
        return ModelPortfolio(
            model_id=str(rows[0][0]),
            risk_appetite=risk_appetite,
            targets=targets,
            jurisdiction=jurisdiction,
            effective_from=str(rows[0][5]),
            source=str(rows[0][6] or ""),
        )
