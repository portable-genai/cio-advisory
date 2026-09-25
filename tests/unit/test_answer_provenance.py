"""The service half of the model pills: which model ANSWERED, and whether it searched.

The console shows two pills at the top right: the model that answered the last request, and
``Search`` when that answer used an online search tool (owner decision, 2026-09-23). Both come
from response headers the kit emits (``install_answer_provenance`` in ``api/app.py``) for
whatever the model adapters NOTED as they called. Before a request is answered the pill shows
``generator_model`` from ``/healthz``, so that value must be the model the bound adapter calls,
never one a configuration flag names while the adapter calls another.

The console calls this service cross-origin, so both headers must also be listed in the CORS
``Access-Control-Expose-Headers``: a browser hides every header a cross-origin script was not
told it may read, and the pills would then stay on the configured model forever.

No cloud SDK is installed here. The Gemini adapters import ``google.genai`` lazily, so a small
stand-in module is put in ``sys.modules`` for the duration of a test and the adapter's own
``_client`` is replaced by a fake that records what it was asked to call.
"""

from __future__ import annotations

import dataclasses
import sys
import types as pytypes
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hex_service_kit import provenance
from tests.conftest import (
    RecordingAudit,
    RecordingGuardrail,
    RecordingHouseView,
    RecordingLLM,
    RecordingPortfolio,
    RecordingRedaction,
    RecordingTracer,
)

from cio_advisory.adapters.gcp.gemini_grounding import GeminiGoogleSearchGroundingAdapter
from cio_advisory.adapters.gcp.gemini_llm import GeminiLLMAdapter
from cio_advisory.adapters.live.house_views import LiveGroundedHouseViewAdapter
from cio_advisory.api import deps
from cio_advisory.api.app import app
from cio_advisory.config import (
    OFFLINE_STUB_MODEL,
    LiveSettings,
    LocalSettings,
    ModelSettings,
    Settings,
)
from cio_advisory.domain.kernel import LlmMessage, LlmRequest
from cio_advisory.domain.services import AdvisoryService

ANSWERED_BY = "x-answered-by"
SEARCH_USED = "x-search-used"
EXPOSE = "access-control-expose-headers"

_CLIENT = "client-000042"  # seeded, owned by tenant demo-bank, which the analyst persona is in
_ALLOWED_ORIGIN = "http://localhost:3000"  # the console's own dev origin, on the CORS allowlist


# --------------------------------------------------------------------------- #
# A stand-in for google.genai: just enough surface for the three adapters
# --------------------------------------------------------------------------- #
class _Recorded:
    """Any SDK value type: keeps its constructor arguments so a test can read them back."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs


class _Part(_Recorded):
    @classmethod
    def from_text(cls, text: str) -> _Part:
        return cls(text=text)


def _fake_types() -> pytypes.ModuleType:
    module = pytypes.ModuleType("google.genai.types")
    for name in ("Content", "GenerateContentConfig", "ThinkingConfig", "Tool", "GoogleSearch"):
        setattr(module, name, type(name, (_Recorded,), {}))
    module.Part = _Part  # type: ignore[attr-defined]
    module.ThinkingLevel = pytypes.SimpleNamespace(LOW="LOW", HIGH="HIGH")  # type: ignore[attr-defined]
    return module


@pytest.fixture
def fake_genai(monkeypatch: pytest.MonkeyPatch) -> pytypes.ModuleType:
    """Install a stand-in ``google.genai.types`` for one test; the real SDK is never needed."""
    fake_types = _fake_types()
    genai = pytypes.ModuleType("google.genai")
    genai.types = fake_types  # type: ignore[attr-defined]
    google = pytypes.ModuleType("google")
    google.genai = genai  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)
    return fake_types


class _FakeModels:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return pytypes.SimpleNamespace(text=self.text, usage_metadata=None, candidates=[])


class _FakeClient:
    def __init__(self, text: str = "") -> None:
        self.models = _FakeModels(text)


@pytest.fixture
def noted() -> Iterator[provenance.AnswerProvenance]:
    """One provenance record, as the middleware opens per request."""
    with provenance.scope() as record:
        yield record


# --------------------------------------------------------------------------- #
# The real app, answering through the local profile
# --------------------------------------------------------------------------- #
def _local_settings(**overrides: Any) -> Settings:
    return Settings(
        profile="local",
        local=LocalSettings(db_path=":memory:", audit_path=":memory:", book_path=":memory:"),
        **overrides,
    )


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """The real app under ``local``; ``bind(house_view=...)`` swaps the service's retrieval."""
    monkeypatch.setenv("CIO_PROFILE", "local")
    monkeypatch.setenv("CIO_LOCAL_DB", ":memory:")
    monkeypatch.setenv("CIO_LOCAL_AUDIT", ":memory:")
    monkeypatch.setenv("CIO_LOCAL_BOOK", ":memory:")
    deps.get_container.cache_clear()
    settings = _local_settings()

    def bind(house_view: Any = None) -> TestClient:
        service = AdvisoryService(
            house_view=house_view or RecordingHouseView(settings),
            portfolio=RecordingPortfolio(settings),
            llm=RecordingLLM(settings),
            guardrail=RecordingGuardrail(settings),
            redaction=RecordingRedaction(settings),
            tracer=RecordingTracer(settings),
            audit=RecordingAudit(settings),
        )
        app.dependency_overrides[deps.get_advisory_service] = lambda: service
        return TestClient(app, client=("127.0.0.1", 50000))

    yield bind
    app.dependency_overrides.clear()
    deps.get_container.cache_clear()


