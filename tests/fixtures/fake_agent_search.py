"""An in-memory Agent Search project, installed in ``sys.modules`` under the SDK's own names.

The ``gcp`` house-view adapter imports its SDK lazily, inside the methods that call it, so a test
can place these modules in ``sys.modules`` and drive the real adapter code, request construction
included, with no cloud SDK installed and no network. Everything here is fictional.

It models the two facts about the real service this repository has been caught out by:

* a data store and its engine exist at ONE location, and a request naming another location is
  refused (:class:`NotFound`) rather than answered with nothing;
* a client serves the location its HOST names. ``us`` and ``eu`` are prefixed hosts, ``global``
  is the bare host, and a client left on the library default reaches ``global`` whatever path it
  sends (:class:`WrongHost`).

Documents are kept the way a protobuf ``Struct`` keeps them, every number a double, so a writer
that compares what it would send with what it reads back is tested against the shape it will
really see.
"""

from __future__ import annotations

import copy
import re
import sys
import types
from dataclasses import dataclass, field
from typing import Any

DEFAULT_HOST = "discoveryengine.googleapis.com"


class NotFound(Exception):  # noqa: N818 - the name the real api_core exception carries
    """The resource does not exist at the location the request names."""


class AlreadyExists(Exception):  # noqa: N818 - the name the real api_core exception carries
    """A create named a document id the branch already holds."""


class WrongHost(Exception):  # noqa: N818 - named for what the real service does
    """The request's location is not the one the client's host serves."""


def as_struct(value: Any) -> Any:
    """``value`` as a ``Struct`` stores it: numbers become doubles, tuples become lists."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        return {str(key): as_struct(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [as_struct(item) for item in value]
    raise TypeError(f"a Struct cannot hold {type(value).__name__}")


class _Message:
    """A request or resource message: keyword fields as attributes, nothing else."""

    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)


@dataclass
class FakeAgentSearch:
    """One data store with one engine over it, at one location of one project."""

    project: str = "fictional-wealth-project"
    location: str = "us"
    data_store_id: str = "cio-house-views"
    engine_id: str = "cio-advisory-engine"
    documents: dict[str, dict[str, Any]] = field(default_factory=dict)
    writes: list[tuple[str, str]] = field(default_factory=list)
    searches: list[str] = field(default_factory=list)
    hosts: list[str] = field(default_factory=list)

    @property
    def _collection(self) -> str:
        return f"projects/{self.project}/locations/{self.location}/collections/default_collection"

    @property
    def branch(self) -> str:
        return f"{self._collection}/dataStores/{self.data_store_id}/branches/default_branch"

    @property
    def serving_config(self) -> str:
        return f"{self._collection}/engines/{self.engine_id}/servingConfigs/default_search"

    def put(self, doc_id: str, record: dict[str, Any]) -> None:
        """Seed a document directly, as something other than the loader wrote it."""
        self.documents[doc_id] = as_struct(record)

    @staticmethod
    def _require_host(host: str, resource: str) -> None:
        match = re.search(r"/locations/([^/]+)/", resource)
        named = match.group(1) if match else ""
        served = "global" if host == DEFAULT_HOST else host.removesuffix(f"-{DEFAULT_HOST}")
        if served != named:
            raise WrongHost(f"{host} serves {served!r}; the request names {named!r}")

    def install(self, monkeypatch: Any) -> FakeAgentSearch:
        """Put the fake SDK modules in ``sys.modules`` for the rest of the test."""
        world = self

        class ClientOptions:
            def __init__(self, api_endpoint: str | None = None) -> None:
                self.api_endpoint = api_endpoint

        class _Client:
            def __init__(self, client_options: ClientOptions | None = None) -> None:
                self.host = getattr(client_options, "api_endpoint", None) or DEFAULT_HOST
                world.hosts.append(self.host)

        class SearchServiceClient(_Client):
            def search(self, request: Any) -> Any:
                world._require_host(self.host, request.serving_config)
                world.searches.append(request.serving_config)
                if request.serving_config != world.serving_config:
                    raise NotFound(f"no engine at {request.serving_config}")
                page = list(world.documents.items())[: request.page_size or None]
                return types.SimpleNamespace(
                    results=[
                        types.SimpleNamespace(
                            document=types.SimpleNamespace(id=doc_id, struct_data=copy.deepcopy(s))
                        )
                        for doc_id, s in page
                    ]
                )

        class DocumentServiceClient(_Client):
            def list_documents(self, request: Any) -> list[Any]:
                world._require_host(self.host, request.parent)
                if request.parent != world.branch:
                    raise NotFound(f"no data store branch at {request.parent}")
                return [
                    types.SimpleNamespace(
                        id=doc_id,
                        name=f"{world.branch}/documents/{doc_id}",
                        struct_data=copy.deepcopy(s),
                    )
                    for doc_id, s in world.documents.items()
                ]

            def create_document(self, request: Any) -> None:
                world._require_host(self.host, request.parent)
                if request.parent != world.branch:
                    raise NotFound(f"no data store branch at {request.parent}")
                if request.document_id in world.documents:
                    raise AlreadyExists(request.document_id)
                world.documents[request.document_id] = as_struct(request.document.struct_data)
                world.writes.append(("create", request.document_id))

            def update_document(self, request: Any) -> None:
                name = request.document.name
                world._require_host(self.host, name)
                prefix = f"{world.branch}/documents/"
                doc_id = name.removeprefix(prefix)
                if not name.startswith(prefix) or doc_id not in world.documents:
                    raise NotFound(name)
                world.documents[doc_id] = as_struct(request.document.struct_data)
                world.writes.append(("update", doc_id))

        de = types.ModuleType("google.cloud.discoveryengine_v1")
        de.SearchServiceClient = SearchServiceClient  # type: ignore[attr-defined]
        de.DocumentServiceClient = DocumentServiceClient  # type: ignore[attr-defined]
        for message in (
            "SearchRequest",
            "ListDocumentsRequest",
            "CreateDocumentRequest",
            "UpdateDocumentRequest",
            "Document",
        ):
            setattr(de, message, type(message, (_Message,), {}))
        cloud = types.ModuleType("google.cloud")
        cloud.discoveryengine_v1 = de  # type: ignore[attr-defined]
        options = types.ModuleType("google.api_core.client_options")
        options.ClientOptions = ClientOptions  # type: ignore[attr-defined]
        api_core = types.ModuleType("google.api_core")
        api_core.client_options = options  # type: ignore[attr-defined]
        for name, module in (
            ("google.cloud", cloud),
            ("google.cloud.discoveryengine_v1", de),
            ("google.api_core", api_core),
            ("google.api_core.client_options", options),
        ):
            monkeypatch.setitem(sys.modules, name, module)
        return self
