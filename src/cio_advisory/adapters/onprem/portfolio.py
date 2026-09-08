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
from ...domain.models import (
    ClientProfile,
    DataCitation,
    ModelPortfolio,
    Portfolio,
    RiskAppetite,
)

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

    def get_model_portfolio(
        self, risk_appetite: RiskAppetite, jurisdiction: str = "SG"
    ) -> ModelPortfolio:
        # Raises rather than returning None: None is the real answer for "this bank has not
        # published one", and a placeholder returning it would report a MISSING allocation as
        # a deliberate absence, which is the failure this profile exists to refuse.
        raise NotImplementedError(_MESSAGE)

    def read_provenance(self, client_id: str) -> DataCitation:
        # Raises for the same reason as the reads above, and NOT returning None: None means
        # "this store cannot say where its rows came from", which is a claim a working
        # adapter is entitled to make. A placeholder returning it would report an unbuilt
        # adapter as a reticent one.
        raise NotImplementedError(_MESSAGE)
