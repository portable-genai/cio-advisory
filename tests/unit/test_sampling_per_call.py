"""Sampling is decided per call: pinned where output is compared, free where it is drafted.

History. The organization front page claims the consequential math is deterministic and
replayable and that the model "never produces the number". On 2026-08-26 that was measured
FALSE in `cdd-sow-research`: two runs of one case minutes apart returned different scores,
because the shared request builder defaulted to `temperature=0.2` and every grounded call
sampled. This file first applied that finding here by pinning the request type's default to 0.0.

What changed (owner decision, 2026-09-23). A default of 0.0 pinned every call, the drafting
ones included, and some models reject a temperature outright. So the default is now `None`,
which SENDS NO TEMPERATURE: the model samples at its own default. A call whose output is
extracted, classified, scored or compared passes `0.0` at the call site; a call that drafts
passes `None`. The shared builder has no default at all, so no call site can inherit a choice
it never made, which was the actual defect in 2026-08.

The call sites, and why:

* `TalkingPointsService.synthesise`: FREE. It drafts the talking-point prose. The suitability
  verdict, the alignment to a computed gap and the citations a point may carry are decided
  deterministically after the call, never read off the model's sampling.
* `GeminiLLMAdapter.classify`: PINNED 0.0. Its output is a label.
* `GeminiGoogleSearchGroundingAdapter.ground`: PINNED 0.0. What is used is the list of citations
  the search returned (retrieval).
* `LiveGroundedHouseViewAdapter._research`: PINNED 0.0. It EXTRACTS structured themes (stance,
  asset class, source) the briefing then computes over.
* The ADK root agent (`agent/root_agent.py`): FREE. It converses; the consequential values come
  back from the deterministic FunctionTools.

**Temperature 0 is not a promise of determinism, and nothing here asserts one.** A hosted model
can still vary across batching and model revisions. It is the strongest thing a caller controls.
"""

from __future__ import annotations

import inspect
import sys
import types as pytypes
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import RecordingLLM
from tests.fixtures import sample_clients

from cio_advisory.adapters.gcp.gemini_grounding import GeminiGoogleSearchGroundingAdapter
from cio_advisory.adapters.gcp.gemini_llm import GeminiLLMAdapter
from cio_advisory.adapters.live.house_views import LiveGroundedHouseViewAdapter
from cio_advisory.config import LiveSettings, Settings
from cio_advisory.domain import _grounded
from cio_advisory.domain.identity import Principal
from cio_advisory.domain.kernel import LlmMessage, LlmRequest

PRINCIPAL = Principal(
    subject="rm@bank.example", principals=("group:cio-analyst",), tenant="demo-bank", source="test"
)


class _Recorded:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.kwargs = kwargs

    @classmethod
    def from_text(cls, text: str) -> _Recorded:
        return cls(text=text)


@pytest.fixture
def fake_genai(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stand-in ``google.genai.types`` so the Gemini adapters run with no SDK installed."""
    fake_types = pytypes.ModuleType("google.genai.types")
    names = ("Content", "Part", "GenerateContentConfig", "ThinkingConfig", "Tool", "GoogleSearch")
    for name in names:
        setattr(fake_types, name, type(name, (_Recorded,), {}))
    fake_types.ThinkingLevel = pytypes.SimpleNamespace(LOW="LOW", HIGH="HIGH")  # type: ignore[attr-defined]
    genai = pytypes.ModuleType("google.genai")
    genai.types = fake_types  # type: ignore[attr-defined]
    google = pytypes.ModuleType("google")
    google.genai = genai  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)


class _FakeClient:
    def __init__(self, text: str = "") -> None:
        self.calls: list[dict[str, Any]] = []
        self.models = self
        self._text = text

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return pytypes.SimpleNamespace(text=self._text, usage_metadata=None, candidates=[])


def _config(client: _FakeClient) -> dict[str, Any]:
    (call,) = client.calls
    return call["config"].kwargs


def test_the_request_type_sends_no_temperature_by_default() -> None:
    """Omitted means free: the adapter sends nothing and the model uses its own default."""
    assert LlmRequest.__dataclass_fields__["temperature"].default is None


def test_the_shared_builder_makes_every_call_site_decide() -> None:
    """No default to inherit: a call site that forgot to choose fails to build a request."""
    parameter = inspect.signature(_grounded.build_llm_request).parameters["temperature"]
    assert parameter.default is inspect.Parameter.empty
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


def test_talking_point_drafting_is_free(advisory_service: Any, llm: RecordingLLM) -> None:
    """The one domain call site drafts prose, so it sends no temperature."""
    advisory_service.brief(sample_clients.BALANCED_CLIENT_ID, PRINCIPAL)
    assert llm.requests, "the service never called the model, so nothing here was tested"
    assert [request.temperature for request in llm.requests] == [None] * len(llm.requests)


def test_the_gemini_adapter_omits_temperature_when_free_and_sends_a_pin(fake_genai: None) -> None:
    messages = (LlmMessage(role="user", content="x"),)
    free = GeminiLLMAdapter(Settings(profile="gcp"))
    free._client = client = _FakeClient("{}")
    free.generate(LlmRequest(messages=messages))
    assert "temperature" not in _config(client), "free must mean ABSENT, never 1.0 or 0.0"

    pinned = GeminiLLMAdapter(Settings(profile="gcp"))
    pinned._client = client = _FakeClient("{}")
    pinned.generate(LlmRequest(messages=messages, temperature=0.0))
    assert _config(client)["temperature"] == 0.0


def test_classification_stays_pinned(fake_genai: None) -> None:
    adapter = GeminiLLMAdapter(Settings(profile="gcp"))
    adapter._client = client = _FakeClient("a")
    adapter.classify("text", ["a", "b"])
    assert _config(client)["temperature"] == 0.0


def test_search_grounding_retrieval_stays_pinned(fake_genai: None) -> None:
    adapter = GeminiGoogleSearchGroundingAdapter(Settings(profile="gcp", grounding_enabled=True))
    adapter._client = client = _FakeClient()
    adapter.ground("rates outlook")
    assert _config(client)["temperature"] == 0.0


def test_live_theme_extraction_stays_pinned(fake_genai: None, tmp_path: Path) -> None:
    settings = Settings(
        profile="live",
        live=LiveSettings(
            research_cache_path=str(tmp_path / "research.json"), research_cache_ttl_seconds=0
        ),
    )
    adapter = LiveGroundedHouseViewAdapter(settings)
    adapter._client = client = _FakeClient('{"themes": []}')
    adapter.retrieve("rates")
    assert _config(client)["temperature"] == 0.0


def test_the_conversational_root_agent_does_not_pin_a_temperature() -> None:
    """Read from source: building the ADK agent needs the SDK this offline suite never has."""
    source = Path("src/cio_advisory/agent/root_agent.py").read_text(encoding="utf-8")
    assert "temperature=" not in source