def _briefing(client: TestClient, **headers: str) -> Any:
    response = client.post(
        "/v1/briefing",
        json={"client_id": _CLIENT},
        headers={"X-Dev-Persona": "analyst", **headers},
    )
    assert response.status_code == 200, response.text
    return response


def test_a_local_answer_names_the_offline_stub_that_generator_model_reports(api: Any) -> None:
    """The pill must not change name when the first answer lands: one spelling, both places."""
    response = _briefing(api())
    assert response.headers[ANSWERED_BY] == OFFLINE_STUB_MODEL
    assert SEARCH_USED not in response.headers
    bindings = Settings.load("config/settings.yaml").adapters
    assert _local_settings(adapters=bindings).generator_model == OFFLINE_STUB_MODEL


def test_a_route_that_calls_no_model_names_none(api: Any) -> None:
    """Nothing noted, nothing sent: the pill never invents a model nobody called."""
    client = api()
    for response in (
        client.get("/healthz"),
        client.get(f"/v1/clients/{_CLIENT}/portfolio", headers={"X-Dev-Persona": "analyst"}),
    ):
        assert response.status_code == 200, response.text
        assert ANSWERED_BY not in response.headers
        assert SEARCH_USED not in response.headers


def test_grounded_research_on_the_briefing_route_shows_search(
    api: Any, fake_genai: pytypes.ModuleType, tmp_path: Path
) -> None:
    """The live profile's house views come from a google_search grounded call: Search shows.

    The real live adapter runs its real research code against a faked client; the briefing is
    then drafted by the offline stub. Both models answered this one request, in call order.
    """
    themes = (
        '{"themes": [{"theme": "Quality income", "stance": "overweight", '
        '"asset_class": "fixed_income", "rationale": "Yields remain attractive.", '
        '"source_title": "Outlook", "source_url": "https://research.example/outlook"}]}'
    )
    live = LiveGroundedHouseViewAdapter(
        _local_settings(
            live=LiveSettings(
                research_cache_path=str(tmp_path / "research.json"),
                research_cache_ttl_seconds=0,
            )
        )
    )
    fake = _FakeClient(themes)
    live._client = fake

    response = _briefing(api(house_view=live))

    assert fake.models.calls, "the research call never ran, so nothing here was tested"
    assert response.headers[SEARCH_USED] == "true"
    assert response.headers[ANSWERED_BY] == f"gemini-3.5-flash, {OFFLINE_STUB_MODEL}"
    # The next request is a fresh record: a search never leaks into a later response.
    assert SEARCH_USED not in _briefing(api()).headers


def test_the_cross_origin_console_may_read_both_headers(api: Any) -> None:
    """A header the CORS response does not expose is invisible to the console's fetch."""
    response = _briefing(api(), Origin=_ALLOWED_ORIGIN)
    assert response.headers.get("access-control-allow-origin") == _ALLOWED_ORIGIN
    exposed = {
        name.strip().lower()
        for value in response.headers.get_list(EXPOSE)
        for name in value.split(",")
    }
    assert {ANSWERED_BY, SEARCH_USED} <= exposed, exposed


