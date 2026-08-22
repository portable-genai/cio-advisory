# Demo guide - Doc3 CIO Advisory Assistant

Step-by-step scripts for demoing Doc3 two ways:

- **Demo A - Suitability-checked advisory briefings, fully offline** (the headline flow):
  for two synthetic clients the assistant runs the whole pipeline - redact, guardrail,
  retrieve the CIO house views, synthesise personalised talking points, run the
  suitability policy per theme, drop UNSUITABLE points, compute portfolio alignment - and
  returns briefings where every talking point carries a suitability verdict and citations
  back to a CIO house view, under a maker-checker (human-review) gate. The headline is that
  the SAME house views earn different verdicts for the two clients. Runs **fully offline**
  (no cloud, no API key).
- **Demo B - The same briefings on the managed GCP stack**: the identical artifacts
  produced against real File Search / Gemini / Model Armor / DLP / BigQuery in
  `asia-southeast1`, shown via the REST API and the Next.js console.

- **Demo C - REAL research and YOUR portfolio under the `live` profile** (the
  audience-facing demo): the day's investment themes come from Gemini-grounded research
  over real published market commentary (each theme cited to its real public source),
  and the client portfolio is whatever the audience registers (JSON template
  downloadable in the UI; opaque ids only, never PII). Suitability verdicts stay with
  the deterministic policy engine; the narrative is generated on a local Gemma model
  server. The fictional sample clients and house views never appear under live.

> The synthetic client and portfolio data in Demos A/B is **fictional** and uses opaque,
> non-PII client ids. This is decision-support, NOT financial advice. Do not run against
> live client data without your own legal, security and model-risk sign-off. Demo C's
> themes are research summaries of public commentary, not a governed in-house CIO
> publication: every citation names its real source so a reviewer can open it.

### Demo C in three commands

```bash
# 1. Start a local OpenAI-compatible model server on :8001 (MLX / Ollama / vLLM)
#    and install the research extra: pip install -e '.[live]'

# 2. Serve live (grounded research needs a GCP project + application-default creds).
GOOGLE_CLOUD_PROJECT=<project> CIO_PROFILE=live python -m cio_advisory.api.app

# 3. In the UI (:3000): download the client template, register a portfolio, Build briefing.
#    API equivalents: GET /v1/clients/template, POST /v1/clients, POST /v1/briefing.
```

---

## 0. Prerequisites

| Need | Demo A (local) | Demo B (GCP) | Notes |
|------|:--:|:--:|-------|
| `git` | yes | yes | clone the repo |
| **Python 3.12+** | yes | yes | the package pins `>=3.12` |
| Node.js 18+ & npm | for the UI / Playwright | for the UI | only if you show the browser console |
| **Playwright** (`pip install playwright` + `playwright install chromium`) | for the guided walkthrough | no | Demo A's presenter walkthrough |
| A GCP project + `gcloud` | no | yes | billing enabled; `asia-southeast1` available |
| Terraform | no | yes | provisions File Search, BigQuery, DLP, WORM bucket, CMEK |
| Cloud KMS key (regional) | no | yes | CMEK; set `CIO_KMS_KEY` |

Install/setup references (read these once):

- Local install & profiles -> [README "Run locally"](README.md)
- HTTP API surface -> [README](README.md) and [`ui/README.md`](ui/README.md)
- The demo scripts -> [`scripts/README.md`](scripts/README.md)
- The UI console -> [`ui/README.md`](ui/README.md)
- Config (`${ENV_VAR}` resolved at load) -> [`config/settings.yaml`](config/settings.yaml)

---

## 1. Common setup (both demos)

```bash
git clone https://github.com/portable-genai/cio-advisory.git
cd cio-advisory

python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # core + dev tooling (NO google-cloud-* packages)

# Sanity check the offline stack before presenting:
export CIO_PROFILE=local
make lint test                   # ruff + mypy + pytest (all local, no cloud)
```

---

## 2. Demo A - Suitability-checked advisory briefings (local, offline)

The build runs on an in-process `local` stack (SQLite FTS5 house-view retrieval + a
deterministic LLM), so it needs **no Google Cloud and no API key** - ideal for a laptop
demo. Four ways to present it, in order of polish.

