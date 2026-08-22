"""Local house-view retrieval adapter (HouseViewRetrievalPort): SQLite FTS5 over CIO views.

The ``local`` profile's stand-in for the **A2 governed KB / File Search**: a ``sqlite3``
database with an **FTS5** virtual table over the CIO house-view articles, queried with
BM25 (``ORDER BY rank``). It is SDK-free, deterministic and **seedable**, so the same code
grounds the offline CLI run and the unit tests. There is no Google emulator for File
Search / Agent Search, so this path is unconditional (no emulator branch).

The adapter returns the same :class:`HouseView` objects (with page-level :class:`Citation`
provenance) as the managed adapter, preserving interface parity. It self-seeds from the
built-in synthetic corpus on first use so an out-of-the-box local run grounds a briefing
without any ingestion step; callers (and tests) may also ``seed(house_views)`` their own.

Default DB path is under a per-package local dir (``~/.cio_advisory/local.db``); tests
pass ``:memory:`` for an ephemeral, deterministic index.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path

from ...config import Settings
from ...domain._grounded import coerce_asset_class, coerce_stance
from ...domain.models import Citation, HouseView, SourceType
from ._seed import SEED_HOUSE_VIEWS

# Default on-disk location for the local index (overridable via settings.local.db_path).
_DEFAULT_DB_DIR = Path.home() / ".cio_advisory"
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "local.db"

# FTS5 query syntax is strict; keep only word characters so a free-text query never trips
# an "fts5: syntax error" (e.g. on punctuation), and OR the terms for recall.
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


class LocalFtsHouseViewAdapter:
    """Retrieve grounded CIO house views from a local SQLite FTS5 index (BM25 ranked)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        db_path = getattr(getattr(settings, "local", None), "db_path", "") or str(_DEFAULT_DB_PATH)
        self._db_path = db_path
        # ``check_same_thread=False`` + an RLock: under ``local serve`` the container is
        # process-wide (deps.get_container is lru_cached) but the sync endpoints run in
        # Starlette's anyio worker threadpool, so retrieve() is called from worker threads
        # other than the one that opened the connection. The reentrant lock serialises every
        # connection access (single-writer) so cross-thread queries do not raise; it is
        # reentrant because seed() nests _insert() under the same guard.
        self._lock = threading.RLock()
        self._conn = self._connect(db_path)
        self._init_schema()
        self._maybe_seed()

    def _maybe_seed(self) -> None:
        """Self-seed the fictional house views so a local run grounds out of the box.

        Never under the ``live`` profile: live derives its themes from real grounded
        research, and a fictional CIO publication must not slip into a real briefing.
        """
        if self._settings.profile != "live" and self._is_empty():
            self.seed(SEED_HOUSE_VIEWS)

    # ------------------------------------------------------------------ #
    # Connection / schema
    # ------------------------------------------------------------------ #
    @staticmethod
    def _connect(db_path: str) -> sqlite3.Connection:
        if db_path not in (":memory:", "") and not db_path.startswith("file:"):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        # One FTS5 table holds the searchable text (theme + rationale); the house-view
        # metadata rides alongside as UNINDEXED columns so a single query returns
        # everything needed to rebuild the HouseView and cite it.
        with self._lock:
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS house_views USING fts5(
                    text,
                    source_id UNINDEXED,
                    theme UNINDEXED,
                    stance UNINDEXED,
                    asset_class UNINDEXED,
                    rationale UNINDEXED,
                    url UNINDEXED,
                    page UNINDEXED,
                    score UNINDEXED
                )
                """
            )
            self._conn.commit()

    def _is_empty(self) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT count(*) AS n FROM house_views").fetchone()
        return int(row["n"]) == 0

    # ------------------------------------------------------------------ #
    # Seeding / ingestion
    # ------------------------------------------------------------------ #
    def seed(self, house_views: tuple[HouseView, ...] | list[HouseView]) -> int:
        """Replace the index contents with ``house_views`` (deterministic test/CLI seed)."""
        with self._lock:
            self._conn.execute("DELETE FROM house_views")
            return self._insert(list(house_views))

    def add(self, house_views: list[HouseView]) -> int:
        """Append ``house_views`` to the index without clearing existing rows."""
        return self._insert(house_views)

    def _insert(self, house_views: list[HouseView]) -> int:
        rows = []
        for hv in house_views:
            c = hv.citation
            page = "" if (c is None or c.page is None) else str(c.page)
            url = c.url if c is not None else ""
            score = c.score if (c is not None and c.score is not None) else 0.9
            # The searchable text is the theme plus rationale so a free-text query matches.
            text = f"{hv.theme}. {hv.rationale}".strip()
            rows.append(
                (
                    text,
                    hv.id,
                    hv.theme,
                    hv.stance.value,
                    hv.asset_class.value,
                    hv.rationale,
                    url,
                    page,
                    f"{float(score):.6f}",
                )
            )
        with self._lock:
            self._conn.executemany(
                "INSERT INTO house_views "
                "(text, source_id, theme, stance, asset_class, rationale, url, page, score) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()
        return len(rows)

    # ------------------------------------------------------------------ #
    # HouseViewRetrievalPort
    # ------------------------------------------------------------------ #
    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, str] | None = None,
    ) -> list[HouseView]:
        """Return ranked CIO house views (with provenance) for ``query``."""
        match = self._build_match(query)
        asset_class = (filters or {}).get("asset_class")

        if not match:
            # No usable query terms: score-ordered scan so the pipeline still gets
            # something deterministic rather than an FTS5 syntax error.
            sql = (
                "SELECT * FROM house_views "
                + ("WHERE asset_class = ? " if asset_class else "")
                + "ORDER BY score DESC LIMIT ?"
            )
            params: list[object] = ([asset_class] if asset_class else []) + [max(top_k, 1)]
        else:
            sql = (
                "SELECT * FROM house_views WHERE house_views MATCH ? "
                + ("AND asset_class = ? " if asset_class else "")
                + "ORDER BY rank LIMIT ?"
            )
            params = [match] + ([asset_class] if asset_class else []) + [max(top_k, 1)]

        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_house_view(row) for row in rows]

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_match(text: str) -> str:
        """Build a safe FTS5 MATCH expression: OR of the alphanumeric query tokens."""
        tokens = _TOKEN_RE.findall(text or "")
        if not tokens:
            return ""
        # Quote each token so reserved words (AND/OR/NOT/NEAR) are treated as literals.
        return " OR ".join(f'"{t}"' for t in tokens)

    @staticmethod
    def _row_to_house_view(row: sqlite3.Row) -> HouseView:
        page_raw = row["page"]
        page = int(page_raw) if page_raw not in (None, "") else None
        try:
            score = float(row["score"])
        except (TypeError, ValueError):
            score = 0.0
        source_id = row["source_id"]
        theme = row["theme"]
        citation = Citation(
            source_id=source_id,
            source_type=SourceType.HOUSE_VIEW,
            title=theme,
            url=row["url"] or "",
            page=page,
            snippet=(row["rationale"] or row["text"] or "")[:240],
            score=score,
        )
        return HouseView(
            id=source_id,
            theme=theme,
            stance=coerce_stance(row["stance"]),
            asset_class=coerce_asset_class(row["asset_class"]),
            rationale=row["rationale"] or "",
            citation=citation,
        )
