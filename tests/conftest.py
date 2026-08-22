"""Pytest fixtures: the ``local`` adapters (seeded) + assembled domain services.

The unit suite is driven by the **real** ``local`` adapter family
(``src/cio_advisory/adapters/local``) rather than bespoke in-memory fakes, so the offline
implementation lives in exactly one place and the tests exercise the same code the offline
CLI runs. Every adapter constructs with a single ``Settings`` (the adapter convention)
pointed at ``:memory:`` SQLite, and the house-view index + portfolio store are seeded with
the synthetic ``tests/fixtures/sample_clients`` corpus for determinism.

A few fixtures wrap the local adapter in a thin **recording** subclass that captures call
arguments for assertions (``.calls`` / ``.requests`` / ``.spans`` / ``.events``). These add
no behaviour: every method delegates to the real local adapter, so the in-memory
implementation is still the one under ``adapters/local``. The recorders are the test
instrumentation the previous bespoke fakes used to bundle.

``BlockingGuardrail`` is the single deliberately-different test double kept here: the
advisory pipeline screens the (benign) client id, which the real heuristic guardrail
allows, so the blocked-path tests need a guardrail that force-blocks. It is a thin
subclass of the real ``LocalHeuristicGuardrailAdapter`` that overrides the verdict, so no
fake re-implements the port from scratch.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from cio_advisory.adapters.local.audit import LocalAppendOnlyAuditAdapter
from cio_advisory.adapters.local.evaluation import LocalOfflineEvalAdapter
from cio_advisory.adapters.local.grounding import LocalDisabledGroundingAdapter
from cio_advisory.adapters.local.guardrail import LocalHeuristicGuardrailAdapter
from cio_advisory.adapters.local.house_views import LocalFtsHouseViewAdapter
from cio_advisory.adapters.local.llm import LocalDeterministicLLMAdapter
from cio_advisory.adapters.local.memory import LocalMemoryAdapter
from cio_advisory.adapters.local.portfolio import LocalPortfolioAdapter
from cio_advisory.adapters.local.redaction import LocalRegexRedactionAdapter
from cio_advisory.adapters.local.registry import LocalRegistryAdapter
from cio_advisory.adapters.local.runtime import LocalAgentRuntimeAdapter
from cio_advisory.adapters.local.session import LocalSessionAdapter
from cio_advisory.adapters.local.tool_catalog import LocalToolCatalogAdapter
from cio_advisory.adapters.local.tracer import LocalNoopTracerAdapter
from cio_advisory.config import LocalSettings, Settings
from cio_advisory.domain.models import (
    AuditEvent,
    Direction,
    GuardrailCategory,
    GuardrailFinding,
    GuardrailVerdict,
    HouseView,
    LlmRequest,
    LlmResponse,
)
from tests.fixtures import sample_clients


def _settings() -> Settings:
    """Settings whose local stores are ephemeral in-memory SQLite (deterministic)."""
    return Settings(
        profile="local",
        local=LocalSettings(db_path=":memory:", audit_path=":memory:"),
    )


# --------------------------------------------------------------------------- #
# Recording wrappers : thin subclasses of the local adapters that capture call
# arguments for assertions. Every method delegates to the real local adapter.
# --------------------------------------------------------------------------- #
class RecordingHouseView(LocalFtsHouseViewAdapter):
    """Local FTS5 house-view retrieval seeded with the full governed-KB corpus.

    Construction reuses the real ``LocalFtsHouseViewAdapter`` (the same SQLite FTS5 store
    the CLI runs); the in-memory index is re-seeded with the synthetic corpus. ``retrieve``
    records the call and then **delegates to the real adapter** (``super().retrieve``), so
    the BM25 ``MATCH``, the asset-class filter and the empty-query fallback scan are the code
    under test rather than a Python slice.

    The advisory pipeline's suitability + alignment assertions need every seeded house view
    (the pipeline's free-text query does not BM25-match the alternatives view), so by default
    this recorder forces the deterministic **whole-corpus** path by delegating with an empty
    query: ``super().retrieve("")`` exercises the real adapter's score-ordered fallback scan
    and returns the full seeded set. Set ``full_corpus=False`` to delegate the caller's real
    query straight through to BM25 (used by the focused FTS unit tests below).
    """

    def __init__(
        self,
        settings: Settings,
        house_views: list[HouseView] | None = None,
        full_corpus: bool = True,
    ) -> None:
        super().__init__(settings)
        self._corpus: list[HouseView] = (
            list(sample_clients.SAMPLE_HOUSE_VIEWS) if house_views is None else list(house_views)
        )
        self._full_corpus = full_corpus
        # Keep the underlying FTS5 index in sync so the adapter is still a real local store.
        self.seed(self._corpus)
        self.calls: list[tuple[str, int, dict[str, str]]] = []

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, str] | None = None,
    ) -> list[HouseView]:
        self.calls.append((query, top_k, dict(filters or {})))
        # Delegate to the real local adapter. The empty query drives the adapter's real
        # score-ordered fallback scan (deterministic whole-corpus) the pipeline tests need;
        # full_corpus=False sends the caller's query through the real BM25 MATCH path.
        effective = "" if self._full_corpus else query
        return super().retrieve(effective, top_k, filters)


class RecordingPortfolio(LocalPortfolioAdapter):
    """Local portfolio store that records the client ids it was asked about."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.profile_calls: list[str] = []
        self.portfolio_calls: list[str] = []

    def get_profile(self, client_id: str):  # type: ignore[no-untyped-def]
        self.profile_calls.append(client_id)
        return super().get_profile(client_id)

    def get_portfolio(self, client_id: str):  # type: ignore[no-untyped-def]
        self.portfolio_calls.append(client_id)
        return super().get_portfolio(client_id)


class RecordingLLM(LocalDeterministicLLMAdapter):
    """Local deterministic LLM that records the requests it received."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.requests: list[LlmRequest] = []
        self.classify_calls: list[tuple[str, list[str]]] = []

    def generate(self, request: LlmRequest) -> LlmResponse:
        self.requests.append(request)
        return super().generate(request)

    def classify(self, text: str, labels: list[str]) -> str:
        self.classify_calls.append((text, labels))
        return super().classify(text, labels)


class RecordingRedaction(LocalRegexRedactionAdapter):
    """Local regex redaction that records the raw text it was asked to redact."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.calls: list[str] = []

    def redact(self, text: str):  # type: ignore[no-untyped-def]
        self.calls.append(text)
        return super().redact(text)


class RecordingTracer(LocalNoopTracerAdapter):
    """Local no-op tracer that records the span names it opened."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.spans: list[str] = []

    def span(self, name: str, **attributes: str):  # type: ignore[no-untyped-def]
        self.spans.append(name)
        return super().span(name, **attributes)


class RecordingGuardrail(LocalHeuristicGuardrailAdapter):
    """Local heuristic guardrail that records the (text, direction) screen calls.

    Behaviour is the real heuristic: benign text passes, malicious text (e.g.
    ``sample_clients.MALICIOUS_REQUEST``) is blocked. Only the recording is added.
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.calls: list[tuple[str, Direction]] = []

    def screen(self, text: str, direction: Direction):  # type: ignore[no-untyped-def]
        self.calls.append((text, direction))
        return super().screen(text, direction)


class RecordingAudit(LocalAppendOnlyAuditAdapter):
    """Local append-only audit that also keeps the AuditEvent objects for assertions."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)
        super().record(event)


class BlockingGuardrail(LocalHeuristicGuardrailAdapter):
    """A thin local-guardrail subclass that force-blocks input (and optionally output).

    The advisory pipeline screens the (benign) client id, which the real heuristic
    allows, so the blocked-path tests need a guardrail that blocks deterministically. This
    overrides only the verdict, reusing the real adapter's construction contract; it is the
    one deliberately-different test double the suite keeps.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        block_input: bool = True,
        block_output: bool = False,
    ) -> None:
        super().__init__(settings or _settings())
        self.block_input = block_input
        self.block_output = block_output
        self.calls: list[tuple[str, Direction]] = []

    def screen(self, text: str, direction: Direction) -> GuardrailVerdict:
        self.calls.append((text, direction))
        blocked = (direction is Direction.INPUT and self.block_input) or (
            direction is Direction.OUTPUT and self.block_output
        )
        if not blocked:
            return super().screen(text, direction)
        return GuardrailVerdict(
            allowed=False,
            direction=direction,
            findings=(
                GuardrailFinding(
                    category=GuardrailCategory.PROMPT_INJECTION,
                    confidence="high",
                    detail="prompt injection detected",
                ),
            ),
            sanitized_text=None,
            reason="blocked by guardrail",
        )


