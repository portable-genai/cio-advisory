"""F2: the presenter demo is driven through a real headless browser, not a string.

``scripts/demo_selftest.py`` starts the real server and reads the served bytes, which
covers the server/renderer path browserlessly. This file closes the other half: a pinned
headless Chromium loads the SERVED pages, clicks the presenter's own ``Next`` button, and
reads every asserted figure back out of the LIVE DOM through the stable ``data-*``
evidence hooks. Nothing here is compared against hard-coded prose; every expectation is
recomputed from the running :class:`DemoSession`.

Playwright is pinned in the ``[demo]`` extra. The browser binary is a network download, so
a fork's day-one offline gate (D3) must not depend on it: the module skips LOUDLY when the
browser is absent, and ``make demo-browser`` runs it for anyone who has the extra.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="the pinned [demo] extra is not installed"
)


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


render = _load("render_cio_ui")
demo_server = _load("cio_demo_server")


@pytest.fixture(scope="module")
def served() -> Iterator[tuple[str, dict]]:
    """The REAL demo server, on an ephemeral port, for the duration of the module."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), demo_server.Handler)
    server.session = demo_server.DemoSession()
    server.lock = threading.Lock()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", server.session.data
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def page() -> Iterator[Any]:
    try:
        with playwright_api.sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as exc:  # pragma: no cover - environment-dependent
                pytest.skip(f"no pinned browser binary available: {exc}")
            context = browser.new_context()
            yield context.new_page()
            context.close()
            browser.close()
    except NotImplementedError as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"playwright cannot run here: {exc}")


def test_the_served_demo_walks_every_step_in_a_real_browser(
    page: Any, served: tuple[str, dict]
) -> None:
    base, data = served
    page.goto(f"{base}/restart", wait_until="load")

    steps = demo_server.STEPS

    for index, step in enumerate(steps):
        bar = page.locator("[data-demo='presenter-step']")
        assert bar.get_attribute("data-step") == str(index)

        client = data["clients"][step["client"]]
        points = client["talking_points"]

        # Figures read out of the LIVE DOM, checked against the running app.
        header = page.locator("[data-panel='briefing-header']")
        assert header.get_attribute("data-briefing-client") == client["client_id"]
        assert header.get_attribute("data-briefing-points") == str(len(points))
        assert header.get_attribute("data-briefing-flagged") == str(render.flagged_count(points))
        assert header.get_attribute("data-briefing-citations") == str(render.citation_count(points))
        assert (
            header.get_attribute("data-briefing-review")
            == str(bool(client["requires_human_review"])).lower()
        )

        for panel in ("briefing-header", "not-advice-banner", "talking-points", "alignment"):
            assert page.locator(f"[data-panel='{panel}']").count() == 1, panel

        panel = page.locator("[data-panel='talking-points']")
        assert panel.get_attribute("data-point-count") == str(len(points))
        assert panel.get_attribute("data-point-flagged") == str(render.flagged_count(points))

        rendered_verdicts = page.locator("[data-point-verdict]").evaluate_all(
            "els => els.map(e => e.getAttribute('data-point-verdict'))"
        )
        assert rendered_verdicts == [
            tp["suitability"]["verdict"] if tp["suitability"] else "review" for tp in points
        ]

        rendered_themes = page.locator("[data-point-theme]").evaluate_all(
            "els => els.map(e => e.getAttribute('data-point-theme'))"
        )
        assert rendered_themes == [tp["house_view_theme"] for tp in points]

        rendered_sources = page.locator("[data-citation-source]").evaluate_all(
            "els => els.map(e => e.getAttribute('data-citation-source'))"
        )
        expected_sources = [c["source_id"] for tp in points for c in tp["citations"]]
        assert expected_sources, "the running app produced no citations to prove"
        assert rendered_sources == expected_sources

        alignment = client["alignment"]
        rendered_alignment = page.locator("[data-align-count]").evaluate_all(
            "els => els.map(e => e.getAttribute('data-align-count'))"
        )
        assert rendered_alignment == [
            str(len(alignment["themes_in_line"])),
            str(len(alignment["gaps"])),
            str(len(alignment["overweights"])),
        ]

        if index < len(steps) - 1:
            page.locator("button.next:not([disabled])").click()
            page.wait_for_load_state("load")

    assert page.locator("button.next[disabled]").count() == 1
    assert "Maker-checker review gate" in page.content()


def test_the_index_page_serves_every_live_client_figure_in_the_browser(
    page: Any, served: tuple[str, dict]
) -> None:
    base, data = served
    page.goto(f"{base}/index", wait_until="load")

    assert page.locator("[data-panel='clients']").count() == 1
    rows = page.locator("[data-client-row]").evaluate_all(
        "els => els.map(e => ({"
        "id: e.getAttribute('data-client-row'),"
        "points: e.getAttribute('data-client-points'),"
        "flagged: e.getAttribute('data-client-flagged'),"
        "citations: e.getAttribute('data-client-citations'),"
        "review: e.getAttribute('data-client-review')}))"
    )
    assert rows == [
        {
            "id": c["client_id"],
            "points": str(len(c["talking_points"])),
            "flagged": str(render.flagged_count(c["talking_points"])),
            "citations": str(render.citation_count(c["talking_points"])),
            "review": str(bool(c["requires_human_review"])).lower(),
        }
        for c in data["clients"]
    ]
