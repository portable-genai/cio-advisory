#!/usr/bin/env python3
"""Load the shipped fictional client book into the managed BigQuery dataset.

The laptop reads the book from DuckDB and the deployment reads it from BigQuery. This is
what puts the same rows in the second place, from the same NDJSON files, so the two surfaces
can be compared rather than merely both work.

Two things it will not do.

**It will not overwrite a book it did not write.** It truncates and reloads, which is right
for a demo book and catastrophic for a real one, so it proceeds only when every target table
is empty or the dataset's own ``book_manifest`` says what it holds is fictional. That guard
is ``cio_advisory.demo_book.may_overwrite``, the same function the DuckDB store calls, so
the rule is proved once and cannot drift between the two stores.

**It will not decide the tenant.** On a deployment the tenant is whatever the identity
adapter resolves from the IAP assertion, usually the hosted domain, and rows loaded under
any other value are invisible to every real user because the entitlement gate fails closed.
So ``--tenant`` is required, and ``client-000999`` (the shipped ``other-bank`` client, which
exists to prove the gate) is loaded under a second tenant derived from it rather than
silently folded into the first.

Usage::

    python scripts/load_demo_book.py --project <id> --tenant <hosted-domain> --dry-run
    python scripts/load_demo_book.py --project <id> --tenant <hosted-domain>

``--dry-run`` writes the NDJSON it would load to a directory and stops, which is how the
rows get reviewed before anything reaches a dataset. It needs no credentials and no
``[gcp]`` extra: the BigQuery import is inside the function that loads.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from cio_advisory import demo_book  # noqa: E402
from cio_advisory.config import Settings  # noqa: E402

#: The shipped tenant these rows carry, and the one every client but the gate-proof uses.
_SHIPPED = demo_book.SHIPPED_TENANT

#: The shipped client that belongs to a DIFFERENT tenant on purpose: a demo-bank persona
#: must not be able to list or brief it. Loading it under the same tenant as the rest would
#: quietly delete the only evidence the tenant gate does anything.
_OTHER_TENANT_CLIENT = "client-000999"


def _source_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _retenant(table: str, row: dict[str, Any], tenant: str) -> dict[str, Any]:
    """Rewrite the shipped tenant to the deployment's, keeping the gate-proof separate."""
    if table not in ("client_profiles", "book_manifest") or "tenant" not in row:
        return row
    if row.get("client_id") == _OTHER_TENANT_CLIENT:
        return dict(row, tenant=f"{tenant}-other")
    return dict(row, tenant=tenant)


def rows_to_load(tenant: str) -> dict[str, list[dict[str, Any]]]:
    """The rows this run would write, per table, with the tenant and manifest resolved."""
    demo_book.validate()
    loaded_at = datetime.now(UTC).isoformat()
    commit = _source_commit()
    out: dict[str, list[dict[str, Any]]] = {}
    for table in demo_book.TABLES:
        rows = [_retenant(table, row, tenant) for row in demo_book.rows(table)]
        if table == "book_manifest":
            rows = [dict(row, loaded_at=loaded_at, source_commit=commit) for row in rows]
        out[table] = rows
    return out


def write_ndjson(rows: dict[str, list[dict[str, Any]]], out_dir: Path) -> list[Path]:
    """Write the rows as one NDJSON file per table and return the paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for table, table_rows in rows.items():
        path = out_dir / f"{table}.ndjson"
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in table_rows),
            encoding="utf-8",
        )
        written.append(path)
    return written


def _existing(client: Any, dataset_ref: str, tables: tuple[str, ...]) -> dict[str, int]:
    """Row count per target table; a table that does not exist counts as absent, not zero."""
    from google.cloud import bigquery  # lazy
    from google.cloud.exceptions import NotFound

    counts: dict[str, int] = {}
    for table in tables:
        try:
            table_ref = bigquery.TableReference.from_string(f"{dataset_ref}.{table}")
            counts[table] = int(client.get_table(table_ref).num_rows)
        except NotFound:
            raise SystemExit(
                f"table {dataset_ref}.{table} does not exist. Apply infra/terraform first: "
                "the loader fills tables, it never creates them."
            ) from None
    return counts


def _manifest_rows(client: Any, dataset_ref: str) -> list[dict[str, Any]]:
    query = f"SELECT fictional FROM `{dataset_ref}.book_manifest`"
    return [dict(row) for row in client.query(query).result()]


def load(project: str, dataset: str, rows: dict[str, list[dict[str, Any]]], location: str) -> None:
    """Truncate and reload every target table, once the overwrite guard allows it."""
    from google.cloud import bigquery  # lazy

    client = bigquery.Client(project=project, location=location)
    dataset_ref = f"{project}.{dataset}"
    counts = _existing(client, dataset_ref, demo_book.TABLES)
    manifest = _manifest_rows(client, dataset_ref) if counts.get("book_manifest") else []
    if not demo_book.may_overwrite(counts, manifest):
        held = ", ".join(f"{table}={count}" for table, count in sorted(counts.items()) if count)
        raise SystemExit(
            f"refusing to load: {dataset_ref} holds rows ({held}) and its book_manifest does "
            "not say they are fictional. This loader truncates; point it at an empty dataset "
            "or one holding a previous demo book."
        )
    for table in demo_book.TABLES:
        table_rows = rows[table]
        job = client.load_table_from_json(
            table_rows,
            f"{dataset_ref}.{table}",
            job_config=bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                schema_update_options=None,
            ),
        )
        job.result()
        print(f"  {table}: {len(table_rows)} rows")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", default="", help="the GCP project holding the dataset")
    parser.add_argument("--dataset", default="", help="dataset id (default: from settings.yaml)")
    parser.add_argument("--location", default="", help="BigQuery location (default: settings)")
    parser.add_argument(
        "--tenant",
        required=True,
        help=(
            "the owning tenant to stamp on every client row. On a deployment this is what "
            "the identity adapter resolves from the IAP assertion (the hosted domain); rows "
            "under any other value are invisible because the entitlement gate fails closed."
        ),
    )
    parser.add_argument(
        "--dry-run",
        metavar="DIR",
        nargs="?",
        const="build/demo-book",
        help="write the NDJSON that would be loaded to DIR and stop (no credentials needed)",
    )
    args = parser.parse_args(argv)

    settings = Settings.load()
    dataset = args.dataset or settings.bigquery.dataset
    location = args.location or settings.bigquery.location
    rows = rows_to_load(args.tenant)

    if args.dry_run is not None:
        out_dir = Path(args.dry_run)
        written = write_ndjson(rows, out_dir)
        total = sum(len(r) for r in rows.values())
        print(f"dry run: {total} rows for {dataset} (tenant {args.tenant!r}), not loaded")
        for path in written:
            print(f"  {path} ({len(rows[path.stem])} rows)")
        return 0

    project = args.project or settings.project_id
    if not project or project == "your-gcp-project":
        raise SystemExit("--project is required (or set GOOGLE_CLOUD_PROJECT)")
    print(f"loading the demo book into {project}.{dataset} as tenant {args.tenant!r}")
    load(project, dataset, rows, location)
    print("done. Verify: CIO_PROFILE=gcp cio-advisory briefing client-000418")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
