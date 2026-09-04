#!/usr/bin/env python3
"""Credential-free anti-rot check for the real cio-advisory presenter demo.

Two stages, both executed, neither reading hard-coded prose:

1. **In-process** -- the real :class:`DemoSession` builds the real advisory briefings and
   renders every presenter step.
2. **Served** -- the real ``ThreadingHTTPServer`` is started on an ephemeral port and the
   whole presenter journey is driven over HTTP with ``POST /advance``. Every figure
   asserted at this stage is read out of the SERVED bytes through the stable ``data-*``
   evidence hooks and compared with the value the RUNNING app computed, so a renderer that
   stops emitting a figure, a server that stops advancing, or a hook that gets renamed all
   fail here. A step that only rendered in-process was invisible to the old check.

The headless-browser journey over the same served pages lives in
``tests/browser/test_served_demo_ui.py`` and needs the pinned ``[demo]`` extra.
"""

from __future__ import annotations

import re
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import render_cio_ui as r
from cio_demo_server import STEPS, DemoSession, Handler


def _hooks(html: str, attribute: str) -> list[str]:
    """Every value of one stable ``data-*`` evidence hook, in document order.

    Both quoting styles are matched in a single pass: the renderer writes some hooks with
    single and some with double quotes, and a helper that tried one style then the other
    would silently see only half the page.
    """
    return [
        single or double
        for single, double in re.findall(rf"{attribute}=(?:'([^']*)'|\"([^\"]*)\")", html)
    ]


def _hook(html: str, attribute: str) -> str:
    """Read the FIRST occurrence of one stable ``data-*`` evidence hook."""
    found = _hooks(html, attribute)
    assert found, f"evidence hook {attribute} is missing from the served page"
    return found[0]


def check_in_process() -> None:
    session = DemoSession()
    opening = session.render()
    assert "decision-support" in opening.lower() and "data-demo='presenter-step'" in opening
    assert len(session.data["clients"]) == 2
    page = opening
    while not session.at_end:
        session.advance()
        page = session.render()
        assert f"data-step='{session.idx}'" in page
    flagged = session.data["clients"][1]["talking_points"]
    assert any(point["suitability"]["verdict"] in {"review", "unsuitable"} for point in flagged)
    assert session.idx == len(STEPS) - 1 and "Demo complete" in page
    print("PASS demo: two-client suitability contrast and review gate rendered")


def check_served() -> None:
    """Drive the REAL server over HTTP and assert live figures from served bytes."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.session = DemoSession()  # type: ignore[attr-defined]
    server.lock = threading.Lock()  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    data = server.session.data  # type: ignore[attr-defined]

    try:
        for index, step in enumerate(STEPS):
            with urllib.request.urlopen(f"{base}/", timeout=20) as response:  # noqa: S310
                assert response.status == 200
                page = response.read().decode("utf-8")

            # The served page is at the step the served app believes it is at.
            assert _hook(page, "data-step") == str(index), f"served step marker is not {index}"

            client = data["clients"][step["client"]]
            points = client["talking_points"]

            # Live figures: served bytes vs what the running app computed.
            assert _hook(page, "data-briefing-client") == client["client_id"]
            assert _hook(page, "data-briefing-points") == str(len(points))
            assert _hook(page, "data-briefing-flagged") == str(r.flagged_count(points))
            assert _hook(page, "data-briefing-citations") == str(r.citation_count(points))
            assert (
                _hook(page, "data-briefing-review")
                == str(bool(client["requires_human_review"])).lower()
            )

            panels = _hooks(page, "data-panel")
            for required in (
                "briefing-header",
                "not-advice-banner",
                "talking-points",
                "alignment",
            ):
                assert required in panels, f"served page lost the {required} panel hook"

            assert _hook(page, "data-point-count") == str(len(points))
            assert _hook(page, "data-point-flagged") == str(r.flagged_count(points))
            assert _hooks(page, "data-point-theme") == [tp["house_view_theme"] for tp in points]
            assert _hooks(page, "data-point-verdict") == [
                tp["suitability"]["verdict"] if tp["suitability"] else "review" for tp in points
            ]
            assert _hooks(page, "data-point-citations") == [
                str(len(tp["citations"])) for tp in points
            ]

            # Every citation the running app produced is chipped onto the served page.
            served_sources = _hooks(page, "data-citation-source")
            expected_sources = [c["source_id"] for tp in points for c in tp["citations"]]
            assert expected_sources, "the running app produced no citations to prove"
            assert served_sources == expected_sources

            alignment = client["alignment"]
            assert _hooks(page, "data-align") == ["in-line", "gaps", "overweights"]
            assert _hooks(page, "data-align-count") == [
                str(len(alignment["themes_in_line"])),
                str(len(alignment["gaps"])),
                str(len(alignment["overweights"])),
            ]

            if index < len(STEPS) - 1:
                request = urllib.request.Request(f"{base}/advance", method="POST", data=b"")
                with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
                    assert response.status in (200, 303)
            else:
                assert "Demo complete" in page

        # The audit-first index (the sources view across clients) must serve too, with the
        # live per-client citation and review figures the running app computed.
        with urllib.request.urlopen(f"{base}/index", timeout=20) as response:  # noqa: S310
            assert response.status == 200
            index_page = response.read().decode("utf-8")
        assert "clients" in _hooks(index_page, "data-panel")
        assert _hooks(index_page, "data-client-row") == [c["client_id"] for c in data["clients"]]
        assert _hooks(index_page, "data-client-citations") == [
            str(r.citation_count(c["talking_points"])) for c in data["clients"]
        ]
        assert _hooks(index_page, "data-client-flagged") == [
            str(r.flagged_count(c["talking_points"])) for c in data["clients"]
        ]
        assert _hooks(index_page, "data-client-review") == [
            str(bool(c["requires_human_review"])).lower() for c in data["clients"]
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    print(
        "PASS served: every presenter step, panel hook and live figure read back over "
        "HTTP from the running demo server"
    )


def main() -> int:
    check_in_process()
    check_served()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
