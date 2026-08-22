"""Runnable demo of the B3 advisory-briefing flow (synthetic, fictional data).

Builds the suitability-checked advisory briefing for each built-in synthetic client
(``client-000042`` balanced/informed, ``client-000077`` conservative/retail) through the
*real* :class:`~cio_advisory.domain.services.AdvisoryService` pipeline on the ``local``
profile: redact -> guardrail(INPUT) -> load profile + portfolio -> retrieve CIO house
views (local SQLite FTS5) -> synthesise talking points + per-theme suitability -> drop
UNSUITABLE -> portfolio alignment -> guardrail(OUTPUT) -> maker-checker (always requires
review) -> audit.

Run it::

    PYTHONPATH=src python scripts/cio_demo.py [out.json]

It prints a per-client summary (talking points, suitability verdicts, alignment) and
writes the full artifact JSON (one entry per client) for the UI to render. No Google
Cloud, no API key, no LLM call: the local deterministic LLM narrates and the suitability
policy is a pure function (replayable by a reviewer). The headline of the demo is that the
SAME CIO house views earn different suitability verdicts for the two clients.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from cio_advisory.api import deps
from cio_advisory.config import Settings, build_container
from cio_advisory.domain.identity import Principal
from cio_advisory.domain.serialization import to_jsonable

# The two synthetic clients the local corpus ships with (opaque, non-PII ids).
CLIENTS: list[tuple[str, str]] = [
    ("client-000042", "Balanced, informed; capital-growth + income; SG"),
    (
        "client-000077",
        "Conservative, retail; capital-preservation + income; ESG-only, no-illiquid; SG",
    ),
]
# The verified principal the demo acts as: a same-tenant (demo-bank) RM entitled to the
# seeded clients. Object authorization (domain/entitlements.py) is enforced against it.
ACTOR = "demo:rm"
PRINCIPAL = Principal(
    subject=ACTOR, principals=("group:cio-analyst",), tenant="demo-bank", source="demo"
)


def build_service() -> tuple[Any, Settings]:
    """Assemble the real AdvisoryService on the local (offline) profile.

    Forces ``CIO_PROFILE=local`` so the demo never reaches for Google Cloud, regardless
    of any ambient config in the environment or ``config/settings.yaml``.
    """
    os.environ["CIO_PROFILE"] = "local"
    settings = Settings.load()
    if settings.profile != "local":
        object.__setattr__(settings, "profile", "local")
    container = build_container(settings)
    return deps.build_advisory_service(container), settings


def _summarise_point(tp: Any) -> dict:
    a = tp.suitability
    return {
        "headline": tp.headline,
        "body": tp.body,
        "house_view_theme": tp.house_view_theme,
        "linked_holdings": list(tp.linked_holdings),
        "is_advice": tp.is_advice,
        "suitability": (
            {
                "theme": a.theme,
                "verdict": a.verdict.value,
                "rationale": a.rationale,
                "factors": [to_jsonable(f) for f in a.factors],
            }
            if a is not None
            else None
        ),
        "citations": [to_jsonable(c) for c in tp.citations],
    }


def _summarise_client(svc: Any, client_id: str, descriptor: str) -> dict:
    briefing = svc.brief(client_id, PRINCIPAL)
    return {
        "client_id": client_id,
        "descriptor": descriptor,
        "requires_human_review": briefing.requires_human_review,
        "not_advice_disclaimer": briefing.not_advice_disclaimer,
        "talking_points": [_summarise_point(tp) for tp in briefing.talking_points],
        "alignment": to_jsonable(briefing.alignment),
        "generated_at": briefing.generated_at.isoformat(),
    }


def build_payload(svc: Any | None = None, settings: Settings | None = None) -> dict:
    """Build the full advisory-artifact payload (one entry per synthetic client).

    Reusable by the live demo server so the click-through and the static artifacts come
    from one source of truth.
    """
    if svc is None or settings is None:
        svc, settings = build_service()
    return {
        "profile": settings.profile,
        "region": settings.region,
        "clients": [_summarise_client(svc, cid, desc) for cid, desc in CLIENTS],
    }


def _print_summary(payload: dict) -> None:
    print(
        f"B3 CIO Advisory Assistant — offline demo "
        f"(profile={payload['profile']}, {payload['region']})\n"
    )
    for client in payload["clients"]:
        points = client["talking_points"]
        print(f"== Client {client['client_id']}  ({client['descriptor']})")
        print(
            f"   talking points: {len(points)}   "
            f"requires_human_review={client['requires_human_review']}"
        )
        for i, tp in enumerate(points, start=1):
            a = tp["suitability"]
            verdict = a["verdict"] if a else "n/a"
            cites = ", ".join(c["source_id"] for c in tp["citations"]) or "none"
            print(f"   {i}. [{verdict.upper():10}] {tp['headline']}  <- {cites}")
        align = client["alignment"]
        print(
            "   alignment: "
            f"in-line={', '.join(align['themes_in_line']) or 'none'} | "
            f"gaps={', '.join(align['gaps']) or 'none'} | "
            f"overweights={', '.join(align['overweights']) or 'none'}\n"
        )


def main(out_path: str) -> None:
    payload = build_payload()
    _print_summary(payload)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"Wrote advisory-artifact JSON -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "cio_demo.json")
