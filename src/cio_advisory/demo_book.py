"""The shipped demo book: fictional clients, holdings, instruments and model portfolios.

The rows live as newline-delimited JSON under ``cio_advisory/data/demo_book/``, one file per
BigQuery table and in that table's column order, so one set of files feeds the DuckDB store
the ``local`` and ``live`` profiles read, the loader that fills the managed dataset, and the
fixtures the tests and the eval gate build from. This module is the one reader of those
files: it declares them, checks the invariants a hand edit can break, and builds the domain
objects. It imports the domain, the kit and the standard library only; the DuckDB and
BigQuery adapters call it, it never calls them.

**The reading, the guard and the store come from :mod:`hex_service_kit.demobook` now.** This
repository shipped the pattern first and the kit generalised it a day later, which left the
one repository that most needs the guard with the weakest version of it: without per-table
COLUMN declarations, its contract test could check that a table existed and that the managed
adapter's selected columns were declared, and could not check that the BOOK carries the
columns the schema does. The three kit-based repositories could. That gap is what this
migration closes, and it closes it by deleting code rather than adding any: the NDJSON
reader, the overwrite guard, the date coercion and the DuckDB store were all four
reimplementations of something now written once.

**Two books, deliberately.** :data:`BOOK` is the warehouse: four tables the loader writes to
BigQuery, plus the manifest the kit appends. :data:`CORPUS_BOOK` is the CIO house-view
themes, which are a File Search corpus rather than a table, are read only by the local
grounding index, and must NEVER seed under the ``live`` profile (the 2026-08-30 decision:
what may not enter a live briefing is the EVIDENCE, and a house view is what a talking point
cites). Keeping them in one book would put the corpus in ``load_order()`` and hand the
warehouse loader a table no dataset has.

Everything here is fictional. See ``data/demo_book/README.md``.
"""

from __future__ import annotations

from typing import Any

from hex_service_kit.demobook import BookError, NdjsonBook, Table, as_date, may_overwrite

from .domain.models import (
    AssetClass,
    Citation,
    ClientProfile,
    Holding,
    HouseView,
    Portfolio,
    RiskAppetite,
    SourceType,
    Stance,
)

__all__ = [
    "BOOK",
    "CORPUS_BOOK",
    "CROSS_TENANT",
    "SHIPPED_TENANT",
    "TABLES",
    "BookError",
    "as_date",
    "house_view_rows",
    "manifest",
    "may_overwrite",
    "rows",
    "validate",
]

#: The tenant the shipped rows carry. The deployment loader rewrites it to the tenant the
#: identity adapter there resolves; locally the seeded personas belong to this one.
SHIPPED_TENANT = "demo-bank"

#: No shipped client belongs to a second tenant. The entitlement gate is proved against a
#: REGISTERED client instead (``tests/`` register one under another tenant), so there is
#: nothing here for the loader to keep separate.
CROSS_TENANT: dict[str, str] = {}

_PACKAGE = "cio_advisory.data.demo_book"

INSTRUMENTS = Table(
    name="instruments",
    columns=(
        "instrument_id",
        "name",
        "asset_class",
        "sub_class",
        "region",
        "theme_tags",
        "esg",
        "liquidity",
    ),
    types={
        "instrument_id": "TEXT NOT NULL",
        "name": "TEXT NOT NULL",
        "asset_class": "TEXT NOT NULL",
        "sub_class": "TEXT",
        "region": "TEXT",
        "theme_tags": "TEXT[]",
        "esg": "BOOLEAN",
        "liquidity": "TEXT",
    },
    primary_key=("instrument_id",),
)

MODEL_PORTFOLIOS = Table(
    name="model_portfolios",
    columns=(
        "model_id",
        "risk_appetite",
        "jurisdiction",
        "asset_class",
        "target_weight",
        "min_weight",
        "max_weight",
        "effective_from",
        "source",
    ),
    types={
        "model_id": "TEXT NOT NULL",
        "risk_appetite": "TEXT NOT NULL",
        "jurisdiction": "TEXT",
        "asset_class": "TEXT NOT NULL",
        "target_weight": "DOUBLE NOT NULL",
        "min_weight": "DOUBLE NOT NULL",
        "max_weight": "DOUBLE NOT NULL",
        "effective_from": "DATE NOT NULL",
        "source": "TEXT",
    },
    primary_key=("model_id", "asset_class"),
    date_columns=frozenset({"effective_from"}),
)

