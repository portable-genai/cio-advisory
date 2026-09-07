"""PortfolioPort : the client's portfolio and KYC profile (internal data).

Reads the client's current holdings and risk/suitability profile from the bank's own
systems. This is internal customer data, so there is **no platform (cross-service) hop**:
the GCP adapter reads BigQuery / AlloyDB (lazy SDK) inside the residency perimeter, and
the on-prem adapter is a placeholder. The returned profile/portfolio are de-identified at
the boundary (P-04) before any text reaches a model or audit sink.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import ClientProfile, ModelPortfolio, Portfolio, RiskAppetite


@runtime_checkable
class PortfolioPort(Protocol):
    def get_portfolio(self, client_id: str) -> Portfolio:
        """Return the client's current holdings."""
        ...

    def get_profile(self, client_id: str) -> ClientProfile:
        """Return the client's KYC / suitability profile (risk appetite, constraints)."""
        ...

    def get_model_portfolio(
        self, risk_appetite: RiskAppetite, jurisdiction: str = "SG"
    ) -> ModelPortfolio | None:
        """Return the bank's ideal allocation for a risk profile, or ``None`` if unpublished.

        The same internal store as the holdings and for the same reason: an institution's
        strategic asset allocation is its own, so this port has no platform (cross-service)
        binding. ``None`` is a real answer rather than an error, and it is why every gap
        computed downstream is optional: a bank that has published no model portfolio for a
        profile gets a briefing without allocation gaps, not a briefing that invents targets.
        """
        ...
