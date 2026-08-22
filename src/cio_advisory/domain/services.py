"""Aggregator re-exporting the B3 orchestration services and policies.

The services live one-per-module (``advisory_service``, ``talking_points_service``) and
the policies likewise (``suitability_policy``, ``review_policy``) so each stays focused.
This module is the single import surface the wiring layers (``api.deps``, ``agent.tools``,
``cli``) use, so they never need to know which module a service or policy lives in.
"""

from __future__ import annotations

from .advisory_service import AdvisoryService
from .review_policy import CioReviewPolicy
from .suitability_policy import SuitabilityPolicy
from .talking_points_service import TalkingPointsService

__all__ = [
    "AdvisoryService",
    "TalkingPointsService",
    "SuitabilityPolicy",
    "CioReviewPolicy",
]