CLIENT_PROFILES = Table(
    name="client_profiles",
    columns=(
        "client_id",
        "tenant",
        "risk_appetite",
        "objectives",
        "knowledge_experience",
        "constraints",
        "jurisdiction",
        "currency",
        "segment",
        "time_horizon_years",
        "last_review_date",
        "as_of_date",
    ),
    types={
        "client_id": "TEXT NOT NULL",
        "tenant": "TEXT NOT NULL",
        "risk_appetite": "TEXT NOT NULL",
        "objectives": "TEXT[]",
        "knowledge_experience": "TEXT",
        "constraints": "TEXT[]",
        "jurisdiction": "TEXT",
        "currency": "TEXT",
        "segment": "TEXT",
        "time_horizon_years": "BIGINT",
        "last_review_date": "DATE",
        "as_of_date": "DATE NOT NULL",
    },
    primary_key=("client_id",),
    date_columns=frozenset({"last_review_date", "as_of_date"}),
)

HOLDINGS = Table(
    name="holdings",
    columns=(
        "client_id",
        "instrument_id",
        "line_no",
        "value",
        "weight",
        "currency",
        "as_of_date",
    ),
    types={
        "client_id": "TEXT NOT NULL",
        "instrument_id": "TEXT NOT NULL",
        "line_no": "BIGINT NOT NULL",
        "value": "DOUBLE NOT NULL",
        "weight": "DOUBLE NOT NULL",
        "currency": "TEXT",
        "as_of_date": "DATE NOT NULL",
    },
    primary_key=("client_id", "instrument_id"),
    date_columns=frozenset({"as_of_date"}),
)

#: The CIO house-view themes. A corpus, not a warehouse table: see the module docstring.
HOUSE_VIEWS = Table(
    name="house_views",
    columns=("view_id", "theme", "asset_class", "stance", "rationale", "as_of_date", "horizon"),
    types={
        "view_id": "TEXT NOT NULL",
        "theme": "TEXT NOT NULL",
        "asset_class": "TEXT NOT NULL",
        "stance": "TEXT NOT NULL",
        "rationale": "TEXT NOT NULL",
        "as_of_date": "DATE NOT NULL",
        "horizon": "TEXT",
    },
    primary_key=("view_id",),
    date_columns=frozenset({"as_of_date"}),
)

#: The warehouse tables, in LOAD order: a referenced table before the rows referencing it.
#: ``book_manifest`` is NOT here. The kit keeps it out and appends it in ``load_order()``,
#: because it records the load that wrote the others, and the set to hold against the
#: Terraform is the set the LOADER writes.
TABLES: tuple[Table, ...] = (INSTRUMENTS, MODEL_PORTFOLIOS, CLIENT_PROFILES, HOLDINGS)

BOOK = NdjsonBook(_PACKAGE, TABLES)

#: The corpus half. Never loaded to a warehouse, never seeded under ``live``.
CORPUS_BOOK = NdjsonBook(_PACKAGE, (HOUSE_VIEWS,))


def rows(table: str) -> list[dict[str, Any]]:
    """The rows of one shipped table, as parsed JSON objects in file order."""
    book = CORPUS_BOOK if table == HOUSE_VIEWS.name else BOOK
    return book.rows(table)


def house_view_rows() -> list[dict[str, Any]]:
    """The CIO house-view themes the ``local`` FTS index self-seeds from."""
    return CORPUS_BOOK.rows(HOUSE_VIEWS.name)


def manifest() -> dict[str, Any]:
    """The single manifest row: version, as-of date, ``fictional``."""
    return BOOK.manifest()


# --------------------------------------------------------------------------- #
# Invariants
# --------------------------------------------------------------------------- #
def validate() -> None:
    """Raise :class:`BookError` on the first invariant a hand edit broke.

    The kit checks the SHAPE first (every row declares only columns the table has, and the
    manifest says the book is fictional). What is here is this book's own arithmetic, which a
    hand edit breaks silently: weights per client sum to one; every holding names a shipped
    instrument; every client holds something; each model portfolio's targets sum to one with
    each target inside its band. Called by the DuckDB store before it seeds and by the loader
    before it writes, so a broken book is refused rather than served.
    """
    BOOK.validate()
    instruments = {r["instrument_id"] for r in rows("instruments")}
    by_client: dict[str, float] = {}
    for r in rows("holdings"):
        if r["instrument_id"] not in instruments:
            raise BookError(
                f"holding for {r['client_id']} names unknown instrument {r['instrument_id']!r}"
            )
        by_client[r["client_id"]] = by_client.get(r["client_id"], 0.0) + float(r["weight"])
    profiles = {r["client_id"] for r in rows("client_profiles")}
    for client_id in sorted(profiles):
        total = by_client.get(client_id)
        if total is None:
            raise BookError(f"{client_id} has a profile and no holdings")
        if abs(total - 1.0) > 1e-6:
            raise BookError(f"{client_id} holdings weigh {total:.6f}, not 1.0")
    orphans = sorted(set(by_client) - profiles)
    if orphans:
        raise BookError(f"holdings without a profile: {orphans}")
    for r in rows("client_profiles"):
        if not str(r.get("tenant") or "").strip():
            raise BookError(f"{r['client_id']} has no tenant; an owner-less client fails closed")
    targets: dict[str, float] = {}
    for r in rows("model_portfolios"):
        lo, target, hi = float(r["min_weight"]), float(r["target_weight"]), float(r["max_weight"])
        if not lo <= target <= hi:
            raise BookError(
                f"{r['model_id']} {r['asset_class']}: target {target} outside band [{lo}, {hi}]"
            )
        targets[r["model_id"]] = targets.get(r["model_id"], 0.0) + target
    for model_id, total in sorted(targets.items()):
        if abs(total - 1.0) > 1e-6:
            raise BookError(f"model portfolio {model_id} targets weigh {total:.6f}, not 1.0")
    if manifest().get("fictional") is not True:
        raise BookError("book_manifest must state fictional: true")


