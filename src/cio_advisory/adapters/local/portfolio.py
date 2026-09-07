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

import duckdb

from ... import demo_book
from ...config import Settings
from ...domain.models import AssetClass, ClientProfile, Holding, Portfolio, RiskAppetite

#: Default on-disk location for the laptop book (overridable via settings.local.book_path).
_DEFAULT_BOOK_PATH = Path.home() / ".cio_advisory" / "book.duckdb"

#: The tables, in the column order the BigQuery schema declares them. One DDL statement per
#: table so a column added to the managed schema is added here in the same shape.
_SCHEMA: tuple[tuple[str, str], ...] = (
    (
        "instruments",
        """
        instrument_id TEXT PRIMARY KEY,
        name          TEXT NOT NULL,
        asset_class   TEXT NOT NULL,
        sub_class     TEXT,
        region        TEXT,
        theme_tags    TEXT[],
        esg           BOOLEAN,
        liquidity     TEXT
        """,
    ),
    (
        "model_portfolios",
        """
        model_id       TEXT NOT NULL,
        risk_appetite  TEXT NOT NULL,
        jurisdiction   TEXT,
        asset_class    TEXT NOT NULL,
        target_weight  DOUBLE NOT NULL,
        min_weight     DOUBLE NOT NULL,
        max_weight     DOUBLE NOT NULL,
        effective_from DATE NOT NULL,
        source         TEXT,
        PRIMARY KEY (model_id, asset_class)
        """,
    ),
    (
        "client_profiles",
        """
        client_id            TEXT PRIMARY KEY,
        tenant               TEXT NOT NULL,
        risk_appetite        TEXT NOT NULL,
        objectives           TEXT[],
        knowledge_experience TEXT,
        constraints          TEXT[],
        jurisdiction         TEXT,
        currency             TEXT,
        segment              TEXT,
        time_horizon_years   BIGINT,
        last_review_date     DATE,
        as_of_date           DATE NOT NULL
        """,
    ),
    (
        "holdings",
        """
        client_id     TEXT NOT NULL,
        instrument_id TEXT NOT NULL,
        line_no       BIGINT NOT NULL,
        value         DOUBLE NOT NULL,
        weight        DOUBLE NOT NULL,
        currency      TEXT,
        as_of_date    DATE NOT NULL,
        PRIMARY KEY (client_id, instrument_id)
        """,
    ),
    (
        "book_manifest",
        """
        book_version  TEXT NOT NULL,
        as_of_date    DATE NOT NULL,
        fictional     BOOLEAN NOT NULL,
        loaded_at     TIMESTAMP,
        source_commit TEXT,
        tenant        TEXT NOT NULL
        """,
    ),
)

#: Column order per table, derived from the DDL above so the two cannot disagree.
_COLUMNS: dict[str, tuple[str, ...]] = {
    table: tuple(
        line.split()[0]
        for line in (raw.strip() for raw in ddl.strip().splitlines())
        if line and not line.upper().startswith("PRIMARY KEY")
    )
    for table, ddl in _SCHEMA
}

_DATE_COLUMNS = frozenset({"as_of_date", "last_review_date", "effective_from"})


class LocalPortfolioAdapter:
    """Serve client profiles and portfolios from the laptop's DuckDB book."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        path = getattr(getattr(settings, "local", None), "book_path", "") or str(_DEFAULT_BOOK_PATH)
        self._path = path
        self._conn = self._connect(path)
        self._init_schema()
        self._maybe_seed()

    # ------------------------------------------------------------------ #
    # Connection / schema / seeding
    # ------------------------------------------------------------------ #
    @staticmethod
    def _connect(path: str) -> duckdb.DuckDBPyConnection:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        return duckdb.connect(path)

    def _init_schema(self) -> None:
        for table, ddl in _SCHEMA:
            self._conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({ddl})")

    def _scalar(self, sql: str) -> Any:
        """The first column of the first row, or ``None`` when the query returned none."""
        row = self._conn.execute(sql).fetchone()
        return None if row is None else row[0]

    def _row_counts(self) -> dict[str, int]:
        return {
            table: int(self._scalar(f"SELECT count(*) FROM {table}") or 0) for table, _ in _SCHEMA
        }

    def _manifest_rows(self) -> list[dict[str, Any]]:
        return [
            dict(zip(_COLUMNS["book_manifest"], row, strict=True))
            for row in self._conn.execute("SELECT * FROM book_manifest").fetchall()
        ]

    def _maybe_seed(self) -> None:
        """Insert the shipped book when this store holds nothing at all, and never otherwise.

        Seeds under every laptop profile including ``live``: the fictional CLIENTS are the
        subject of a briefing, not the evidence it cites, and the console labels them. The
        fictional house views are a different matter and stay out of ``live`` entirely.

        A store that already holds rows is left exactly as it is, whoever wrote them. That
        matters for a demo as much as for a real book: re-seeding on every open would discard
        the clients an audience registered in an earlier run of the same demo.
        """
        if all(count == 0 for count in self._row_counts().values()):
            self.seed_shipped_book()

    def seed_shipped_book(self) -> None:
        """Replace this store's contents with the shipped demo book.

        Refuses a populated store whose manifest does not declare it fictional, which is the
        same guard, in the same function, that the managed loader runs before it truncates a
        BigQuery dataset. One rule proved in one place, called from two.
        """
        demo_book.validate()
        counts = self._row_counts()
        if not demo_book.may_overwrite(counts, self._manifest_rows()):
            held = ", ".join(f"{table}={count}" for table, count in sorted(counts.items()) if count)
            raise PermissionError(
                f"refusing to seed {self._path}: it holds rows ({held}) and its manifest does "
                "not say they are fictional"
            )
        for table, _ in reversed(_SCHEMA):
            self._conn.execute(f"DELETE FROM {table}")
        for table, _ in _SCHEMA:
            self._insert(table, demo_book.rows(table))

    def _insert(self, table: str, rows: list[dict[str, Any]]) -> None:
        columns = _COLUMNS[table]
        placeholders = ", ".join("?" for _ in columns)
        values = [
            [
                demo_book.as_date(row.get(column)) if column in _DATE_COLUMNS else row.get(column)
                for column in columns
            ]
            for row in rows
        ]
        if values:
            self._conn.executemany(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})", values
            )

    def close(self) -> None:
        """Close the DuckDB connection (the CLI and tests reopen the same file)."""
        self._conn.close()

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
            "SELECT i.name, i.asset_class, h.value, h.weight, h.currency "
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
            )
            for name, asset_class, value, weight, currency in rows
        )
        return Portfolio(
            client_id=client_id,
            holdings=holdings,
            total_value=sum(h.value for h in holdings),
            currency=holdings[0].currency,
        )
