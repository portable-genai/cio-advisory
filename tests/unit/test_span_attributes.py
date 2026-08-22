"""The advisory pipeline's spans carry structural attributes only, never content.

A trace backend is not the WORM audit trail. It has no redaction stage, no retention policy
written against a regulator's requirement, and a far wider read audience than the audit
store. The conftest ``RecordingTracer`` records only span NAMES, so it can never see a
leak: the attributes are thrown away before anything could inspect them. This module keeps
its own recorder that captures ``(name, dict(attributes))`` and asserts two halves:

* the attribute KEY SET is a fixed allowlist (an attribute added "to explain" a briefing is
  a defect, not an enrichment), and
* no attribute VALUE carries the planted PII from ``sample_clients.PII_CLIENT_REQUEST``,
  which is the input that would actually leak if any attribute were content-shaped.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from tests.conftest import load_service
from tests.fixtures import sample_clients

from cio_advisory.domain.identity import Principal

#: The one attribute set every advisory span may carry: enough for "whose call, doing
#: what, how long", and nothing more. Grow this list only for structural, low-cardinality
#: identifiers; never for client ids, briefing text or talking points.
ALLOWED_SPAN_ATTRIBUTES = {"action", "actor"}

_ACTOR = "rm@bank.test"
_PRINCIPAL = Principal(
    subject=_ACTOR, principals=("group:cio-analyst",), tenant="demo-bank", source="test"
)
_PRINCIPAL_WITH_GRANT = Principal(
    subject=_ACTOR,
    principals=(f"client:{sample_clients.BALANCED_CLIENT_ID}",),
    tenant="demo-bank",
    source="test",
)
#: The PII planted in the noisy client request; a content-shaped attribute would carry it.
_PLANTED = ("S1234567A", "jane.doe@example.com")


class _RecordingTracer:
    """Captures every span name AND its attributes so the test can inspect what left."""

    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, str]]] = []

    @contextmanager
    def span(self, name: str, **attributes: str):  # type: ignore[no-untyped-def]
        self.spans.append((name, dict(attributes)))
        yield


def _service(
    house_view: Any,
    portfolio: Any,
    llm: Any,
    guardrail: Any,
    redaction: Any,
    audit: Any,
    tracer: _RecordingTracer,
) -> Any:
    return load_service("AdvisoryService")(
        house_view, portfolio, llm, guardrail, redaction, tracer, audit
    )


def test_brief_opens_exactly_one_named_span(
    house_view, portfolio, llm, guardrail, redaction, audit
) -> None:
    tracer = _RecordingTracer()
    service = _service(house_view, portfolio, llm, guardrail, redaction, audit, tracer)
    service.brief(sample_clients.BALANCED_CLIENT_ID, _PRINCIPAL)
    assert [name for name, _ in tracer.spans] == ["advisory.brief"]


def test_talking_points_opens_its_own_named_span(
    house_view, portfolio, llm, guardrail, redaction, audit
) -> None:
    tracer = _RecordingTracer()
    service = _service(house_view, portfolio, llm, guardrail, redaction, audit, tracer)
    service.talking_points(sample_clients.BALANCED_CLIENT_ID, _PRINCIPAL)
    assert [name for name, _ in tracer.spans] == ["advisory.talking_points"]


def test_every_span_attribute_set_is_the_fixed_allowlist(
    house_view, portfolio, llm, guardrail, redaction, audit
) -> None:
    """Whatever the verdict, a span may not attach findings to explain itself."""
    tracer = _RecordingTracer()
    service = _service(house_view, portfolio, llm, guardrail, redaction, audit, tracer)
    service.brief(sample_clients.BALANCED_CLIENT_ID, _PRINCIPAL)
    service.brief(sample_clients.CONSERVATIVE_CLIENT_ID, _PRINCIPAL)
    service.talking_points(sample_clients.BALANCED_CLIENT_ID, _PRINCIPAL)
    assert tracer.spans
    for name, attributes in tracer.spans:
        assert set(attributes) == ALLOWED_SPAN_ATTRIBUTES, name


def test_no_span_attribute_carries_planted_pii(
    house_view, portfolio, llm, guardrail, redaction, audit
) -> None:
    """Drive the pipeline with the request carrying the planted NRIC + email."""
    tracer = _RecordingTracer()
    service = _service(house_view, portfolio, llm, guardrail, redaction, audit, tracer)
    # The noisy id maps to no seeded client, so stub the profile/portfolio lookups the way
    # the redaction-boundary test does; the grant admits the owner-less stub profile.
    portfolio.get_profile = lambda _cid: sample_clients.BALANCED_PROFILE  # type: ignore[assignment]
    portfolio.get_portfolio = lambda _cid: sample_clients.BALANCED_PORTFOLIO  # type: ignore[assignment]
    service.brief(sample_clients.PII_CLIENT_REQUEST, _PRINCIPAL_WITH_GRANT)
    emitted = " ".join(
        str(value) for _, attributes in tracer.spans for value in attributes.values()
    )
    for planted in _PLANTED:
        assert planted not in emitted
        assert planted.lower() not in emitted.lower()
