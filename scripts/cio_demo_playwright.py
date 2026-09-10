"""Presenter-controlled Playwright walkthrough of the live CIO advisory demo.

Drives a headed browser through the suitability-checked advisory briefings served by
``scripts/cio_demo_server.py``. It is **paced by the presenter**: before each step it
prints what is about to happen and waits for you to press Enter, then performs the action
(click "Next") and highlights the panel to look at. You stay in control of timing.

Usage (two terminals)::

    # terminal 1: the live demo server
    PYTHONPATH=src python scripts/cio_demo_server.py

    # terminal 2: the guided walkthrough (a real Chrome window opens)
    pip install playwright && playwright install chromium     # one-time
    python scripts/cio_demo_playwright.py

You can also point this at the real Next.js console instead of the demo server by setting
``DEMO_URL`` (e.g. ``DEMO_URL=http://localhost:3000`` with ``make run-ui`` +
``make run-api PROFILE=local``), then drive it manually. The narration still applies.

Environment overrides:
    DEMO_URL    server base URL (default http://127.0.0.1:8099)
    HEADLESS=1  run headless (used for the self-test; no window)
    DEMO_AUTO=1 don't wait for Enter, advance automatically (self-test / recording)
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
        "Start with the client, not the report. This is client-000042's portfolio against "
        "the model portfolio the bank publishes for a balanced profile. They hold 30 percent "
        "equity where the target is 45 with a floor of 35, so they are 15 points short: "
        "180,000 dollars short, on a 1.2 million book. And 35 percent sits in cash against a "
        "ceiling of 10. Every one of those figures is arithmetic, not a model's opinion.",
        False,
        "[data-panel='portfolio']",
    ),
    (
        "Now the house view, read against that portfolio. Each talking point is cited back "
        "to a CIO article, carries a suitability verdict, and says which gap it closes: the "
        "AI infrastructure theme is the one that would take equity towards its target. Note "
        "the amber banner: decision-support, not financial advice.",
        True,
        ".banner",
    ),
    (
        "Theme by theme, and the honest line at the bottom. This client is also short of "
        "alternatives and real assets, and today's report offers nothing that closes either. "
        "The briefing says so rather than inventing a theme to fill the space.",
        True,
        ".align",
    ),
    (
        "A second client, and the same house views. client-000077 is conservative and "
        "retail, ESG-only and no-illiquid, and they are 20 points short of equity: a larger "
        "gap than the first client's, and 160,000 dollars.",
        True,
        "[data-panel='portfolio']",
    ),
    (
        "Here is the moment worth slowing down for. The theme that would close that equity "
        "gap is the same AI infrastructure theme, and it is NOT in this client's points: the "
        "suitability policy dropped it as UNSUITABLE for a conservative client, and the "
        "engine will not present it however large the gap is. The rest flag REVIEW. A gap is "
        "a reason to talk, never a reason to override the suitability check.",
        True,
        ".verdict",
    ),
    (
        "Theme by theme for the conservative client, for contrast with the first.",
        True,
        ".align",
    ),
    (
        "A third client, where the threat is the story. client-000418 holds 25 percent in "
        "real assets against a 5 to 15 band, and the commercial real estate theme names the "
        "REIT fund carrying it. That link comes from the instrument's own tags, not from the "
        "model guessing which holding a theme is about.",
        True,
        "[data-panel='portfolio']",
    ),
    (
        "Maker-checker: every briefing always requires human review (P-06). The RM is the "
        "human checker; the assistant is only the maker. Every talking point is cited back "
        "to a CIO house view, and every figure beside it can be recomputed by hand.",
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

        print("\n=== CIO advisory live demo: press Enter to advance each step ===\n")
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
