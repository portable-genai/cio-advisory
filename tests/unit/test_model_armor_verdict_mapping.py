"""The Model Armor adapter blocks on a match, and fails closed on no verdict or an API error.

``FilterMatchState`` is a proto-plus ``IntEnum``. On Python 3.11+
``str(FilterMatchState.MATCH_FOUND)`` is ``'2'``, so a mapping that searched the ``str()``
for ``"MATCH_FOUND"`` allowed every flagged prompt through, and a stub that carried the state
as a plain string kept its test green.

This module tests at two levels:

* **SDK-free** (always runs, including the offline gate's SDK-free ``make check``): the
  mapping is fed ``_MirrorState``, a stdlib ``IntEnum`` with the real member names and
  numbers. It has the same ``str()`` behaviour that hid the bug.
* **Real SDK** (runs where ``google-cloud-modelarmor`` is installed, skips on the SDK-free
  local profile): responses are built from the real ``modelarmor_v1`` types and screened
  through ``screen()`` with a fake client, so nothing touches the network. The first of
  these tests also pins the mirror to the real enum, so the SDK-free half cannot drift.
"""

from __future__ import annotations

import enum
from types import SimpleNamespace
from typing import Any

import pytest

from cio_advisory.adapters.gcp.model_armor_guardrail import ModelArmorGuardrailAdapter
from cio_advisory.config import Settings
from cio_advisory.domain.models import Direction

TEXT = "Should I move my whole portfolio into one stock?"
DIRECTIONS = [Direction.INPUT, Direction.OUTPUT]


class _MirrorState(enum.IntEnum):
    """``modelarmor_v1.FilterMatchState``'s members, by name and number."""

    FILTER_MATCH_STATE_UNSPECIFIED = 0
    NO_MATCH_FOUND = 1
    MATCH_FOUND = 2


def _map(response: Any, direction: Direction = Direction.INPUT) -> Any:
    return ModelArmorGuardrailAdapter._map_result(response, direction, TEXT)


def _mirror_response(state: _MirrorState) -> SimpleNamespace:
    return SimpleNamespace(sanitization_result=SimpleNamespace(filter_match_state=state))


# --------------------------------------------------------------------------- #
# SDK-free: the mapping itself
# --------------------------------------------------------------------------- #
def test_the_enum_str_is_the_number_not_the_name() -> None:
    """The premise of the fix: a ``str()`` substring check can never see MATCH_FOUND."""
    assert "MATCH_FOUND" not in str(_MirrorState.MATCH_FOUND)


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_match_found_blocks_sdk_free(direction: Direction) -> None:
    verdict = _map(_mirror_response(_MirrorState.MATCH_FOUND), direction)
    assert verdict.allowed is False
    assert verdict.sanitized_text is None
    assert verdict.findings and verdict.findings[0].detail == "Model Armor filter match"


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_no_match_found_allows_sdk_free(direction: Direction) -> None:
    verdict = _map(_mirror_response(_MirrorState.NO_MATCH_FOUND), direction)
    assert verdict.allowed is True
    assert verdict.sanitized_text == TEXT
    assert verdict.findings == ()


@pytest.mark.parametrize(
    "response",
    [
        _mirror_response(_MirrorState.FILTER_MATCH_STATE_UNSPECIFIED),
        SimpleNamespace(sanitization_result=None),
        SimpleNamespace(sanitization_result=SimpleNamespace()),
        object(),
        None,
    ],
    ids=["unspecified-state", "none-result", "empty-result", "no-result-attr", "none-response"],
)
def test_no_verdict_fails_closed_sdk_free(response: Any) -> None:
    verdict = _map(response)
    assert verdict.allowed is False
    assert verdict.sanitized_text is None


# --------------------------------------------------------------------------- #
# Real SDK: real modelarmor_v1 messages through screen(), with a fake client
# --------------------------------------------------------------------------- #
class _FakeClient:
    """Returns a canned response for either direction, or raises the canned error."""

    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.requests: list[Any] = []

    def _answer(self, request: Any) -> Any:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return self._response

    def sanitize_user_prompt(self, request: Any) -> Any:
        return self._answer(request)

    def sanitize_model_response(self, request: Any) -> Any:
        return self._answer(request)


def _ma() -> Any:
    return pytest.importorskip("google.cloud.modelarmor_v1")


def _adapter(client: _FakeClient) -> ModelArmorGuardrailAdapter:
    adapter = ModelArmorGuardrailAdapter(Settings(project_id="p", profile="gcp"))
    adapter._client = client  # skip the real client; the mapping is what is under test
    return adapter


def _real_response(direction: Direction, state_name: str | None) -> Any:
    """A real sanitize response; ``state_name=None`` leaves ``sanitization_result`` unset."""
    ma = _ma()
    cls = (
        ma.SanitizeUserPromptResponse
        if direction is Direction.INPUT
        else ma.SanitizeModelResponseResponse
    )
    if state_name is None:
        return cls()
    state = ma.FilterMatchState[state_name]
    return cls(sanitization_result=ma.SanitizationResult(filter_match_state=state))


def test_the_mirror_matches_the_real_enum() -> None:
    real = _ma().FilterMatchState
    assert {m.name: int(m) for m in real} == {m.name: int(m) for m in _MirrorState}
    assert "MATCH_FOUND" not in str(real.MATCH_FOUND)


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_match_found_blocks(direction: Direction) -> None:
    client = _FakeClient(_real_response(direction, "MATCH_FOUND"))
    verdict = _adapter(client).screen(TEXT, direction)
    assert verdict.allowed is False
    assert verdict.sanitized_text is None
    assert len(client.requests) == 1


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_no_match_found_allows(direction: Direction) -> None:
    client = _FakeClient(_real_response(direction, "NO_MATCH_FOUND"))
    verdict = _adapter(client).screen(TEXT, direction)
    assert verdict.allowed is True
    assert verdict.sanitized_text == TEXT


@pytest.mark.parametrize("direction", DIRECTIONS)
@pytest.mark.parametrize(
    "state_name",
    [None, "FILTER_MATCH_STATE_UNSPECIFIED"],
    ids=["missing-result", "unspecified-state"],
)
def test_no_verdict_fails_closed(direction: Direction, state_name: str | None) -> None:
    client = _FakeClient(_real_response(direction, state_name))
    verdict = _adapter(client).screen(TEXT, direction)
    assert verdict.allowed is False
    assert verdict.sanitized_text is None


def test_api_errors_propagate() -> None:
    """An API failure must not turn into an allow; it reaches the caller."""
    _ma()
    boom = RuntimeError("Model Armor unavailable")
    with pytest.raises(RuntimeError, match="unavailable"):
        _adapter(_FakeClient(error=boom)).screen(TEXT, Direction.INPUT)
