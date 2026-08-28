# B3 CIO Advisory Assistant : developer Makefile.
#
# The default dev/test/lint targets run under the LOCAL profile: a WORKING offline stack
# (SQLite FTS5 + deterministic LLM, no Google Cloud SDK, no API key, no emulator). The
# onprem profile fails fast (migration placeholders). Override PROFILE=gcp for the managed
# stack, or PROFILE=onprem to exercise the fail-fast migration target.

PYTHON      ?= python3
PIP         ?= pip
PROFILE     ?= local
SRC         := src/cio_advisory
TESTS       := tests
API_APP     := cio_advisory.api.app:app
API_HOST    ?= 127.0.0.1  # no-auth local dev binds loopback; override deliberately
API_PORT    ?= 8091
UI_DIR      := ui
TF_DIR      := infra/terraform

export CIO_PROFILE := $(PROFILE)

.DEFAULT_GOAL := help
.PHONY: help install install-demo install-gcp lock fmt lint test briefing demo demo-server demo-selftest eval check \
        demo-browser portability ui-install ui-check run-api run-ui tf-plan clean

help: ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install the package + dev tooling (NO GCP SDK : local/test profile).
	$(PIP) install -e ".[dev]"

install-demo: ## Install the pinned headless-browser extra, then fetch its browser binary.
	$(PIP) install -e ".[dev,demo]"
	$(PYTHON) -m playwright install chromium

install-gcp: ## Install with the managed-stack extra (google-adk, genai, discoveryengine, ...).
	$(PIP) install -e ".[gcp,dev]"

lock: ## Recompile every lockfile from pyproject.toml and restore the tag = commit headers.
	$(PYTHON) scripts/lock.py

fmt: ## Auto-format and auto-fix lint issues.
	ruff format $(SRC) $(TESTS) eval
	ruff check --fix $(SRC) $(TESTS) eval

lint: ## Lint (ruff), check formatting, and type-check (mypy).
	ruff check $(SRC) $(TESTS) eval scripts/demo_selftest.py scripts/portability_demo.py \
		scripts/render_cio_ui.py
	ruff format --check $(SRC) $(TESTS) eval scripts/demo_selftest.py scripts/portability_demo.py \
		scripts/render_cio_ui.py
	mypy $(SRC)

test: ## Run unit + contract tests on the local profile (no GCP SDK required).
	CIO_PROFILE=local pytest -m 'not integration' -q

briefing: ## End-to-end smoke: build a cited briefing offline under the local profile.
	CIO_PROFILE=local cio-advisory briefing client-000042

demo: ## Offline demo: build cited briefings + write JSON + render static audit-first HTML.
	PYTHONPATH=src $(PYTHON) scripts/cio_demo.py cio_demo.json
	PYTHONPATH=src $(PYTHON) scripts/render_cio_ui.py cio_demo.json ./out
	@echo "open ./out/index.html - or: make demo-server"

demo-server: ## Live presenter-controlled demo server (offline) on :8099.
	PYTHONPATH=src $(PYTHON) scripts/cio_demo_server.py

eval: ## Run the A4 eval gate (groundedness / suitability / citations / no-advice).
	$(PYTHON) eval/run_eval.py

portability: ## Execute the bounded offline/profile portability proof.
	PYTHONPATH=src $(PYTHON) scripts/portability_demo.py

plugin: ## Render the Agent Plugins 1.0.0 directory from this repo's own declarations.
	python scripts/render_plugin.py --dest dist/plugin

mcp-serve: ## Serve the governed tool catalog over MCP 2026-07-28 (stdio; needs [gcp]).
	python -m cio_advisory.mcp

check: lint test eval demo-selftest portability plugin ## Run the full offline quality gate (no node, no cloud).

demo-selftest: ## Prove the served presenter states and evidence hooks cannot rot silently.
	PYTHONPATH=src:scripts $(PYTHON) scripts/demo_selftest.py

demo-browser: ## Drive the SERVED demo through pinned headless Chromium (needs the [demo] extra).
	CIO_PROFILE=local $(PYTHON) -m pytest $(TESTS)/browser -q -rs

# --------------------------------------------------------------------------------------- #
# The ui/ console. Requires node; nothing in `make check` does.
# --------------------------------------------------------------------------------------- #

ui-install: ## Install the console's locked dependencies.
	npm ci --prefix $(UI_DIR)

ui-check: ## The console gate: types, CSP unit tests, build, and a REAL hydration check.
	npm --prefix $(UI_DIR) run lint
	npm --prefix $(UI_DIR) test
	NEXT_TELEMETRY_DISABLED=1 npm --prefix $(UI_DIR) run build
	# Runs LAST and against the artefact the previous line produced. Everything cheaper than
	# this has been fooled by the defect it catches: the CSP header is byte-identical whether
	# the page hydrates or is dead markup, so only starting the built server and reading the
	# served script tags can tell the two apart. See ui/scripts/assert-hydratable.mjs.
	npm --prefix $(UI_DIR) run assert-hydratable

run-api: ## Run the FastAPI service (PROFILE=$(PROFILE)).
	uvicorn $(API_APP) --host $(API_HOST) --port $(API_PORT) --reload

run-ui: ## Run the React / Next.js UI (dev server).
	cd $(UI_DIR) && npm install && npm run dev

tf-plan: ## Terraform plan for the asia-southeast1 infrastructure.
	cd $(TF_DIR) && terraform init -input=false && terraform plan

clean: ## Remove caches and build artefacts.
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
