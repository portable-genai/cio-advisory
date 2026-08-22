"""PortfolioPort : the client's portfolio and KYC profile (internal data).

Reads the client's current holdings and risk/suitability profile from the bank's own
systems. This is internal customer data, so there is **no platform (cross-service) hop**:
the GCP adapter reads BigQuery / AlloyDB (lazy SDK) inside the residency perimeter, and
the on-prem adapter is a placeholder. The returned profile/portfolio are de-identified at
the boundary (P-04) before any text reaches a model or audit sink.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import ClientProfile, Portfolio


@runtime_checkable
class PortfolioPort(Protocol):
    def get_portfolio(self, client_id: str) -> Portfolio:
        """Return the client's current holdings."""
        ...

    def get_profile(self, client_id: str) -> ClientProfile:
        """Return the client's KYC / suitability profile (risk appetite, constraints)."""
        ...
