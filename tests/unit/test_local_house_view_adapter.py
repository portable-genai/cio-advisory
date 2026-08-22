"""Unit tests for the real local FTS5 house-view adapter (HouseViewRetrievalPort).

These exercise the highest-risk offline retrieval code directly, against the real
``LocalFtsHouseViewAdapter`` (SQLite FTS5, BM25 ``ORDER BY rank``), rather than through the
recording wrapper's whole-corpus convenience path. They cover the branches the pipeline
fixtures do not: a BM25 ``MATCH`` returns the expected ranked subset, FTS5 reserved words
and bare punctuation never raise an ``fts5: syntax error``, the empty-query fallback scan
returns the seeded corpus, and the documented lowercase ``asset_class`` filter narrows
results (the stored value is the enum ``.value``).
"""

from __future__ import annotations

import pytest
from tests.fixtures import sample_clients

from cio_advisory.adapters.local.house_views import LocalFtsHouseViewAdapter
from cio_advisory.config import LocalSettings, Settings
from cio_advisory.domain.models import AssetClass


def _adapter(seed: bool = True) -> LocalFtsHouseViewAdapter:
    settings = Settings(
        profile="local",
        local=LocalSettings(db_path=":memory:", audit_path=":memory:"),
    )
    adapter = LocalFtsHouseViewAdapter(settings)
    if seed:
        adapter.seed(sample_clients.SAMPLE_HOUSE_VIEWS)
    return adapter


def test_match_returns_expected_ranked_subset() -> None:
    # A specific query BM25-matches only the relevant house view, not the whole corpus.
    views = _adapter().retrieve("AI infrastructure", top_k=8)
    assert views, "expected a BM25 match for the AI infrastructure view"
    assert views[0].theme == "AI infrastructure build-out"
    themes = {v.theme for v in views}
    assert "Selective private markets" not in themes, "BM25 must not return unrelated views"
    assert all(v.citation is not None for v in views), "every matched view carries provenance"


def test_reserved_words_do_not_raise() -> None:
    # AND / OR / NEAR are FTS5 operators; the adapter must quote tokens so they are literals.
    views = _adapter().retrieve("AND OR NEAR equity", top_k=8)
    # No fts5 syntax error; the alphanumeric token still matches the equity view.
    assert any(v.asset_class is AssetClass.EQUITY for v in views)


def test_punctuation_only_query_falls_back_to_full_scan() -> None:
    # A query with no alphanumeric tokens yields an empty MATCH: the adapter must take the
    # deterministic score-ordered fallback scan rather than build an invalid MATCH.
    views = _adapter().retrieve("!!! ??? ...", top_k=8)
    assert len(views) == len(sample_clients.SAMPLE_HOUSE_VIEWS)


def test_empty_query_returns_seeded_corpus() -> None:
    views = _adapter().retrieve("", top_k=8)
    assert {v.theme for v in views} == {hv.theme for hv in sample_clients.SAMPLE_HOUSE_VIEWS}


def test_empty_index_returns_nothing() -> None:
    adapter = _adapter(seed=False)
    adapter.seed([])  # explicitly empty the self-seeded built-in corpus
    assert adapter.retrieve("AI infrastructure", top_k=8) == []
    assert adapter.retrieve("", top_k=8) == []


def test_asset_class_filter_uses_lowercase_enum_value() -> None:
    # The stored asset_class is the enum .value (lowercase); the documented filter contract
    # passes that lowercase value and must narrow the result to that class only.
    adapter = _adapter()
    views = adapter.retrieve(
        "infrastructure credit cash markets",
        top_k=8,
        filters={"asset_class": AssetClass.EQUITY.value},
    )
    assert views, "filtered query returned nothing for a present asset class"
    assert all(v.asset_class is AssetClass.EQUITY for v in views)


def test_top_k_slices_under_bm25() -> None:
    # An empty MATCH returns the whole corpus ordered by score; top_k bounds the result.
    views = _adapter().retrieve("", top_k=2)
    assert len(views) == 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
