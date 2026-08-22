"""Render the audit-first B3 advisory UI from the demo JSON into static HTML pages.

Server-side, dependency-free rendering of the advisory briefing (one page per client
plus an index), faithful to the React/Next.js console in ``ui/`` (the not-advice banner,
the talking-point cards with suitability verdict pills + citation chips, the portfolio
alignment panel) and the existing palette (ink / regblue, Panel, Pill). Used to produce
screenshots / slide artifacts with the synthetic seed data.

    PYTHONPATH=src python scripts/render_cio_ui.py cio_demo.json out_dir/
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

VERDICT_COLOR = {
    "suitable": ("#ecfdf5", "#047857", "Suitable"),
    "review": ("#fffbeb", "#92400e", "Review"),
    "unsuitable": ("#fff1f2", "#be123c", "Unsuitable"),
}

CSS = """
:root{--ink-50:#f5f7fa;--ink-100:#e6ebf2;--ink-200:#cdd7e4;--ink-300:#a6b6cc;
--ink-400:#7790ae;--ink-500:#546b8b;--ink-600:#3f5470;--ink-700:#33445b;--ink-800:#1f2a3a;
--regblue-50:#eef4ff;--regblue-100:#dbe7ff;--regblue-600:#2945d6;--regblue-700:#2237ad;--regblue-800:#1b2c89;
--ok:#059669;--warn:#d97706;
--shadow:0 1px 2px rgba(11,16,26,.06),0 8px 24px rgba(11,16,26,.06);}
*{box-sizing:border-box}
body{margin:0;background:var(--ink-50);color:var(--ink-800);
font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;
font-size:14px;line-height:1.5;padding:24px 18px}
.wrap{max-width:900px;margin:0 auto}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
h1{font-size:18px;margin:0 0 2px}
.sub{color:var(--ink-500);font-size:13px;margin:0 0 16px}
.sub b{color:var(--ink-800)}
.banner{border:1px solid #fcd34d;background:#fffbeb;color:#92400e;border-radius:10px;padding:11px 14px;margin-bottom:16px}
.banner b{display:block;font-size:13px}
.banner p{margin:4px 0 0;font-size:12px;color:#a16207}
.panel{border:1px solid var(--ink-200);background:#fff;border-radius:12px;box-shadow:var(--shadow);margin-bottom:16px}
.panel>h2{border-bottom:1px solid var(--ink-100);padding:11px 16px;margin:0;font-size:13px;font-weight:600;color:var(--ink-700);
display:flex;justify-content:space-between;align-items:center;letter-spacing:.02em}
.panel>.body{padding:16px}
.pill{display:inline-flex;align-items:center;border-radius:999px;padding:2px 10px;font-size:11px;font-weight:600}
.pill.warn{background:#fef3c7;color:#92400e}
.pill.info{background:var(--regblue-100);color:var(--regblue-800)}
.tp{border:1px solid var(--ink-200);border-radius:10px;padding:12px 14px;margin-bottom:12px}
.tp:last-child{margin-bottom:0}
.tp .hd{display:flex;align-items:flex-start;gap:10px;justify-content:space-between}
.tp .hl{font-weight:600;font-size:14px;color:var(--ink-800)}
.tp .body{font-size:13px;color:var(--ink-600);margin:6px 0 0}
.verdict{font-size:10px;font-weight:700;text-transform:uppercase;padding:3px 9px;border-radius:6px;flex:none;white-space:nowrap}
.theme{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--regblue-700);background:var(--regblue-50);border:1px solid var(--regblue-100);border-radius:5px;padding:1px 6px}
.rationale{font-size:12px;color:var(--ink-500);margin-top:8px;padding:8px 10px;background:var(--ink-50);border-radius:7px;border:1px solid var(--ink-100)}
.holds{margin-top:8px;font-size:12px;color:var(--ink-500)}
.chips{margin-top:8px;display:flex;gap:6px;flex-wrap:wrap}
.chip{display:inline-flex;align-items:center;gap:5px;border:1px solid var(--ink-200);background:var(--ink-50);border-radius:6px;padding:2px 8px;font-size:11px;color:var(--ink-700)}
.chip .ty{font-family:ui-monospace,Menlo,monospace;font-weight:700;color:var(--regblue-700)}
.chip .sr{font-family:ui-monospace,Menlo,monospace}
.align{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}
.align .col h3{font-size:11px;text-transform:uppercase;color:var(--ink-400);margin:0 0 6px;letter-spacing:.04em}
.align .col ul{margin:0;padding-left:16px;font-size:13px}
.align .col li{margin:2px 0}
.align .none{color:var(--ink-300);font-size:13px}
.muted{color:var(--ink-400);font-size:12px}
.foot{font-size:11px;color:var(--ink-400);text-align:center;margin-top:18px}
table.idx{width:100%;border-collapse:collapse;font-size:13px}
table.idx th,table.idx td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--ink-100)}
table.idx th{font-size:11px;text-transform:uppercase;color:var(--ink-400);font-weight:600}
table.idx a{color:var(--regblue-700);text-decoration:none;font-weight:600}
table.idx td.num{font-variant-numeric:tabular-nums}
"""


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def verdict_pill(verdict: str) -> str:
    bg, fg, label = VERDICT_COLOR.get(verdict, ("#eef2f7", "#546b8b", verdict))
    return f'<span class="verdict" style="background:{bg};color:{fg}">{esc(label)}</span>'


def chip(c: dict) -> str:
    ty = {"house_view": "CIO", "portfolio": "PF"}.get(
        c.get("source_type", ""), c.get("source_type", "")
    )
    page = f" p.{c['page']}" if c.get("page") is not None else ""
    return (
        f'<span class="chip" data-citation-source="{esc(c.get("source_id"))}">'
        f'<span class="ty">{esc(ty)}</span>'
        f'<span class="sr">{esc(c.get("source_id"))}{esc(page)}</span></span>'
    )


def flagged_count(points: list) -> int:
    """Talking points the deterministic suitability policy did not clear outright.

    The single definition of the "flagged" figure. The renderer, the presenter server's
    control bar and both anti-rot stages (``scripts/demo_selftest.py`` and
    ``tests/browser/test_served_demo_ui.py``) all read it from here or recompute it from
    the running app's payload, never from a literal.
    """
    return sum(
        1
        for tp in points
        if tp.get("suitability") and tp["suitability"]["verdict"] in ("review", "unsuitable")
    )


def citation_count(points: list) -> int:
    """Total citations backing the briefing's talking points."""
    return sum(len(tp.get("citations", [])) for tp in points)


def page(title: str, body: str) -> str:
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><title>{esc(title)}</title>"
        f"<style>{CSS}</style></head><body><div class='wrap'>{body}</div></body></html>"
    )


