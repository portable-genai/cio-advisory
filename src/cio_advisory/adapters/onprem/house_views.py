"""On-prem placeholder for ``HouseViewRetrievalPort`` : the on-premise migration target.

One of the reversibility (P-02) migration placeholders: in the managed profile this port
binds to the governed-KB / File Search adapter; switching ``profile`` to ``onprem``
rebinds it here. The adapter constructs cleanly with **no external dependencies** and
structurally satisfies the same Protocol as the managed adapter, so the contract tests
prove interface parity. Porting house-view retrieval to an on-premise platform is *only*
a matter of filling these bodies in : the core domain logic is unchanged.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import HouseView

_MESSAGE = (
    "On-prem HouseViewRetrievalPort adapter is a migration placeholder; implement against "
    "your on-premise platform. Core domain logic is unchanged."
)


class OnPremHouseViewAdapter:
    """Placeholder house-view retrieval adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, str] | None = None,
    ) -> list[HouseView]:
        raise NotImplementedError(_MESSAGE)
