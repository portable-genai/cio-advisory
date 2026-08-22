"""Live, presenter-controlled demo server for the B3 advisory flow (stdlib only).

Builds the *real* suitability-checked advisory briefings for the two built-in synthetic
clients once (deterministically, on start / Restart) via the local
:class:`~cio_advisory.domain.services.AdvisoryService`, and reveals them one step per
click: the balanced client's cited talking points -> their portfolio alignment -> the
conservative client (where the SAME CIO house views now flag REVIEW) -> their alignment ->
the maker-checker review gate. It renders the audit-first UI (the not-advice banner, the
talking-point cards with suitability verdict pills + citation chips, the alignment panel)
at each step. No Google Cloud, no API key, no extra dependencies.

    PYTHONPATH=src python scripts/cio_demo_server.py [--port 8099]

Then open http://localhost:8099 and click "Next", or drive it with
``scripts/cio_demo_playwright.py`` for a presenter-controlled walkthrough. The demo port
(8099) is deliberately distinct from the FastAPI port (8091).
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cio_demo as demo  # sibling script: reuse the synthetic two-client build
import render_cio_ui as r  # sibling script: reuse the exact audit-first rendering

# The scripted reveal steps. Each "Next" reveals the next panel / advances to the next
# client; ``client`` indexes payload["clients"], and ``align`` toggles the alignment panel.
STEPS = [
    {
        "client": 0,
        "align": False,
        "label": "Balanced client — cited talking points revealed",
        "next": "Show this client's portfolio alignment",
    },
    {
        "client": 0,
        "align": True,
        "label": "Balanced client — portfolio alignment",
        "next": "Switch to the conservative client (same house views)",
    },
    {
        "client": 1,
        "align": False,
        "label": "Conservative client — same house views, now flagged REVIEW",
        "next": "Show this client's portfolio alignment",
    },
    {
        "client": 1,
        "align": True,
        "label": "Conservative client — portfolio alignment",
        "next": "Show the maker-checker review gate",
    },
    {
        "client": 1,
        "align": True,
        "label": "Maker-checker review gate — complete",
        "next": None,
    },
]

_CONTROL_CSS = """
.democtl{position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:12px;
  margin:-24px -18px 16px;padding:12px 18px;background:#0b101a;color:#fff}
.democtl .lbl{font-size:13px}.democtl .lbl b{color:#90b2ff}
.democtl .spacer{flex:1}
.democtl form{margin:0}
.democtl button{font:inherit;font-size:13px;font-weight:600;border:0;border-radius:7px;
  padding:7px 14px;cursor:pointer}
.democtl .next{background:#3a60f0;color:#fff}.democtl .next:disabled{opacity:.4;cursor:default}
.democtl .restart{background:transparent;color:#a6b6cc;border:1px solid #33445b}
.democtl .pct{font-variant-numeric:tabular-nums;color:#cdd7e4;font-size:12px}
"""


class DemoSession:
    """Builds both real briefings once and reveals them one step at a time."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.data = demo.build_payload()
        self.idx = 0

    @property
    def at_end(self) -> bool:
        return self.idx >= len(STEPS) - 1

    def advance(self) -> None:
        if not self.at_end:
            self.idx += 1

    # -- rendering --------------------------------------------------------- #
    def render(self) -> str:
        step = STEPS[self.idx]
        client = self.data["clients"][step["client"]]
        html = r.render_client(self.data, client)
        if not step["align"]:
            # Dim the alignment panel until it is explicitly revealed.
            html = html.replace(
                "<h2>Portfolio alignment",
                "<h2 style='opacity:.35'>Portfolio alignment",
                1,
            )
        return self._inject_controls(html, client)

    def _inject_controls(self, html: str, client: dict) -> str:
        step = STEPS[self.idx]
        nxt = step["next"]
        points = client["talking_points"]
        # One definition of the "flagged" figure, shared with the renderer, so the control
        # bar and the panels can never disagree (and the F2 anti-rot stages check both).
        n_flag = r.flagged_count(points)
        pill = f"<span class='pct'>{len(points)} points · {n_flag} flagged</span>"
        next_btn = (
            f"<form method='post' action='/advance'><button class='next' type='submit'>"
            f"Next &nbsp;·&nbsp; {r.esc(nxt)}</button></form>"
            if nxt
            else "<button class='next' disabled>Demo complete</button>"
        )
        bar = (
            f"<div class='democtl' data-demo='presenter-step' data-step='{self.idx}'>"
            f"<span class='lbl'>Step {self.idx + 1}/{len(STEPS)} — <b>{r.esc(step['label'])}</b></span>"
            f"{pill}<span class='spacer'></span>{next_btn}"
            "<form method='post' action='/restart'><button class='restart' type='submit'>Restart</button></form>"
            "</div>"
        )
        html = html.replace("</style>", _CONTROL_CSS + "</style>", 1)
        return html.replace("<div class='wrap'>", "<div class='wrap'>" + bar, 1)


class Handler(BaseHTTPRequestHandler):
    session: DemoSession  # set on the server instance below

    def _send(self, body: str, status: int = 200) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, to: str = "/") -> None:
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    @property
    def _sess(self) -> DemoSession:
        return self.server.session  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        with self.server.lock:  # type: ignore[attr-defined]
            if path == "/":
                self._send(self._sess.render())
            elif path == "/index":
                self._send(r.render_index(self._sess.data))
            elif path == "/state":
                self._send(json.dumps({"step": self._sess.idx}), 200)
            elif path == "/restart":
                # Allowed over GET so the walkthrough can reset with a plain navigation.
                self._sess.reset()
                self._redirect("/")
            else:
                self._send("<h1>404</h1>", 404)

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        with self.server.lock:  # type: ignore[attr-defined]
            if path == "/advance":
                self._sess.advance()
            elif path == "/restart":
                self._sess.reset()
        self._redirect("/")

    def log_message(self, *args: object) -> None:  # quiet console
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Live CIO advisory demo server")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.session = DemoSession()  # type: ignore[attr-defined]
    server.lock = threading.Lock()  # type: ignore[attr-defined]
    print(f"CIO advisory demo server on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
