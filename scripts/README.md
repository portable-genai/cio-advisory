# Demo scripts - `cio-advisory` CIO Advisory Assistant

All scripts are SDK-free and run against the in-process `local` stack (no Google Cloud,
no API key, no LLM call: a deterministic local LLM narrates and the suitability policy is
a pure function). Run them from the repo root with the domain package on the path:

```bash
export PYTHONPATH=src
```

The scripts force `CIO_PROFILE=local`, so they never reach for Google Cloud even if your
shell has a different profile set.

| Script | What it does |
|--------|--------------|
| `cio_demo.py` | Builds the suitability-checked advisory briefing for the two synthetic clients through the real `AdvisoryService` and writes the artifact JSON (one entry per client). |
| `render_cio_ui.py` | Renders that JSON into static audit-first HTML pages (one per client + an index) for screenshots. |
| `cio_demo_server.py` | A **live, click-through** server that builds the real briefings and reveals them one step per click, rendering the audit-first UI. |
| `cio_demo_playwright.py` | A **presenter-controlled** Playwright walkthrough of the live server: it narrates each step and waits for you to press Enter before performing it. |

## Static screenshots

```bash
python scripts/cio_demo.py cio_demo.json
python scripts/render_cio_ui.py cio_demo.json ./out   # ./out/cio-client-*.html, index.html
```

Or simply `make demo` (writes `cio_demo.json` and renders `./out`).

## Live, presenter-controlled demo

Two terminals:

```bash
# 1) the live demo server  (http://localhost:8099)
PYTHONPATH=src python scripts/cio_demo_server.py

# 2) the guided walkthrough  (a real Chrome window opens)
pip install playwright && playwright install chromium      # one-time
python scripts/cio_demo_playwright.py
```

The walkthrough is **paced by you**: it prints what the next step will do, waits for you to
press **Enter**, then clicks **Next** and spotlights the panel to look at. The five steps
are: balanced client talking points (with verdicts) -> their alignment -> conservative
client (the SAME house views, now flagged REVIEW / dropped) -> their alignment ->
maker-checker review gate.

You can also just open `http://localhost:8099` and click **Next** / **Restart** by hand -
the server holds the real briefings, so the buttons drive the same workflow.

The demo port `8099` is deliberately distinct from the FastAPI port `8091`.

Useful environment overrides for `cio_demo_playwright.py`:

| Var | Default | Purpose |
|-----|---------|---------|
| `DEMO_URL` | `http://127.0.0.1:8099` | server base URL (point at `http://localhost:3000` to drive the real console) |
| `HEADLESS=1` | off | run without a window (self-test / recording) |
| `DEMO_AUTO=1` | off | don't wait for Enter - advance automatically |
| `SLOWMO_MS` | `250` headed | per-action slow motion |
| `CHROME_PATH` | - | explicit Chromium/Chrome binary |
| `lock.py` | Compiles both lockfiles and puts the header back, because `uv pip compile` REPLACES the output file: it writes its own two-line provenance comment and destroys the `tag = commit` map the pin tests check against. `make lock` runs this rather than uv directly. |
