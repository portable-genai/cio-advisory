"""HouseViewRetrievalPort : grounded CIO house-view retrieval over the governed KB.

B3 does RAG over the bank's CIO house-view articles via the **A2 Enterprise Knowledge
Base** (governed retrieval, ``/v1/search``); it does NOT build its own retrieval backend.
The platform adapter is a thin HTTP client to A2; the GCP adapter is Agent Search / File
Search; the on-prem adapter is a placeholder. Each maps the retrieved passages to
:class:`HouseView` objects so the domain reasons in house-view terms.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import HouseView


@runtime_checkable
class HouseViewRetrievalPort(Protocol):
    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, str] | None = None,
    ) -> list[HouseView]:
        """Return ranked CIO house views (with provenance) for ``query``."""
        ...