### 2.1 Guided, presenter-controlled walkthrough (recommended)

A real browser opens; the script narrates each step and **waits for you to press Enter**
before performing it, so you control the pace. (One-time: `pip install playwright &&
playwright install chromium`.)

```bash
# Terminal 1 - the live demo server (http://localhost:8099)
source .venv/bin/activate
PYTHONPATH=src python scripts/cio_demo_server.py

# Terminal 2 - the guided walkthrough (a Chrome window opens)
source .venv/bin/activate
python scripts/cio_demo_playwright.py
```

You'll step through, pressing Enter each time:

1. **Balanced client (client-000042)** - cited talking points on screen, each with a
   suitability verdict pill; the amber banner says decision-support, not advice.
2. **Portfolio alignment** - which OVERWEIGHT house views the portfolio reflects (in
   line), under-holds (gaps), or holds at/above the concentration limit (overweights).
3. **Conservative client (client-000077)** - the SAME house views now earn different
   verdicts: the aggressive equity overweight is dropped as UNSUITABLE, the rest flag
   REVIEW (ESG-only constraint, concentration, retail knowledge).
4. **Portfolio alignment** for the conservative client - a different picture.
5. **Maker-checker** - every briefing always requires human review (P-06); every claim is
   cited back to a CIO house view.

**What to point at on screen:** the not-advice banner, the suitability verdict pills
(suitable / review / unsuitable), the citation chips on every talking point, and how the
verdicts change between the two clients. Full options (`SLOWMO_MS`, `HEADLESS`,
`CHROME_PATH`, ...) are in [`scripts/README.md`](scripts/README.md).

### 2.2 Manual, click-through (no Playwright)

Run only the server and drive it yourself in any browser:

```bash
PYTHONPATH=src python scripts/cio_demo_server.py     # http://localhost:8099
```

Open `http://localhost:8099` and click **Next** to advance, **Restart** to reset, and the
**/index** path for the per-client overview. Or run the real console against the live API
instead:

```bash
make run-api PROFILE=local      # FastAPI on :8091
make run-ui                     # Next.js console on http://localhost:3000
```

The console submits the client to `POST /v1/briefing` and renders the same briefing.

### 2.3 Static artifacts (slides / screenshots)

Generate the audit-first pages and JSON without a browser:

```bash
PYTHONPATH=src python scripts/cio_demo.py cio_demo.json        # prints the per-client summary
PYTHONPATH=src python scripts/render_cio_ui.py cio_demo.json ./out
# -> ./out/cio-client-000042.html, ./out/cio-client-000077.html, ./out/index.html
```

Or simply `make demo` (writes `cio_demo.json` and renders `./out`).

### 2.4 One-shot briefing via the CLI (quick variant)

If you only want the cited briefing in the terminal (not the browser):

```bash
export CIO_PROFILE=local
cio-advisory briefing client-000042
```

`cio-advisory talking-points client-000042` and
`cio-advisory suitability client-000042 "AI infrastructure build-out"` show the individual
artifacts.

---

## 3. Demo B - The same briefings on the managed GCP stack

Shows the identical artifacts produced against **real managed services** in
`asia-southeast1`; the short version:

### 3.1 GCP setup

```bash
source .venv/bin/activate
pip install -e ".[gcp,dev]"                 # adds google-adk, google-genai, discoveryengine, bigquery, dlp, ...

export GOOGLE_CLOUD_PROJECT=your-sg-project
export CIO_PROFILE=gcp
export CIO_KMS_KEY="projects/.../locations/asia-southeast1/keyRings/.../cryptoKeys/..."
gcloud auth application-default login
```

### 3.2 Provision infra (one-time)

```bash
make tf-plan          # review the plan - the WORM bucket lock is IRREVERSIBLE
cd infra/terraform && terraform apply && cd ../..
# Export the outputs the app reads:
export CIO_DLP_INSPECT_TEMPLATE="$(terraform -chdir=infra/terraform output -raw dlp_inspect_template)"
export CIO_DLP_DEIDENTIFY_TEMPLATE="$(terraform -chdir=infra/terraform output -raw dlp_deidentify_template)"
```

### 3.3 Run and show

```bash
make run-api PROFILE=gcp          # FastAPI on :8091, profile=gcp
```

Then demo any surface:

