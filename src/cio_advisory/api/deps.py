"""FastAPI dependency wiring for the B3 CIO Advisory Assistant.

This module builds a single, process-wide :class:`~cio_advisory.config.Container` (the
ports-and-adapters registry) and assembles the advisory service from the Container's port
instances. The Container is created lazily on first access so importing this module : and
therefore the FastAPI app : never touches Google Cloud: a unit test or the on-prem profile
can import the API with no GCP SDK installed.

Each ``get_*`` factory is a FastAPI ``Depends`` provider. The service takes *explicit port
instances* in its constructor (SPEC §5), so the wiring here is the single place that knows
which ports it needs.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends

from ..adapters.controls import RecordingReviewRouter
from ..config import Container, Settings, build_container
from ..domain.models import AssetClass
from ..domain.services import AdvisoryService
from ..domain.suitability_policy import SuitabilityPolicy


@lru_cache(maxsize=1)
def get_container() -> Container:
    """Return the process-wide Container, building it on first use."""
    return build_container(Settings.load())


def get_settings() -> Settings:
    """Convenience accessor for the active settings (region, profile, ...)."""
    return get_container().settings


# --------------------------------------------------------------------------- #
# Service factories : assemble the service from the Container's ports.
# Constructor argument order mirrors SPEC §5 exactly.
# --------------------------------------------------------------------------- #


def get_request_review_router() -> RecordingReviewRouter:
    """The review router for ONE request, wrapped so the response reports the hand-off.

    FastAPI resolves a dependency once per request, so the route and the service it builds
    receive the same wrapper and the route reads what the service's hand-off did.
    """
    return RecordingReviewRouter(get_container().review_router)


#: Injected by FastAPI; ``None`` when the getter is called directly, which binds the
#: container's router unwrapped.
RequestReviewRouter = Annotated[RecordingReviewRouter | None, Depends(get_request_review_router)]


def get_advisory_service(review_router: RequestReviewRouter = None) -> AdvisoryService:
    """AdvisoryService(house_view, portfolio, llm, guardrail, redaction, tracer, audit)."""
    return build_advisory_service(get_container(), review_router=review_router)


def build_advisory_service(container: Container, *, review_router: Any = None) -> AdvisoryService:
    """Assemble an :class:`AdvisoryService` from an explicit Container.

    ``review_router`` replaces the container's router for this one service, which is how a
    caller hands it a :class:`RecordingReviewRouter` and reports the hand-off afterwards.
    """
    return AdvisoryService(
        house_view=container.house_view,
        portfolio=container.portfolio,
        llm=container.llm,
        guardrail=container.guardrail,
        redaction=container.redaction,
        tracer=container.tracer,
        audit=container.audit,
        review_router=review_router or container.review_router,
        suitability_policy=SuitabilityPolicy(
            concentration_limit=container.settings.suitability.concentration_limit,
            aggressive_asset_classes=frozenset(
                AssetClass(value)
                for value in container.settings.suitability.aggressive_asset_classes
            ),
            complex_asset_classes=frozenset(
                AssetClass(value) for value in container.settings.suitability.complex_asset_classes
            ),
        ),
    )


def create_app():
    """App factory used by ``uvicorn ...:create_app --factory`` and the CLI ``serve``."""
    from .app import app

    return app
