"""BigQuery portfolio adapter (PortfolioPort).

Reads the client's current holdings and KYC / suitability profile from **BigQuery** in
``asia-southeast1`` (Singapore). This is internal customer data, so there is no
cross-service hop: the read stays inside the residency perimeter, the dataset is
CMEK-encrypted, and the returned objects are de-identified at the boundary (P-04) before
any text reaches a model or audit sink.

The ``google.cloud.bigquery`` import is lazy so on-prem and test profiles load this module
with no GCP SDK installed.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain._grounded import coerce_asset_class
from ...domain.errors import PortfolioUnavailableError
from ...domain.models import ClientProfile, Holding, Portfolio, RiskAppetite


class BigQueryPortfolioAdapter:
    """Load portfolios and client profiles from BigQuery (in-region, CMEK)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._bq = settings.bigquery
        self._client: Any | None = None

    def _get_client(self) -> Any:
        from google.cloud import bigquery  # lazy

        if self._client is None:
            self._client = bigquery.Client(
                project=self._settings.project_id, location=self._bq.location
            )
        return self._client

    def _table(self, table: str) -> str:
        return f"{self._settings.project_id}.{self._bq.dataset}.{table}"

    def get_portfolio(self, client_id: str) -> Portfolio:
        """Return the client's holdings from the portfolio table."""
        client = self._get_client()
        rows = self._query(
            client,
            f"SELECT instrument, asset_class, value, weight, currency "
            f"FROM `{self._table(self._bq.portfolio_table)}` WHERE client_id = @client_id",
            client_id,
        )
        holdings = tuple(
            Holding(
                instrument=str(r["instrument"]),
                asset_class=coerce_asset_class(r["asset_class"]),
                value=float(r["value"]),
                weight=float(r["weight"]),
                currency=str(r.get("currency", "USD")),
            )
            for r in rows
        )
        if not holdings:
            raise PortfolioUnavailableError(f"no portfolio rows for client {client_id!r}")
        total = sum(h.value for h in holdings)
        currency = holdings[0].currency
        return Portfolio(
            client_id=client_id, holdings=holdings, total_value=total, currency=currency
        )

    def get_profile(self, client_id: str) -> ClientProfile:
        """Return the client's KYC / suitability profile from the profile table.

        The ``tenant`` (owning book) column is the server-side object-authZ owner the
        entitlement gate reads (``domain/entitlements.py``); a profile row without it is
        owner-less and fails closed (deny), never client-asserted.
        """
        client = self._get_client()
        rows = self._query(
            client,
            f"SELECT risk_appetite, objectives, knowledge_experience, constraints, "
            f"jurisdiction, tenant FROM `{self._table(self._bq.profile_table)}` "
            f"WHERE client_id = @client_id LIMIT 1",
            client_id,
        )
        if not rows:
            raise PortfolioUnavailableError(f"no profile row for client {client_id!r}")
        row = rows[0]
        return ClientProfile(
            id=client_id,
            risk_appetite=self._coerce_appetite(row.get("risk_appetite")),
            objectives=tuple(row.get("objectives") or ()),
            knowledge_experience=str(row.get("knowledge_experience") or "informed"),
            constraints=tuple(row.get("constraints") or ()),
            jurisdiction=str(row.get("jurisdiction") or "SG"),
            tenant=str(row.get("tenant") or ""),
        )

    def _query(self, client: Any, sql: str, client_id: str) -> list[dict[str, Any]]:
        from google.cloud import bigquery  # lazy

        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("client_id", "STRING", client_id)]
        )
        return [dict(row) for row in client.query(sql, job_config=job_config).result()]

    @staticmethod
    def _coerce_appetite(value: Any) -> RiskAppetite:
        by_value = {a.value: a for a in RiskAppetite}
        if isinstance(value, str):
            return by_value.get(value.strip().lower(), RiskAppetite.BALANCED)
        return RiskAppetite.BALANCED