# --------------------------------------------------------------------------- #
# The Gemini adapters note what they called
# --------------------------------------------------------------------------- #
def _request(**overrides: Any) -> LlmRequest:
    return LlmRequest(messages=(LlmMessage(role="user", content="x"),), **overrides)


def test_the_gemini_adapter_notes_the_model_it_called(
    fake_genai: pytypes.ModuleType, noted: provenance.AnswerProvenance
) -> None:
    settings = Settings(profile="gcp", models=ModelSettings(reasoning="model-it-calls"))
    adapter = GeminiLLMAdapter(settings)
    fake = _FakeClient("{}")
    adapter._client = fake

    adapter.generate(_request())
    adapter.generate(_request(model="explicit-model"))

    assert [call["model"] for call in fake.models.calls] == ["model-it-calls", "explicit-model"]
    assert noted.models == ["model-it-calls", "explicit-model"]
    assert noted.search_used is False, "no search tool was attached, so Search must not show"


def test_the_gemini_classifier_notes_the_triage_model(
    fake_genai: pytypes.ModuleType, noted: provenance.AnswerProvenance
) -> None:
    settings = Settings(profile="gcp", models=ModelSettings(triage="triage-model"))
    adapter = GeminiLLMAdapter(settings)
    adapter._client = _FakeClient("b")

    assert adapter.classify("text", ["a", "b"]) == "b"
    assert noted.models == ["triage-model"]
    assert noted.search_used is False


def test_the_google_search_grounding_adapter_notes_model_and_search(
    fake_genai: pytypes.ModuleType, noted: provenance.AnswerProvenance
) -> None:
    settings = Settings(
        profile="gcp", grounding_enabled=True, models=ModelSettings(triage="search-model")
    )
    adapter = GeminiGoogleSearchGroundingAdapter(settings)
    fake = _FakeClient()
    adapter._client = fake

    adapter.ground("rates outlook")

    (call,) = fake.models.calls
    tools = call["config"].kwargs["tools"]
    assert tools and "google_search" in tools[0].kwargs, "the search tool was not attached"
    assert noted.models == ["search-model"]
    assert noted.search_used is True


def test_disabled_grounding_calls_nothing_and_notes_nothing(
    noted: provenance.AnswerProvenance,
) -> None:
    adapter = GeminiGoogleSearchGroundingAdapter(Settings(profile="gcp", grounding_enabled=False))
    assert adapter.ground("rates outlook") == []
    assert noted.models == [] and noted.search_used is False


# --------------------------------------------------------------------------- #
# generator_model is the model the adapter calls, and the flag that broke that is gone
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("profile", ["gcp", "platform", "live"])
def test_generator_model_is_the_model_the_bound_gemini_adapter_calls(
    fake_genai: pytypes.ModuleType, noted: provenance.AnswerProvenance, profile: str
) -> None:
    base = Settings.load("config/settings.yaml")
    settings = dataclasses.replace(
        base, profile=profile, models=ModelSettings(reasoning="the-model-the-adapter-calls")
    )
    adapter = GeminiLLMAdapter(settings)
    adapter._client = _FakeClient("{}")
    adapter.generate(_request())  # no explicit model: the adapter's own default

    assert noted.models == [settings.generator_model] == ["the-model-the-adapter-calls"]


def test_the_hard_reasoning_flag_does_not_exist() -> None:
    """The latent false banner: a flag that moved the pill but not the model that answered.

    ``generator_model`` once named ``models.hard_reasoning`` when ``models.use_hard_reasoning``
    was set, while the Gemini adapter called ``request.model or models.reasoning`` and never
    read the flag. The pill would then have named a model that never answered.
    """
    fields = {f.name for f in dataclasses.fields(ModelSettings)}
    assert "use_hard_reasoning" not in fields and "hard_reasoning" not in fields
    root = Path(".")
    for source in [root / "config" / "settings.yaml", *sorted((root / "src").rglob("*.py"))]:
        assert "hard_reasoning" not in source.read_text(encoding="utf-8"), source
