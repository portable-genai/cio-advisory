"""Remote-platform house-view adapter : thin HTTP client to the A2 governed KB.

B3 does RAG over the bank's CIO house-view articles via the shared **A2 Enterprise
Knowledge Base** (``enterprise-knowledge-base``) rather than building its own retrieval
backend (SPEC §6, A2 contract). This adapter implements :class:`HouseViewRetrievalPort` by
POSTing to A2's ``/v1/search`` endpoint and mapping each returned passage into a domain
:class:`HouseView` (with a HOUSE_VIEW citation). Stance and asset class are parsed from the
passage metadata where present, defaulting conservatively when absent.

The base URL is read from ``KNOWLEDGE_BASE_URL`` (localhost default), so nothing GCP-specific is
required to construct or exercise it.
"""

from __future__ import annotations

from typing import Any

import httpx

from ...domain._grounded import coerce_asset_class, coerce_stance
from ...domain.errors import AdvisoryError
from ...domain.models import Citation, HouseView, SourceType
from ...envread import setting_or_default
from . import _s2s

_DEFAULT_URL = "http://localhost:8082"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class RemoteHouseViewError(AdvisoryError):
    """Raised when the A2 knowledge-base service returns a non-2xx response."""


class RemoteHouseViewAdapter:
    """HTTP client for the A2 ``enterprise-knowledge-base`` search endpoint."""

    def __init__(self, settings: object) -> None:
        self._settings = settings
        self._base_url = _s2s.validate_base_url(
            setting_or_default("KNOWLEDGE_BASE_URL", _DEFAULT_URL), service="knowledge base"
        )

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, str] | None = None,
    ) -> list[HouseView]:
        """Retrieve CIO house views via the A2 governed-KB search endpoint."""
        payload: dict[str, Any] = {
            "query": query,
            "top_k": top_k,
            "acl_principals": ["cio-advisory"],
            "filters": dict(filters or {}),
        }
        url = f"{self._base_url}/v1/search"
        try:
            response = httpx.post(url, json=payload, timeout=_TIMEOUT, headers=_s2s.headers())
        except httpx.HTTPError as exc:
            raise RemoteHouseViewError(f"A2 KB request to {url} failed: {exc}") from exc
        if response.status_code // 100 != 2:
            raise RemoteHouseViewError(
                f"A2 KB {url} returned {response.status_code}: {response.text[:500]}"
            )
        return self._parse(response.json())

    @staticmethod
    def _parse(body: dict) -> list[HouseView]:
        out: list[HouseView] = []
        for i, passage in enumerate(body.get("passages") or ()):
            citation_raw = passage.get("citation") or {}
            source_id = str(citation_raw.get("source_id") or citation_raw.get("id") or f"hv-{i}")
            title = str(citation_raw.get("title") or passage.get("text", "")[:64])
            citation = Citation(
                source_id=source_id,
                source_type=SourceType.HOUSE_VIEW,
                title=title,
                url=str(citation_raw.get("url", "")),
                page=citation_raw.get("page"),
                snippet=str(passage.get("text", ""))[:240],
                score=passage.get("score"),
            )
            out.append(
                HouseView(
                    id=source_id,
                    theme=str(citation_raw.get("theme") or title),
                    stance=coerce_stance(citation_raw.get("stance")),
                    asset_class=coerce_asset_class(citation_raw.get("asset_class")),
                    rationale=str(passage.get("text", "")),
                    citation=citation,
                )
            )
        return out
