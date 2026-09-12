"""Agent Search house-view adapter (HouseViewRetrievalPort), and the one writer of its store.

When `cio-advisory` runs standalone (the ``gcp`` profile) the CIO house views are retrieved from
an Agent Search (Discovery Engine) data store, through the search engine Terraform creates over
it. Inside the full platform retrieval is delegated to `enterprise-knowledge-base` instead (the
``platform`` adapter); the domain is unchanged either way because both speak :class:`HouseView`.

**Where the store lives is one setting.** Agent Search serves exactly three locations,
``global``, ``us`` and ``eu``, and no Cloud region. ``settings.house_views.location`` (read from
``CIO_HOUSE_VIEWS_LOCATION``) names it and Terraform's ``house_views_location`` creates it; the
contract suite fails when their defaults or allowed values differ. The two jurisdictional
locations are reached through a location-prefixed host and ``global`` through the bare one, so
the clients are built for the location rather than left on the library default, which is the
``global`` host whatever location the resource path names.

**Reading and writing share one mapping.** :func:`house_view_record` is what
:meth:`FileSearchHouseViewAdapter.sync` writes and :func:`house_view_from_record` is what
:meth:`FileSearchHouseViewAdapter.retrieve` reads back. A field the loader sends and retrieval
drops is then a failing round-trip test rather than a quieter briefing: ``tags`` was one, and
dropping it unlinked every theme from the holdings it names.

The ``google.cloud.discoveryengine`` import is lazy, so the offline profiles, the loader's dry
run and the tests load this module with no cloud SDK installed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ...config import Settings, agent_search_location
from ...domain._grounded import coerce_asset_class, coerce_stance
from ...domain.models import Citation, HouseView, SourceType

_COLLECTION = "default_collection"
_BRANCH = "default_branch"
_GLOBAL_HOST = "discoveryengine.googleapis.com"

#: What Agent Search accepts as a document id. Checked before a write, so a bad id fails the load
#: with its name rather than as a 400 halfway through.
_DOCUMENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}")

#: The most documents one list page may return.
_LIST_PAGE_SIZE = 1000


class HouseViewStoreConflictError(RuntimeError):
    """The store holds a document under a loaded id that another tenant, or no tenant, owns.

    Raised before anything is written. Re-stamping a document's tenant would move a CIO
    publication from one bank's briefings into another's, which no loader may do silently.
    """


def api_endpoint(location: str) -> str:
    """The Discovery Engine host serving ``location``.

    A prefixed host for ``us`` and ``eu``, the bare host for ``global``; any other location is
    refused before a host is derived.
    """
    if agent_search_location(location) == "global":
        return _GLOBAL_HOST
    return f"{location}-{_GLOBAL_HOST}"


def _require_tenant(tenant: str) -> str:
    value = (tenant or "").strip()
    if not value:
        raise ValueError(
            "a house view in the managed store must name its owning tenant: an untagged "
            "document is public to every tenant's briefings"
        )
    return value


def house_view_record(view: HouseView, tenant: str) -> dict[str, Any]:
    """The ``struct_data`` document :meth:`FileSearchHouseViewAdapter.sync` writes for ``view``."""
    if not _DOCUMENT_ID.fullmatch(view.id):
        raise ValueError(f"house view id {view.id!r} is not a valid Agent Search document id")
    citation = view.citation
    record: dict[str, Any] = {
        "id": view.id,
        "tenant": _require_tenant(tenant),
        "theme": view.theme,
        "stance": view.stance.value,
        "asset_class": view.asset_class.value,
        "rationale": view.rationale,
        "tags": list(view.tags),
        "title": citation.title if citation is not None else view.theme,
        "url": citation.url if citation is not None else "",
        "snippet": citation.snippet if citation is not None else "",
    }
    if citation is not None and citation.page is not None:
        record["page"] = citation.page
    if citation is not None and citation.score is not None:
        record["score"] = citation.score
    return record


def house_view_from_record(record: Mapping[str, Any], document_id: str = "") -> HouseView:
    """The :class:`HouseView` a stored document describes, the inverse of :func:`house_view_record`.

    ``document_id`` stands in for a record that carries no ``id`` of its own.
    """
    source_id = str(record.get("id") or document_id)
    if not source_id:
        raise ValueError("a house-view document with no id cannot be cited")
    theme = str(record.get("theme") or record.get("title") or source_id)
    page = record.get("page")
    score = record.get("score")
    return HouseView(
        id=source_id,
        theme=theme,
        stance=coerce_stance(record.get("stance")),
        asset_class=coerce_asset_class(record.get("asset_class")),
        rationale=str(record.get("rationale") or ""),
        tags=tuple(str(tag) for tag in record.get("tags") or ()),
        tenant=str(record.get("tenant") or ""),
        citation=Citation(
            source_id=source_id,
            source_type=SourceType.HOUSE_VIEW,
            title=str(record.get("title") or theme),
            url=str(record.get("url") or ""),
            page=int(page) if page is not None else None,
            snippet=str(record.get("snippet") or "")[:240],
            score=float(score) if score is not None else None,
        ),
    )


def _plain(value: Any) -> Any:
    """A protobuf ``Struct`` as JSON-shaped Python, with every number the double it stores.

    Applied to both what is read back and what would be written, so an ``int`` page the loader
    sends compares equal to the ``1.0`` the store returns and an unchanged document is left alone.
    """
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, Iterable):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class SyncReport:
    """What one :meth:`FileSearchHouseViewAdapter.sync` did, by document id."""

    created: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    #: Documents this tenant holds that the loaded corpus no longer names. Reported, never
    #: deleted: retrieval still returns them, and removing a publication is not a loader's call.
    stale: tuple[str, ...] = ()

    @property
    def writes(self) -> int:
        return len(self.created) + len(self.updated)


class FileSearchHouseViewAdapter:
    """Retrieve CIO house views from the Agent Search engine, and sync the store behind it."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cfg = settings.house_views
        self._location = agent_search_location(self._cfg.location)
        self._endpoint = api_endpoint(self._location)
        self._search_client: Any | None = None
        self._document_client: Any | None = None

    # ------------------------------------------------------------------ #
    # Where
    # ------------------------------------------------------------------ #
    @property
    def endpoint(self) -> str:
        """The host every call goes to, derived from the store location."""
        return self._endpoint

    @property
    def serving_config(self) -> str:
        """The search ENGINE's serving config, which is the search resource Terraform creates."""
        return (
            f"{self._location_path()}/collections/{_COLLECTION}"
            f"/engines/{self._cfg.engine_id}/servingConfigs/{self._cfg.serving_config}"
        )

    @property
    def branch(self) -> str:
        """The data store branch documents are written to."""
        return (
            f"{self._location_path()}/collections/{_COLLECTION}"
            f"/dataStores/{self._cfg.data_store_id}/branches/{_BRANCH}"
        )

    def _location_path(self) -> str:
        return f"projects/{self._settings.project_id}/locations/{self._location}"

    # ------------------------------------------------------------------ #
    # Lazy clients, each bound to the host that serves the location
    # ------------------------------------------------------------------ #
    def _client_options(self) -> Any:
        from google.api_core.client_options import ClientOptions  # lazy

        return ClientOptions(api_endpoint=self._endpoint)

    def _search(self) -> Any:
        if self._search_client is None:
            from google.cloud import discoveryengine_v1 as de  # lazy

            self._search_client = de.SearchServiceClient(client_options=self._client_options())
        return self._search_client

    def _documents(self) -> Any:
        if self._document_client is None:
            from google.cloud import discoveryengine_v1 as de  # lazy

            self._document_client = de.DocumentServiceClient(client_options=self._client_options())
        return self._document_client

    # ------------------------------------------------------------------ #
    # HouseViewRetrievalPort
    # ------------------------------------------------------------------ #
    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, str] | None = None,
    ) -> list[HouseView]:
        """Return ranked CIO house views (with provenance) for ``query``."""
        from google.cloud import discoveryengine_v1 as de  # lazy

        request = de.SearchRequest(
            serving_config=self.serving_config,
            query=query,
            page_size=top_k,
            filter=self._to_filter(filters),
        )
        response = self._search().search(request=request)
        return [self._to_house_view(result) for result in response.results]

    @staticmethod
    def _to_filter(filters: dict[str, str] | None) -> str:
        if not filters:
            return ""
        clauses = [f'{key}: ANY("{value}")' for key, value in filters.items()]
        return " AND ".join(clauses)

    @staticmethod
    def _to_house_view(result: Any) -> HouseView:
        document = getattr(result, "document", None)
        record = _plain(getattr(document, "struct_data", None) or {})
        return house_view_from_record(record, str(getattr(document, "id", "") or ""))

    # ------------------------------------------------------------------ #
    # The store's one writer
    # ------------------------------------------------------------------ #
    def sync(self, house_views: Sequence[HouseView], tenant: str) -> SyncReport:
        """Make the store hold ``house_views`` under ``tenant``. Idempotent, and safe to re-run.

        Every document is compared with what the store already holds: a missing one is created,
        one whose record differs is updated, an identical one is not written. A document under a
        loaded id that another tenant (or no tenant) owns stops the run BEFORE any write, and so
        does a corpus that names an id twice.
        """
        from google.cloud import discoveryengine_v1 as de  # lazy

        owner = _require_tenant(tenant)
        desired: dict[str, dict[str, Any]] = {}
        for view in house_views:
            if view.id in desired:
                raise ValueError(f"the corpus names house view {view.id!r} twice")
            desired[view.id] = house_view_record(view, owner)
        if not desired:
            raise ValueError("no house views to load; an empty load would prove nothing")

        client = self._documents()
        parent = self.branch
        existing: dict[str, Any] = {
            str(document.id): _plain(document.struct_data or {})
            for document in client.list_documents(
                request=de.ListDocumentsRequest(parent=parent, page_size=_LIST_PAGE_SIZE)
            )
        }
        conflicts = sorted(
            doc_id
            for doc_id in desired
            if doc_id in existing and existing[doc_id].get("tenant") != owner
        )
        if conflicts:
            raise HouseViewStoreConflictError(
                f"{parent} already holds {conflicts} under another tenant or none; "
                f"nothing was written, and a load as {owner!r} never re-stamps a document"
            )

        created: list[str] = []
        updated: list[str] = []
        unchanged: list[str] = []
        for doc_id, record in desired.items():
            if doc_id not in existing:
                client.create_document(
                    request=de.CreateDocumentRequest(
                        parent=parent,
                        document=de.Document(id=doc_id, struct_data=record),
                        document_id=doc_id,
                    )
                )
                created.append(doc_id)
            elif existing[doc_id] != _plain(record):
                client.update_document(
                    request=de.UpdateDocumentRequest(
                        document=de.Document(
                            name=f"{parent}/documents/{doc_id}", id=doc_id, struct_data=record
                        )
                    )
                )
                updated.append(doc_id)
            else:
                unchanged.append(doc_id)
        stale = sorted(
            doc_id
            for doc_id, record in existing.items()
            if doc_id not in desired and record.get("tenant") == owner
        )
        return SyncReport(
            created=tuple(created),
            updated=tuple(updated),
            unchanged=tuple(unchanged),
            stale=tuple(stale),
        )
