"""On-prem placeholder for ``GroundingPort`` : the on-premise migration target.

One of the reversibility (P-02) migration placeholders: in the managed profile this port
binds to the Gemini ``google_search`` grounding adapter; switching ``profile`` to
``onprem`` rebinds it here. The adapter constructs cleanly with **no external
dependencies** and structurally satisfies the same Protocol as the managed adapter. The
``enabled`` property reports ``False`` so the domain never attempts web grounding on the
on-prem profile until a real backend is wired in. Filling these bodies in is the only
change required.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import WebCitation

_MESSAGE = (
    "On-prem GroundingPort adapter is a migration placeholder; implement against your "
    "on-premise platform. Core domain logic is unchanged."
)


class OnPremGroundingAdapter:
    """Placeholder grounding adapter for the on-prem profile (web grounding off)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return False

    def ground(self, query: str, max_results: int = 5) -> list[WebCitation]:
        raise NotImplementedError(_MESSAGE)
