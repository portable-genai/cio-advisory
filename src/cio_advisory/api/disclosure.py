"""Put what the runtime controls did on a response, so the user who asked can see it.

One field, defined on every response model built from a briefing the service may hand to the
review console: ``review_routing``, one of ``routed``, ``failed``, ``off`` or ``not_required``.

The value comes from the request-scoped :class:`~..adapters.controls.RecordingReviewRouter`,
which the route receives from the same FastAPI dependency its service was built with.
"""

from __future__ import annotations

from pydantic import BaseModel

from ..adapters.controls import RecordingReviewRouter


def disclose[ResponseT: BaseModel](
    response: ResponseT, *, routing: RecordingReviewRouter | None = None
) -> ResponseT:
    """Return ``response`` with the controls' outcome for this request filled in."""
    if routing is None:
        return response
    return response.model_copy(update={"review_routing": routing.outcome.value})