def render_talking_point(tp: dict) -> str:
    a = tp.get("suitability")
    verdict = a["verdict"] if a else "review"
    rationale = (
        f'<div class="rationale">{esc(a["rationale"])}</div>' if a and a.get("rationale") else ""
    )
    holds = (
        f'<div class="holds">Linked holdings: {esc(", ".join(tp.get("linked_holdings", [])))}</div>'
        if tp.get("linked_holdings")
        else ""
    )
    chips = "".join(chip(c) for c in tp.get("citations", []))
    return f"""
    <div class="tp" data-point-theme="{esc(tp["house_view_theme"])}" data-point-verdict="{esc(verdict)}" data-point-citations="{len(tp.get("citations", []))}">
      <div class="hd">
        <div>
          <div class="hl">{esc(tp["headline"])}</div>
          <div class="body">{esc(tp["body"])}</div>
        </div>
        {verdict_pill(verdict)}
      </div>
      <div style="margin-top:8px"><span class="theme">{esc(tp["house_view_theme"])}</span></div>
      {holds}
      {rationale}
      {f'<div class="chips">{chips}</div>' if chips else ""}
    </div>"""


def _col(title: str, slug: str, items: list[str]) -> str:
    if items:
        body = "<ul>" + "".join(f"<li>{esc(x)}</li>" for x in items) + "</ul>"
    else:
        body = '<div class="none">none</div>'
    return (
        f'<div class="col" data-align="{esc(slug)}" data-align-count="{len(items)}">'
        f"<h3>{esc(title)}</h3>{body}</div>"
    )


def render_alignment(align: dict) -> str:
    return (
        '<section class="panel" data-panel="alignment">'
        '<h2>Portfolio alignment</h2><div class="body"><div class="align">'
        + _col("In line", "in-line", align.get("themes_in_line", []))
        + _col("Gaps", "gaps", align.get("gaps", []))
        + _col("Overweights", "overweights", align.get("overweights", []))
        + "</div></div></section>"
    )


