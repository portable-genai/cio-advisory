"""The half of the model-pills contract that lives in the BROWSER.

Every served console shows two small pills at the top right of every page: the model that
ANSWERED the last request, and ``Search`` when that answer used an online search tool (owner
decision, 2026-09-23). They replaced the full-width provenance banner, which named the model
configuration would call rather than the one that answered. The SERVICE half (the profile
implies a runtime, ``generator_model`` is read off the binding, the answer headers are emitted
and exposed to a cross-origin console) is pinned in ``tests/unit/test_health_provenance.py``
and ``tests/unit/test_answer_provenance.py`` and is not restated here.

This file pins the other half, because that is the half that broke before. On 2026-09-04 eight
consoles were found to have rendered NOTHING on every page load since the banner landed: the
component named ``/api/agent``, the same-origin route handler the service template ships, in
trees that ship no such handler. The health call reached a path nothing serves, took the failure
branch, and the failure branch renders nothing, deliberately. A check that cannot fail loudly
fails as an ABSENCE, and an absent strip is exactly what no reviewer notices. Every service-side
assertion was green throughout, which is why these live in their own file.

``ui/tests/answer-provenance.test.mjs`` proves the fetch wrapper itself in node.
"""

from __future__ import annotations

import re
from pathlib import Path

UI = Path("ui")
PILLS = UI / "components" / "ModelPills.tsx"
WATCHER = UI / "lib" / "answer-provenance.mjs"


def _code_only(source: str) -> str:
    """``source`` without ``//`` and ``/* */`` comments, so a comment cannot satisfy a check."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"(?m)^\s*//.*$", "", source)


def _rule(css: str, selector: str) -> str:
    """The body of one CSS rule; fails when the stylesheet does not carry it."""
    opening = f"{selector} {{"
    assert opening in css, f"ui/app/globals.css has no {selector} rule"
    start = css.index(opening)
    return css[start : css.index("}", start)]


def test_the_console_shows_the_model_that_answered_as_pills_not_a_banner() -> None:
    """The whole chain, from the offline gate.

    The pills start from ``/healthz``, read both answer headers through the one fetch wrapper,
    and are mounted in the layout. The old banner and its sentence are gone: a second component
    naming the model from configuration would contradict the pill on every answered page.
    """
    assert PILLS.is_file(), "the console has no model pills"
    pills = _code_only(PILLS.read_text(encoding="utf-8"))
    assert "/healthz" in pills, "the pills do not start from the service's own /healthz"
    assert "watchAnswers(window" in pills, "the pills do not read the answer headers"
    assert "generator_model" in pills and "runtime" in pills
    assert 'data-testid="model-pills"' in pills
    watcher = WATCHER.read_text(encoding="utf-8")
    for header in ('"x-answered-by"', '"x-search-used"'):
        assert header in watcher, "the pills never read " + header
    assert not (UI / "components" / "ProvenanceBanner.tsx").exists(), "the old banner is back"
    for source in sorted(UI.glob("**/*.tsx")):
        if "node_modules" in source.parts or ".next" in source.parts:
            continue
        assert "ProvenanceBanner" not in source.read_text(encoding="utf-8"), source
    assert (UI / "tests" / "answer-provenance.test.mjs").is_file()


def test_the_pills_are_mounted_in_the_layout_rather_than_in_a_page() -> None:
    """Being at the top of EVERY page is a property of the console, not of any page.

    Mounted per page, the pills are present on the pages somebody remembered and absent on the
    one a screenshot came from, and the absence is invisible, because they render nothing until
    the service answers anyway. The layout is the only mount a new route cannot forget.
    """
    layout = (UI / "app" / "layout.tsx").read_text(encoding="utf-8")
    assert "<ModelPills />" in _code_only(layout), "the pills are not mounted on every page"


def test_the_pills_read_the_same_base_the_console_serves() -> None:
    """The defect that shipped in eight consoles, stated as an assertion.

    This console has no ``/api/agent`` proxy route: the browser calls the service directly at
    ``API_BASE``, resolved once in ``ui/lib/api`` from ``NEXT_PUBLIC_API_BASE``. The pills'
    health call and their header watcher must use that same base. A base of their own would be
    silently refused by the ``connect-src`` built from the shared one, and a watcher keyed on
    ``/api/agent`` would never match a single response, leaving the pill configured forever.
    """
    assert not (UI / "app" / "api" / "agent").exists(), (
        "this console now ships an /api/agent proxy; the pills must use it, and that route "
        "must forward x-answered-by and x-search-used"
    )
    pills = _code_only(PILLS.read_text(encoding="utf-8"))
    assert re.search(r'import \{ API_BASE \} from "@/lib/api"', pills), (
        "the pills must reach the service through the base the rest of this console reads"
    )
    assert "`${API_BASE}/healthz`" in pills
    assert "watchAnswers(window, API_BASE," in pills
    assert '"/api/agent"' not in pills and '"/api/agent"' not in _code_only(
        WATCHER.read_text(encoding="utf-8")
    )


def test_the_cross_origin_service_exposes_both_headers_to_the_console() -> None:
    """A cross-origin response hides every header CORS does not list, so the service lists both.

    Asserted on the source here and on a real response in ``test_answer_provenance.py``.
    """
    app = Path("src/cio_advisory/api/app.py").read_text(encoding="utf-8")
    assert 'expose_headers=["X-Answered-By", "X-Search-Used"]' in app
    assert "\ninstall_answer_provenance(app)\n" in app


def test_the_pills_sit_fixed_at_the_top_right_where_a_reader_can_see_them() -> None:
    """A pill that renders off-screen or under the page has satisfied every other check here.

    The old strip once rendered 32px ABOVE the viewport in eight trees: present in the DOM,
    holding the right text, visible on no page. Fixed to the viewport's top right, with a
    non-negative offset and a stacking order above the panels, the pills cannot scroll away or
    be pulled out of view.
    """
    css = (UI / "app" / "globals.css").read_text(encoding="utf-8")
    assert ".provenance-banner" not in css
    rule = _rule(css, ".model-pills")
    assert re.search(r"^\s*position:\s*fixed;", rule, re.MULTILINE)
    for side in ("top", "right"):
        match = re.search(rf"^\s*{side}:\s*(\d+)px;", rule, re.MULTILINE)
        assert match, f".model-pills is not anchored by a non-negative px {side}"
    z_index = re.search(r"^\s*z-index:\s*(\d+);", rule, re.MULTILINE)
    assert z_index and int(z_index.group(1)) > 0
    for state in (".model-pill.configured", ".model-pill.answered", ".model-pill.search"):
        assert re.search(r"\bbg-", _rule(css, state)), f"{state} has no opaque background"