```bash
# REST - build a suitability-checked advisory briefing.
# No actor is sent: the audit actor is the SERVER-verified identity (an IAP assertion in
# secure mode; a seeded dev persona chosen with the X-Dev-Persona header under local).
curl -s localhost:8091/v1/briefing -H 'content-type: application/json' -d '{
  "client_id": "client-000042"
}' | python -m json.tool

# Just the talking points
curl -s localhost:8091/v1/talking-points -H 'content-type: application/json' -d '{
  "client_id": "client-000042"
}' | python -m json.tool

# Suitability of one house-view theme for a client
curl -s localhost:8091/v1/suitability -H 'content-type: application/json' -d '{
  "client_id": "client-000077", "theme": "AI infrastructure build-out"
}' | python -m json.tool

# Under the local profile you can act as a specific seeded persona (see /v1/personas):
curl -s localhost:8091/v1/briefing -H 'content-type: application/json' \
  -H 'X-Dev-Persona: auditor' -d '{"client_id": "client-000042"}' | python -m json.tool

# Agent card / health
curl -s localhost:8091/.well-known/agent-card.json | python -m json.tool
curl -s localhost:8091/healthz
```

Or the browser console (talks to the API on :8091) - see [`ui/README.md`](ui/README.md):

```bash
make run-ui           # http://localhost:3000
```

**What to highlight:** every talking point carries a **citation** back to a CIO house view;
PII is redacted before any model/index/audit call; the suitability verdict is **computed
deterministically** by the policy (the LLM never overrides UNSUITABLE); a briefing is
**always** marked human-review (maker-checker, the RM is the checker); everything stays in
`asia-southeast1` with CMEK.

---

## 4. Talking points

- **Suitability is the gate, and it is a pure function.** The verdict (suitable / review /
  unsuitable) is computed deterministically from the client's risk appetite, constraints,
  concentration and knowledge - replayable by a reviewer. The LLM only drafts prose; it
  never overrides an UNSUITABLE verdict, which is dropped and never presented.
- **It's grounded, not generative guesswork.** Retrieval is the gate: every talking point
  points back to its exact CIO house view. With no house views retrieved the build refuses
  rather than inventing advice.
- **Decision-support, not advice.** A persistent non-advice banner, a "not advice" framing
  on every talking point, and a "requires human review" flag on every briefing - the RM is
  the human checker (P-06).
- **Guardrails hold.** Redact-before-everything, guardrail on input and output, always-on
  maker-checker, single-region + CMEK residency in `asia-southeast1`.

---

## 5. Troubleshooting & cleanup

| Symptom | Fix |
|---------|-----|
| `python3.12: command not found` | Install Python 3.12+; the package pins `>=3.12`. |
| `ModuleNotFoundError` for a google-cloud package from a script | You ran with a non-local profile. The demo scripts pin `CIO_PROFILE=local`; do not override it to `gcp` without `pip install -e ".[gcp,dev]"`. |
| Playwright: "executable doesn't exist" | `playwright install chromium`, or set `CHROME_PATH=/path/to/chrome`. |
| No display for the headed walkthrough | Use 2.2 (manual browser) on a machine with a display, or `HEADLESS=1 DEMO_AUTO=1 python scripts/cio_demo_playwright.py` to self-run. |
| "Cannot reach the demo server" | Start 2.1 Terminal 1 first; or set `DEMO_URL` if you changed `--port`. |
| Port 8099 / 8091 in use | `python scripts/cio_demo_server.py --port 9000` (then `DEMO_URL=http://127.0.0.1:9000`); API port via `make run-api API_PORT=...`. |
| `NotImplementedError` / exit 2 from a CLI command | You're on `CIO_PROFILE=onprem` (fail-fast). Use `local` (Demo A) or `gcp` (Demo B). |
| UI shows "Could not reach the advisory backend" | Start `make run-api PROFILE=local` first; the console reads `NEXT_PUBLIC_API_BASE` (default `http://localhost:8091`). |

**Stop / clean up:** Ctrl-C the demo server and `make run-api`. For GCP, scale the
deployment to zero or remove the app SA's model access - the audit trail remains intact.
`make clean` removes local caches/artefacts (and you can delete `cio_demo.json` and
`./out`).
