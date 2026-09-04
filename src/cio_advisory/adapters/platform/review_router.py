"""Platform ReviewRouterPort: submit the routed briefing review to human-review-console via
``review-kit``.

Builds the review from the escalated briefing and submits it to the human-review-console service
intake (``POST /v1/service/reviews``), S2S-authenticated. The human-review-console base URL comes
from the environment (``HUMAN_REVIEW_URL``) and the S2S credentials from this repo's shared env-var
names (``S2S_TOKEN`` / ``S2S_SIGNING_KEY``, the same pair the other platform delegates use). No
cloud SDK is involved (the kit uses stdlib ``urllib`` + wire-compatible S2S headers), so this module
imports cleanly with no GCP SDK; it is bound under the ``gcp`` and ``platform`` profiles because it
makes a real network call to a sibling service.
"""

from __future__ import annotations

from review_kit import ReviewClient

from ...config import Settings
from ...domain.models import AdvisoryBriefing
from ...envread import required_setting
from .._review_payload import briefing_to_review
from ._s2s import SIGNING_KEY_ENV, TOKEN_ENV

_URL_ENV = "HUMAN_REVIEW_URL"


class PlatformReviewRouter:
    """Submit escalated advisory briefings to human-review-console (rule R8), reusing the shared
    client.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def route(
        self, briefing: AdvisoryBriefing, *, maker: str, tenant: str = ""
    ) -> None:  # pragma: no cover - needs live human-review-console
        base_url = required_setting(_URL_ENV)
        client = ReviewClient(base_url, token_env=TOKEN_ENV, signing_key_env=SIGNING_KEY_ENV)
        client.submit(
            briefing_to_review(briefing, maker=maker, tenant=tenant), actor="doc3-cio-advisory"
        )
