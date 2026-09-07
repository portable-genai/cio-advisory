"""The shipped demo book: fictional clients, holdings, instruments and model portfolios.

The rows live as newline-delimited JSON under ``cio_advisory/data/demo_book/``, one file per
BigQuery table and in that table's column order, so one set of files feeds the DuckDB store
the ``local`` and ``live`` profiles read, the loader that fills the managed dataset, and the
fixtures the tests and the eval gate build from. This module is the one reader of those
files: it parses them, checks the invariants a hand edit can break, and builds the domain
objects. It imports the domain and the standard library only; the DuckDB and BigQuery
adapters call it, it never calls them.

Everything here is fictional. See ``data/demo_book/README.md``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date
from importlib import resources
from typing import Any

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

#: The tables the book ships, in load order: referenced tables before the rows that
#: reference them. ``book_manifest`` is last because its ``loaded_at`` is stamped by the
#: loader that wrote the others.
TABLES: tuple[str, ...] = (
    "instruments",
    "model_portfolios",
    "client_profiles",
    "holdings",
    "book_manifest",
)

#: The tenant the shipped rows carry. The deployment loader rewrites it to the tenant the
#: identity adapter there resolves; locally the seeded personas belong to this one.
SHIPPED_TENANT = "demo-bank"

_PACKAGE = "cio_advisory.data.demo_book"


class BookError(ValueError):
    """The shipped book violates one of its own invariants."""


# --------------------------------------------------------------------------- #
# Raw rows
# --------------------------------------------------------------------------- #
def rows(table: str) -> list[dict[str, Any]]:
    """The rows of one shipped table, as parsed JSON objects in file order."""
    text = (resources.files(_PACKAGE) / f"{table}.ndjson").read_text(encoding="utf-8")
    out: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        parsed = json.loads(line)
        if not isinstance(parsed, dict):
            raise BookError(f"{table}.ndjson line {number}: not a JSON object")
        out.append(parsed)
    return out


def house_view_rows() -> list[dict[str, Any]]:
    """The CIO house-view themes the ``local`` FTS index self-seeds from."""
    return rows("house_views")


def manifest() -> dict[str, Any]:
    """The single manifest row: version, as-of date, ``fictional``."""
    found = rows("book_manifest")
    if len(found) != 1:
        raise BookError(f"book_manifest.ndjson must hold exactly one row, found {len(found)}")
    return found[0]


# --------------------------------------------------------------------------- #
# Invariants
# --------------------------------------------------------------------------- #
def validate() -> None:
    """Raise :class:`BookError` on the first invariant a hand edit broke.

    Weights per client sum to one; every holding names a shipped instrument; every client
    holds something; each model portfolio's targets sum to one with each target inside its
    band; the manifest says the book is fictional. Called by the DuckDB store before it
    seeds and by the loader before it writes, so a broken book is refused rather than served.
    """
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
# The overwrite guard the loader and the DuckDB store share
# --------------------------------------------------------------------------- #
def may_overwrite(row_counts: dict[str, int], manifest_rows: Iterable[dict[str, Any]]) -> bool:
    """Whether a store holding ``row_counts`` may be truncated and reloaded with this book.

    True when every table is empty, or when the store's own manifest says what it holds is
    fictional. False otherwise: a table with rows and no fictional manifest is somebody's
    book, and a demo loader must never be the thing that truncates it.
    """
    if all(count == 0 for count in row_counts.values()):
        return True
    return any(row.get("fictional") is True for row in manifest_rows)


def as_date(value: Any) -> date | None:
    """Coerce a shipped ISO date string (or ``None``) to a :class:`date`."""
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