# --------------------------------------------------------------------------- #
# Service / policy resolvers : locate the domain classes wherever they live.
# --------------------------------------------------------------------------- #
_SERVICE_MODULE_CANDIDATES = (
    "cio_advisory.domain.advisory_service",
    "cio_advisory.domain.talking_points_service",
    "cio_advisory.domain.services",
)
_POLICY_MODULE_CANDIDATES = (
    "cio_advisory.domain.suitability_policy",
    "cio_advisory.domain.review_policy",
    "cio_advisory.domain.services",
)


def _resolve(symbol: str, candidates: tuple[str, ...]) -> Any:
    last: Exception | None = None
    for mod_name in candidates:
        try:
            module = importlib.import_module(mod_name)
        except ModuleNotFoundError as exc:  # pragma: no cover - layout fallback
            last = exc
            continue
        obj = getattr(module, symbol, None)
        if obj is not None:
            return obj
    raise ImportError(f"Could not locate domain symbol {symbol!r} in any of {candidates}") from last


def load_service(name: str) -> Any:
    return _resolve(name, _SERVICE_MODULE_CANDIDATES)


def load_policy(name: str) -> Any:
    return _resolve(name, _POLICY_MODULE_CANDIDATES)


# --------------------------------------------------------------------------- #
# Pytest fixtures : construct the (seeded) local adapters.
# --------------------------------------------------------------------------- #
@pytest.fixture
def house_view() -> RecordingHouseView:
    return RecordingHouseView(_settings())


