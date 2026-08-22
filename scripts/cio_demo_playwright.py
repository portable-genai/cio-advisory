"""Presenter-controlled Playwright walkthrough of the live CIO advisory demo.

Drives a headed browser through the suitability-checked advisory briefings served by
``scripts/cio_demo_server.py``. It is **paced by the presenter**: before each step it
prints what is about to happen and waits for you to press Enter, then performs the action
(click "Next") and highlights the panel to look at. You stay in control of timing.

Usage (two terminals)::

    # terminal 1 — the live demo server
    PYTHONPATH=src python scripts/cio_demo_server.py

    # terminal 2 — the guided walkthrough (a real Chrome window opens)
    pip install playwright && playwright install chromium     # one-time
    python scripts/cio_demo_playwright.py

You can also point this at the real Next.js console instead of the demo server by setting
``DEMO_URL`` (e.g. ``DEMO_URL=http://localhost:3000`` with ``make run-ui`` +
``make run-api PROFILE=local``), then drive it manually — the narration still applies.

Environment overrides:
    DEMO_URL    server base URL (default http://127.0.0.1:8099)
    HEADLESS=1  run headless (used for the self-test; no window)
    DEMO_AUTO=1 don't wait for Enter — advance automatically (self-test / recording)
    SLOWMO_MS   per-action slow-motion in ms (default 250 headed, 0 headless)
    CHROME_PATH explicit Chromium/Chrome binary (else Playwright's own)
"""

from __future__ import annotations

import contextlib
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("DEMO_URL", "http://127.0.0.1:8099")
HEADLESS = os.environ.get("HEADLESS") == "1"
AUTO = os.environ.get("DEMO_AUTO") == "1"
SLOWMO = int(os.environ.get("SLOWMO_MS", "0" if HEADLESS else "250"))
CHROME_PATH = os.environ.get("CHROME_PATH") or None

# (narration shown in the terminal, whether this step clicks "Next", panel to spotlight)
STEPS = [
    (
        "Balanced client (client-000042). The assistant has run the full offline pipeline "
        "— redact, guardrail, retrieve CIO house views, synthesise — and the cited TALKING "
        "POINTS are on screen, each with a suitability verdict pill. Note the amber "
        "not-advice banner: this is decision-support, not financial advice.",
        False,
        ".banner",
    ),
    (
        "Portfolio alignment for the balanced client — which OVERWEIGHT house-view themes "
        "the portfolio already reflects (in line), which it under-holds (gaps), and where a "
        "single asset class is at or above the concentration limit (overweights).",
        True,
        ".align",
    ),
    (
        "Now the conservative, retail client (client-000077). Watch the SAME CIO house "
        "views earn different verdicts: the aggressive equity overweight is dropped as "
        "UNSUITABLE, and the others flag REVIEW (ESG-only constraint, concentration, "
        "knowledge). The suitability policy is a pure, replayable function.",
        True,
        ".verdict",
    ),
    (
        "Portfolio alignment for the conservative client — a different picture: the AI "
        "infrastructure theme is a gap, and the bond/cash concentration shows as "
        "overweights.",
        True,
        ".align",
    ),
    (
        "Maker-checker — every briefing always requires human review (P-06). The RM is the "
        "human checker; the assistant is only the maker. Every talking point is cited back "
        "to a CIO house view, so a reviewer can trace each claim.",
        True,
        ".banner",
    ),
]


def _pause(prompt: str) -> None:
    if AUTO:
        time.sleep(1.2)
        return
    try:
        input(prompt)
    except EOFError:  # non-interactive stdin
        time.sleep(1.0)


def _spotlight(page, selector: str | None) -> None:
    if not selector:
        return
    with contextlib.suppress(Exception):  # cosmetic only
        page.eval_on_selector_all(
            selector,
            "els => els.forEach((e,i)=>{ if(i<6){ e.style.transition='box-shadow .3s';"
            " e.style.boxShadow='0 0 0 3px #3a60f0'; setTimeout(()=>e.style.boxShadow='',1600);} })",
        )


def _reachable() -> bool:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(BASE + "/state", timeout=2):
            return True
    except (urllib.error.URLError, OSError):
        return False


def main() -> int:
    if not _reachable():
        print(f"Cannot reach the demo server at {BASE}.")
        print("Start it first:  PYTHONPATH=src python scripts/cio_demo_server.py")
        return 2

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS, slow_mo=SLOWMO, executable_path=CHROME_PATH)
        page = browser.new_context(viewport={"width": 1100, "height": 900}).new_page()

        print("\n=== CIO advisory live demo — press Enter to advance each step ===\n")
        page.goto(BASE + "/restart", wait_until="load")  # always start clean
        page.goto(BASE + "/", wait_until="load")

        for i, (say, click, spotlight) in enumerate(STEPS):
            print(f"[{i + 1}/{len(STEPS)}] {say}")
            _pause("        press Enter to run this step... ")
            if click:
                btn = page.locator(".democtl button.next")
                if btn.count() and btn.is_enabled():
                    btn.click()
                    page.wait_for_load_state("load")
            page.wait_for_timeout(200)
            _spotlight(page, spotlight)
            page.wait_for_timeout(700)
            print()

        print("Demo complete. The browser stays open for questions.")
        _pause("        press Enter to close the browser... ")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
