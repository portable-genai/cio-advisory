#!/usr/bin/env python3
"""Load the shipped CIO house views into the managed Agent Search store, through the gcp adapter.

The laptop grounds a briefing on the fictional corpus in ``cio_advisory/data/demo_book/``
through SQLite FTS5. This puts the same themes into the Agent Search store the standalone
``gcp`` profile searches, so the two surfaces ground on one report.

It writes through :meth:`FileSearchHouseViewAdapter.sync`, the class the ``gcp`` profile binds
for retrieval, rather than through a second client of its own. The project comes from
``--project`` (or ``GOOGLE_CLOUD_PROJECT``); the location, the data store and the host come from
the same settings the serving API reads (``CIO_HOUSE_VIEWS_LOCATION`` in
``config/settings.yaml``), and there is deliberately no flag to point the load anywhere else. A
loader that can write to a location the API does not read is how a store ends up full while
every briefing reports it empty.

**It will not decide the tenant.** Every document carries the tenant that owns it, and a
briefing only cites a tagged house view whose tenant is the verified caller's
(``domain/entitlements.py``). On a deployment that is the tenant the identity adapter resolves,
which the embedding host's tenant map decides. A document under any other value never reaches a
briefing, and that reads exactly like an empty store. So ``--tenant`` is required.

**Re-running is safe.** A document already holding the same record is not written, one whose
record differs is updated, a missing one is created, and a document under a loaded id that
another tenant owns stops the run before anything is written. Documents this tenant holds that
the corpus no longer names are listed, never deleted.

What this is NOT: a governed publication pipeline. A bank ingests its own CIO articles through
whatever already publishes them. The records written here are fictional, and every URL is under
``example.test``, which is not a real domain.

Usage::

    python scripts/ingest_house_views.py --project <id> --tenant <tenant> --dry-run
    python scripts/ingest_house_views.py --project <id> --tenant <tenant>

``--dry-run`` prints the destination and the exact records a load would write, and needs no
credentials and no ``[gcp]`` extra.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from cio_advisory import demo_book  # noqa: E402
from cio_advisory.adapters.gcp.file_search_house_views import (  # noqa: E402
    FileSearchHouseViewAdapter,
    house_view_record,
)
from cio_advisory.config import Settings  # noqa: E402
from cio_advisory.domain.models import HouseView  # noqa: E402

#: The project id ``config/settings.yaml`` carries when ``GOOGLE_CLOUD_PROJECT`` is unset.
_PLACEHOLDER_PROJECT = "your-gcp-project"


def corpus() -> tuple[HouseView, ...]:
    """The shipped house views, refused when the book is broken or holds none."""
    demo_book.validate()
    views = demo_book.house_views()
    if not views:
        raise SystemExit("the shipped corpus has no house views; nothing to load")
    return views


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--project",
        default="",
        help="the GCP project holding the store (default: GOOGLE_CLOUD_PROJECT)",
    )
    parser.add_argument(
        "--tenant",
        required=True,
        help=(
            "the owning tenant to stamp on every document. On a deployment this is the tenant "
            "the identity adapter resolves for the people who will be briefed; a document under "
            "any other value never reaches a briefing."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the destination and the records a load would write, and stop",
    )
    args = parser.parse_args(argv)

    tenant = args.tenant.strip()
    if not tenant:
        raise SystemExit("--tenant names nothing; pass the tenant the deployment resolves")

    settings = Settings.load()
    project = args.project.strip() or settings.project_id
    views = corpus()
    records = [house_view_record(view, tenant) for view in views]

    if args.dry_run:
        adapter = FileSearchHouseViewAdapter(
            dataclasses.replace(settings, project_id=project or _PLACEHOLDER_PROJECT)
        )
        print(f"dry run: {len(records)} house views as tenant {tenant!r}, nothing written")
        print(f"  store:    {adapter.branch}")
        print(f"  endpoint: {adapter.endpoint}")
        for record in records:
            print(json.dumps(record, sort_keys=True))
        return 0

    if not project or project == _PLACEHOLDER_PROJECT:
        raise SystemExit("--project is required (or set GOOGLE_CLOUD_PROJECT)")
    adapter = FileSearchHouseViewAdapter(dataclasses.replace(settings, project_id=project))
    print(f"loading {len(views)} house views into {adapter.branch} as tenant {tenant!r}")
    print(f"  endpoint: {adapter.endpoint}")
    report = adapter.sync(views, tenant)
    for label, ids in (
        ("created", report.created),
        ("updated", report.updated),
        ("unchanged", report.unchanged),
    ):
        print(f"  {label}: {len(ids)}" + (f" ({', '.join(ids)})" if ids else ""))
    if report.stale:
        print(f"  stale, still retrievable, not deleted: {', '.join(report.stale)}")
    print("done. Verify with a briefing through the deployed console as a user of that tenant.")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
