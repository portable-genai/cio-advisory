"""Platform ReviewRouterPort: submit the routed briefing review to human-review-console via
``review-kit``.

Builds the review from the escalated briefing and submits it to the human-review-console service
intake (``POST /v1/service/reviews``). The base URL comes from ``HUMAN_REVIEW_URL`` and the signed
actor from ``S2S_SIGNING_KEY``; the bearer depends on how the console is reached:

* **Through the portal's IAP edge** (``gcp``): the deployed console is an embedded app behind
  `journey-portal`, so ``HUMAN_REVIEW_URL`` is its edge path
  (``https://<edge-host>/apps/human-review-console/api``) and the edge accepts only a
  Google-signed ID token minted for the IAP OAuth client id, named by
  ``HUMAN_REVIEW_IAP_AUDIENCE``. The router mints one per submission with this service's
  workload identity (:func:`._s2s.fetch_id_token`), so an expiring token is never reused. The
  console authenticates this service from the IAP assertion the edge forwards, not from the
  portal's bearer that replaces this one.
* **Directly** (audience unset): the static ``S2S_TOKEN`` bearer, the same pair the other
  platform delegates use.

``HUMAN_REVIEW_IAP_AUDIENCE`` is read in three states: unset keeps the static bearer, emptied
refuses at construction, and a backend-service path pasted where the client id belongs refuses
by name. Under ``gcp`` the boot check in :mod:`cio_advisory.config` requires it beside the URL
while routing is on. The kit itself uses stdlib ``urllib``; ``google-auth`` is imported only when
a token is minted.
"""

from __future__ import annotations

from review_kit import ReviewClient

from ...config import HUMAN_REVIEW_IAP_AUDIENCE_ENV, Settings, iap_audience_or_refuse
from ...domain.models import AdvisoryBriefing
from ...envread import optional_setting, required_setting
from .._review_payload import briefing_to_review
from . import _s2s
from ._s2s import SIGNING_KEY_ENV, TOKEN_ENV

_URL_ENV = "HUMAN_REVIEW_URL"


class PlatformReviewRouter:
    """Submit escalated advisory briefings to human-review-console (rule R8), reusing the shared
    client.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        audience = optional_setting(HUMAN_REVIEW_IAP_AUDIENCE_ENV)
        self._audience = (
            None
            if audience is None
            else iap_audience_or_refuse(HUMAN_REVIEW_IAP_AUDIENCE_ENV, audience)
        )

    def route(self, briefing: AdvisoryBriefing, *, maker: str, tenant: str = "") -> None:
        self._client().submit(
            briefing_to_review(briefing, maker=maker, tenant=tenant), actor="doc3-cio-advisory"
        )

    def _client(self) -> ReviewClient:
        base_url = required_setting(_URL_ENV)
        audience = self._audience
        if audience is None:
            return ReviewClient(base_url, token_env=TOKEN_ENV, signing_key_env=SIGNING_KEY_ENV)
        return ReviewClient(
            base_url,
            token_env=TOKEN_ENV,
            signing_key_env=SIGNING_KEY_ENV,
            bearer_provider=lambda: _s2s.fetch_id_token(audience),
        )
