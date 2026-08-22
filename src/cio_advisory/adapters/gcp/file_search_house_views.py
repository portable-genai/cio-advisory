"""Agent Search / File Search house-view adapter (HouseViewRetrievalPort).

When B3 runs standalone (gcp profile), CIO house-view articles are retrieved from an
**Agent Search / File Search** data store on the Gemini Enterprise Agent Platform, pinned
to ``asia-southeast1`` (Singapore). Inside the full platform, retrieval is instead
delegated to the governed A2 knowledge base (the ``platform`` adapter); the domain is
unchanged either way because both speak :class:`HouseView`.

The ``google.cloud.discoveryengine`` import is lazy so on-prem and test profiles load this
module with no GCP SDK installed.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain._grounded import coerce_asset_class, coerce_stance
from ...domain.models import Citation, HouseView, SourceType


class FileSearchHouseViewAdapter:
    """Retrieve CIO house views from an Agent Search / File Search data store."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cfg = settings.house_views
        self._client: Any | None = None

    def _serving_config(self, client: Any) -> str:
        return client.serving_config_path(
            project=self._settings.project_id,
            location=self._cfg.location,
            data_store=self._cfg.data_store_id,
            serving_config=self._cfg.serving_config,
        )

    def _get_client(self) -> Any:
        from google.cloud import discoveryengine_v1 as de  # lazy

        if self._client is None:
            self._client = de.SearchServiceClient()
        return self._client

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, str] | None = None,
    ) -> list[HouseView]:
        """Return ranked CIO house views (with provenance) for ``query``."""
        from google.cloud import discoveryengine_v1 as de  # lazy

        client = self._get_client()
        request = de.SearchRequest(
            serving_config=self._serving_config(client),
            query=query,
            page_size=top_k,
            filter=self._to_filter(filters),
        )
        response = client.search(request=request)
        return [self._to_house_view(result) for result in response.results]

    @staticmethod
    def _to_filter(filters: dict[str, str] | None) -> str:
        if not filters:
            return ""
        clauses = [f'{key}: ANY("{value}")' for key, value in filters.items()]
        return " AND ".join(clauses)

    @staticmethod
    def _to_house_view(result: Any) -> HouseView:
        doc = getattr(result, "document", None)
        struct = dict(getattr(doc, "struct_data", {}) or {})
        source_id = str(struct.get("id") or getattr(doc, "id", "") or "house-view")
        theme = str(struct.get("theme") or struct.get("title") or source_id)
        citation = Citation(
            source_id=source_id,
            source_type=SourceType.HOUSE_VIEW,
            title=theme,
            url=str(struct.get("url", "")),
            snippet=str(struct.get("snippet", ""))[:240],
        )
        return HouseView(
            id=source_id,
            theme=theme,
            stance=coerce_stance(struct.get("stance")),
            asset_class=coerce_asset_class(struct.get("asset_class")),
            rationale=str(struct.get("rationale", "")),
            citation=citation,
        )
