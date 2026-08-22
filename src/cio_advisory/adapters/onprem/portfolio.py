"""On-prem placeholder for ``PortfolioPort`` : the on-premise migration target.

One of the reversibility (P-02) migration placeholders: in the managed profile this port
binds to the BigQuery / AlloyDB portfolio adapter; switching ``profile`` to ``onprem``
rebinds it here. The adapter constructs cleanly with **no external dependencies** and
structurally satisfies the same Protocol as the managed adapter, so the contract tests
prove interface parity. Porting the portfolio/profile reads to an on-premise relational
store is *only* a matter of filling these bodies in : the core domain logic is unchanged.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import ClientProfile, Portfolio

_MESSAGE = (
    "On-prem PortfolioPort adapter is a migration placeholder; implement against your "
    "on-premise platform. Core domain logic is unchanged."
)


class OnPremPortfolioAdapter:
    """Placeholder portfolio adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def get_portfolio(self, client_id: str) -> Portfolio:
        raise NotImplementedError(_MESSAGE)

    def get_profile(self, client_id: str) -> ClientProfile:
        raise NotImplementedError(_MESSAGE)