def render_client(meta: dict, client: dict) -> str:
    points = client.get("talking_points", [])
    n_flag = flagged_count(points)
    n_cite = citation_count(points)
    review = bool(client.get("requires_human_review"))
    review_pill = '<span class="pill warn">requires human review</span>' if review else ""
    # Stable, styling-independent evidence hooks (F2). The anti-rot stages read the
    # load-bearing figures back out of the SERVED page through these attributes and
    # compare them with what the running app computed, so a renderer that silently stops
    # emitting a figure, or a hook that gets renamed, fails the gate.
    header = (
        f"<header data-panel='briefing-header' data-briefing-client='{esc(client['client_id'])}' "
        f"data-briefing-points='{len(points)}' data-briefing-flagged='{n_flag}' "
        f"data-briefing-citations='{n_cite}' data-briefing-review='{str(review).lower()}'>"
        f"<h1>CIO advisory briefing — client <span class='mono'>{esc(client['client_id'])}</span></h1>"
        f"<p class='sub'>{esc(client.get('descriptor', ''))} · profile <b>{esc(meta.get('profile'))}</b> · "
        f"region <b>{esc(meta.get('region'))}</b> · generated <b>{esc(client.get('generated_at', '')[:19])}</b></p>"
        "</header>"
    )
    banner = (
        '<div class="banner" data-panel="not-advice-banner">'
        "<b>Decision-support, not financial advice.</b>"
        f"<p>{esc(client.get('not_advice_disclaimer', ''))}</p></div>"
    )
    tp_panel = (
        f'<section class="panel" data-panel="talking-points" data-point-count="{len(points)}" '
        f'data-point-flagged="{n_flag}"><h2>Talking points <span class="muted">'
        f"{len(points)} points · {n_flag} flagged for review</span>{review_pill}</h2>"
        f'<div class="body">{"".join(render_talking_point(tp) for tp in points) or "<p class=muted>No suitable talking points.</p>"}</div></section>'
    )
    body = (
        header
        + banner
        + tp_panel
        + render_alignment(client.get("alignment", {}))
        + "<p class='foot'>Audit-first advisory view · synthetic fictional data · "
        "deterministic suitability policy · every claim cited to a CIO house view</p>"
    )
    return page(f"CIO briefing {client['client_id']}", body)


def render_index(data: dict) -> str:
    rows = []
    for c in data.get("clients", []):
        points = c.get("talking_points", [])
        n_flag = flagged_count(points)
        cid = c["client_id"]
        rows.append(
            f"<tr data-client-row='{esc(cid)}' data-client-points='{len(points)}' "
            f"data-client-flagged='{n_flag}' data-client-citations='{citation_count(points)}' "
            f"data-client-review='{str(bool(c.get('requires_human_review'))).lower()}'>"
            f"<td><a href='cio-{esc(cid)}.html'>{esc(cid)}</a></td>"
            f"<td>{esc(c.get('descriptor', ''))}</td>"
            f"<td class='num'>{len(points)}</td><td class='num'>{n_flag}</td>"
            f"<td>{'yes' if c.get('requires_human_review') else 'no'}</td></tr>"
        )
    body = (
        "<h1>CIO advisory briefings — synthetic clients</h1>"
        f"<p class='sub'>Profile <b>{esc(data.get('profile'))}</b> · region <b>{esc(data.get('region'))}</b> · "
        "decision-support, not advice. Every briefing is maker-checker gated (the RM is the checker).</p>"
        '<section class="panel" data-panel="clients"><h2>Clients</h2><div class="body">'
        "<table class='idx'><tr><th>Client</th><th>Profile</th><th>Points</th><th>Flagged</th><th>Review</th></tr>"
        + "".join(rows)
        + "</table></div></section>"
        "<p class='foot'>Audit-first advisory view · synthetic fictional data</p>"
    )
    return page("CIO advisory briefings", body)


def main(json_path: str, out_dir: str) -> None:
    data = json.loads(Path(json_path).read_text())
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    written = []
    for client in data.get("clients", []):
        p = out / f"cio-{client['client_id']}.html"
        p.write_text(render_client(data, client))
        written.append(p)
    idx = out / "index.html"
    idx.write_text(render_index(data))
    written.append(idx)
    for p in written:
        print("wrote", p)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
