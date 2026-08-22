"""Concurrency regression tests for the local SQLite-backed adapters.

The API serves sync ``def`` endpoints from Starlette's anyio worker threadpool while
``api/deps.get_container`` is ``@lru_cache`` (one process-wide container, hence one
process-wide SQLite connection per adapter). A request handled on a worker thread other
than the one that opened the connection therefore calls ``record()`` / ``retrieve()`` on a
connection created in a different thread. Without ``check_same_thread=False`` + a lock that
serialises every connection access, SQLite raises::

    SQLite objects created in a thread can only be used in that same thread

which drops the WORM audit event and 500s the endpoint under concurrent ``serve``.

These tests construct each adapter **once** (the lru_cached, process-wide case) and drive
writes and reads from many threads via a ``ThreadPoolExecutor``, asserting that no thread
raises and that the final row count is correct. They FAIL before the fix (the default
``sqlite3.connect`` is thread-bound) and PASS after it.
"""

from __future__ import annotations

import concurrent.futures

from tests.fixtures import sample_clients

from cio_advisory.adapters.local.audit import LocalAppendOnlyAuditAdapter
from cio_advisory.adapters.local.house_views import LocalFtsHouseViewAdapter
from cio_advisory.config import LocalSettings, Settings
from cio_advisory.domain.models import AuditEvent, Decision

_WORKERS = 8
_PER_WORKER = 25


def _settings() -> Settings:
    return Settings(
        profile="local",
        local=LocalSettings(db_path=":memory:", audit_path=":memory:"),
    )


def _drive(fn, count: int) -> None:
    """Run ``fn(i)`` for ``i in range(count)`` across a thread pool, raising any error."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = [pool.submit(fn, i) for i in range(count)]
        for future in concurrent.futures.as_completed(futures):
            future.result()  # re-raises any exception from the worker thread


def test_audit_adapter_is_thread_safe() -> None:
    # One adapter (the process-wide, lru_cached container case) opened on the main thread.
    adapter = LocalAppendOnlyAuditAdapter(_settings())
    total = _WORKERS * _PER_WORKER

    def write_and_read(i: int) -> None:
        adapter.record(
            AuditEvent(
                action="briefing",
                actor=f"rm-{i}",
                decision=Decision.ALLOWED,
                redacted_prompt="redacted",
                redacted_response="redacted",
            )
        )
        # Interleave reads so the read path is exercised cross-thread too.
        adapter.read_all()

    _drive(write_and_read, total)

    # Append-only: every write from every worker thread landed exactly once.
    assert len(adapter.read_all()) == total


def test_house_view_adapter_is_thread_safe() -> None:
    # Seed once on the main thread, then hammer retrieve() (and re-seed) from worker threads.
    adapter = LocalFtsHouseViewAdapter(_settings())
    adapter.seed(sample_clients.SAMPLE_HOUSE_VIEWS)
    expected = len(sample_clients.SAMPLE_HOUSE_VIEWS)

    def query(i: int) -> int:
        if i % 10 == 0:
            # Periodic re-seed exercises the write path concurrently with reads.
            adapter.seed(sample_clients.SAMPLE_HOUSE_VIEWS)
        views = adapter.retrieve("", top_k=expected)
        return len(views)

    with concurrent.futures.ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = [pool.submit(query, i) for i in range(_WORKERS * _PER_WORKER)]
        counts = [f.result() for f in concurrent.futures.as_completed(futures)]

    # No thread raised, and every empty-query scan saw the full seeded corpus.
    assert counts and all(c == expected for c in counts)
    assert len(adapter.retrieve("", top_k=expected)) == expected