# --------------------------------------------------------------------------- #
# Domain objects
# --------------------------------------------------------------------------- #
def profiles() -> dict[str, ClientProfile]:
    """Every shipped client profile by id, tenant stamped from the row."""
    out: dict[str, ClientProfile] = {}
    for r in rows("client_profiles"):
        out[r["client_id"]] = ClientProfile(
            id=str(r["client_id"]),
            risk_appetite=RiskAppetite(str(r["risk_appetite"])),
            objectives=tuple(str(o) for o in r.get("objectives") or ()),
            knowledge_experience=str(r.get("knowledge_experience") or "informed"),
            constraints=tuple(str(c) for c in r.get("constraints") or ()),
            jurisdiction=str(r.get("jurisdiction") or "SG"),
            tenant=str(r.get("tenant") or ""),
        )
    return out


def portfolios() -> dict[str, Portfolio]:
    """Every shipped portfolio by client id, holdings in statement-line order."""
    instruments = {r["instrument_id"]: r for r in rows("instruments")}
    currencies = {r["client_id"]: str(r.get("currency") or "USD") for r in rows("client_profiles")}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows("holdings"):
        grouped.setdefault(r["client_id"], []).append(r)
    out: dict[str, Portfolio] = {}
    for client_id, lines in grouped.items():
        holdings = tuple(
            Holding(
                instrument=str(instruments[r["instrument_id"]]["name"]),
                asset_class=AssetClass(str(instruments[r["instrument_id"]]["asset_class"])),
                value=float(r["value"]),
                weight=float(r["weight"]),
                currency=str(r.get("currency") or currencies.get(client_id, "USD")),
                instrument_id=str(r["instrument_id"]),
                tags=tuple(str(t) for t in instruments[r["instrument_id"]].get("theme_tags") or ()),
            )
            for r in sorted(lines, key=lambda row: int(row["line_no"]))
        )
        out[client_id] = Portfolio(
            client_id=client_id,
            holdings=holdings,
            total_value=sum(h.value for h in holdings),
            currency=currencies.get(client_id, "USD"),
        )
    return out


def house_views() -> tuple[HouseView, ...]:
    """The shipped CIO house views with their fictional citations."""
    out: list[HouseView] = []
    for r in house_view_rows():
        source_id = str(r["id"])
        theme = str(r["theme"])
        out.append(
            HouseView(
                id=source_id,
                theme=theme,
                stance=Stance(str(r["stance"])),
                asset_class=AssetClass(str(r["asset_class"])),
                rationale=str(r.get("rationale") or ""),
                tags=tuple(str(t) for t in r.get("tags") or ()),
                citation=Citation(
                    source_id=source_id,
                    source_type=SourceType.HOUSE_VIEW,
                    title=theme,
                    url=str(r.get("url") or ""),
                    page=int(r["page"]) if r.get("page") is not None else None,
                    snippet=str(r.get("snippet") or ""),
                    score=float(r["score"]) if r.get("score") is not None else None,
                ),
            )
        )
    return tuple(out)


# --------------------------------------------------------------------------- #
# The overwrite guard and the date coercion used to live here
# --------------------------------------------------------------------------- #
# Both are re-exported from `hex_service_kit.demobook` at the top of this module rather than
# implemented again. They were written here first and generalised into the kit a day later,
# and two implementations of "may a demo loader truncate this store" is one that eventually
# says yes in the place that matters. The callers (the DuckDB store, the managed loader) are
# unchanged: they still call `demo_book.may_overwrite` and `demo_book.as_date`.