@pytest.fixture
def empty_house_view() -> RecordingHouseView:
    return RecordingHouseView(_settings(), house_views=[])


@pytest.fixture
def portfolio() -> RecordingPortfolio:
    return RecordingPortfolio(_settings())


@pytest.fixture
def llm() -> RecordingLLM:
    return RecordingLLM(_settings())


@pytest.fixture
def grounding() -> LocalDisabledGroundingAdapter:
    return LocalDisabledGroundingAdapter(_settings())


@pytest.fixture
def guardrail() -> RecordingGuardrail:
    return RecordingGuardrail(_settings())


@pytest.fixture
def blocking_guardrail() -> BlockingGuardrail:
    return BlockingGuardrail(_settings())


@pytest.fixture
def redaction() -> RecordingRedaction:
    return RecordingRedaction(_settings())


@pytest.fixture
def tracer() -> RecordingTracer:
    return RecordingTracer(_settings())


@pytest.fixture
def audit() -> RecordingAudit:
    return RecordingAudit(_settings())


@pytest.fixture
def session() -> LocalSessionAdapter:
    return LocalSessionAdapter(_settings())


@pytest.fixture
def memory() -> LocalMemoryAdapter:
    return LocalMemoryAdapter(_settings())


@pytest.fixture
def agent_runtime() -> LocalAgentRuntimeAdapter:
    return LocalAgentRuntimeAdapter(_settings())


@pytest.fixture
def evaluation() -> LocalOfflineEvalAdapter:
    return LocalOfflineEvalAdapter(_settings())


@pytest.fixture
def registry() -> LocalRegistryAdapter:
    return LocalRegistryAdapter(_settings())


@pytest.fixture
def tool_catalog() -> LocalToolCatalogAdapter:
    return LocalToolCatalogAdapter(_settings())


# Direction is re-exported for unit tests that import it from the conftest namespace.
__all__ = ["Direction", "BlockingGuardrail", "load_service", "load_policy"]


@pytest.fixture
def advisory_service(house_view, portfolio, llm, guardrail, redaction, tracer, audit):
    """AdvisoryService(house_view, portfolio, llm, guardrail, redaction, tracer, audit)."""
    cls = load_service("AdvisoryService")
    return cls(house_view, portfolio, llm, guardrail, redaction, tracer, audit)
