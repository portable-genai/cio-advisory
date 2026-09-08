#!/usr/bin/env python3
"""Ingest the shipped CIO house views into the managed search store.

The laptop grounds a briefing on the fictional corpus in ``cio_advisory/data/demo_book/``
through SQLite FTS5. This puts the same eight themes into the Agent Search / File Search
data store the standalone ``gcp`` profile queries, so the two surfaces ground on one report
and a paired comparison is comparing the same thing.

Each theme becomes one structured record whose fields are exactly what the adapter reads out
of ``struct_data`` (``adapters/gcp/file_search_house_views.py``): ``id``, ``theme``,
``stance``, ``asset_class``, ``rationale``, ``tags``, ``url`` and ``snippet``. A field the
adapter does not read is not sent, and a field it reads is never omitted.

What this is NOT: a governed publication pipeline. A bank ingests its own CIO articles
through whatever already publishes them, and this script exists so a DEMO of the standalone
profile has something real to retrieve. The records it writes are fictional and say so in
their own text; every URL is under ``example.test``, which is not a real domain.

Usage::

    python scripts/ingest_house_views.py --project <id> --dry-run
    python scripts/ingest_house_views.py --project <id>

``--dry-run`` prints the records and needs no credentials and no ``[gcp]`` extra: the
Discovery Engine import is inside the function that writes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from cio_advisory import demo_book  # noqa: E402
from cio_advisory.config import Settings  # noqa: E402

#: The struct_data keys the managed adapter reads. Named here so a record that would arrive
#: without one fails now rather than as a theme that coerces to a neutral multi-asset view
#: in front of an audience.
_REQUIRED = ("id", "theme", "stance", "asset_class", "rationale", "tags", "url", "snippet")


def records() -> list[dict[str, Any]]:
    """The shipped house views as the structured records the adapter expects."""
    demo_book.validate()
    out: list[dict[str, Any]] = []
    for row in demo_book.house_view_rows():
        record = {
            "id": str(row["id"]),
            "theme": str(row["theme"]),
            "stance": str(row["stance"]),
            "asset_class": str(row["asset_class"]),
            "rationale": str(row.get("rationale", "")),
            "tags": [str(t) for t in row.get("tags") or []],
            "url": str(row.get("url", "")),
            "snippet": str(row.get("snippet", "")),
        }
        missing = [key for key in _REQUIRED if key not in record]
        if missing:
            raise SystemExit(f"house view {record.get('id')!r} is missing {missing}")
        out.append(record)
    if not out:
        raise SystemExit("the shipped corpus has no house views; nothing to ingest")
    return out


def ingest(project: str, location: str, data_store_id: str, rows: list[dict[str, Any]]) -> None:
    """Write each record into the data store, replacing one that already carries its id."""
    from google.api_core.exceptions import AlreadyExists  # lazy
    from google.cloud import discoveryengine_v1 as de  # lazy

    client = de.DocumentServiceClient()
    parent = client.branch_path(
        project=project,
        location=location,
        data_store=data_store_id,
        branch="default_branch",
    )
    for row in rows:
        document = de.Document(
            id=row["id"],
            struct_data=row,
        )
        try:
            client.create_document(
                request=de.CreateDocumentRequest(
                    parent=parent, document=document, document_id=row["id"]
                )
            )
            print(f"  created {row['id']}")
        except AlreadyExists:
            document.name = f"{parent}/documents/{row['id']}"
            client.update_document(request=de.UpdateDocumentRequest(document=document))
            print(f"  updated {row['id']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", default="", help="the GCP project holding the data store")
    parser.add_argument("--data-store", default="", help="data store id (default: settings)")
    parser.add_argument("--location", default="", help="store location (default: settings)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the records that would be written and stop (no credentials needed)",
    )
    args = parser.parse_args(argv)

    settings = Settings.load()
    data_store_id = args.data_store or settings.house_views.data_store_id
    location = args.location or settings.house_views.location
    rows = records()

    if args.dry_run:
        print(f"dry run: {len(rows)} house views for {data_store_id} in {location}")
        for row in rows:
            print(json.dumps(row))
        return 0

    project = args.project or settings.project_id
    if not project or project == "your-gcp-project":
        raise SystemExit("--project is required (or set GOOGLE_CLOUD_PROJECT)")
    print(f"ingesting {len(rows)} house views into {project}/{location}/{data_store_id}")
    ingest(project, location, data_store_id, rows)
    print("done. Verify: CIO_PROFILE=gcp cio-advisory briefing client-000042")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
