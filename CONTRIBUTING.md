# Contributing to `cio-advisory`

Thanks for helping improve the CIO Advisory Assistant. This is an engineering-portfolio
reference repo: it must stay internally consistent and pass an offline gate with **no Google
Cloud SDK installed**.

## The hard gate (how "done" is judged)

In a fresh venv with only the `[dev]` extra (NO `google-cloud-*`, NO `google-adk`):

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

ruff check src tests          # MUST be clean
ruff format --check src tests # MUST be clean
pytest -m 'not integration' -q  # MUST pass (unit + contract)
mypy src                       # SHOULD be clean (best-effort)
python eval/run_eval.py        # SHOULD pass (exit 0)
```

`ruff check`, `ruff format --check`, and `pytest -m 'not integration'` passing are
mandatory. Use Python 3.12+ (`requires-python >= 3.12`).

## Architecture rules (do not break these)

1. **The domain stays pure.** `src/cio_advisory/domain/` imports only the standard library
   plus its own modules. No `google-cloud`, `google-genai`, `google-adk`, FastAPI, httpx, or
   pydantic in the domain.
2. **GCP imports are lazy.** Every adapter in `adapters/gcp/` imports its SDK inside a method
   or under `TYPE_CHECKING`, never at module top level. Importing any module must not require
   a Google Cloud SDK.
3. **One adapter constructor shape.** Every adapter is `def __init__(self, settings: Settings)`.
4. **On-prem placeholders raise.** Every `adapters/onprem/` method raises
   `NotImplementedError("...migration target... domain unchanged")` and names no third-party
   product.
5. **Decision-support, not advice.** Any new output must be `is_advice = False`, carry the
   non-advice disclaimer where it is a deliverable, and be suitability-tagged and
   maker-checker gated. Never phrase output as a recommendation.

## Adding a port or adapter

1. Define the Protocol in `ports/` (`@runtime_checkable`) and re-export it from
   `ports/__init__.py`.
2. Add a `cached_property` to the `Container` in `config.py`.
3. Add the three bindings (`gcp` / `platform` where applicable / `onprem`) under
   `adapters:` in `config/settings.yaml`.
4. Implement the gcp adapter (lazy SDK), the platform client if it consumes a sibling, and
   the on-prem placeholder.
5. Add the port to `PORT_PROTOCOLS` in `tests/contract/test_port_parity.py`.

## Tests

- Unit tests drive the real domain services and the `SuitabilityPolicy` against in-memory
  fakes in `tests/conftest.py`.
- The contract test proves on-prem parity.
- Integration tests are marked `@pytest.mark.integration` and deselected by default.

## Markdown

Minimise em-dashes in all markdown (use colons, commas, parentheses). Validate every mermaid
diagram with `mmdc` before submitting.

## Commits

Do not add co-author trailers. Commits are authored solely by the user.

## Adding an adapter or sub-service

For an adapter, update the typed port, implement every declared profile family, update
`config/settings.yaml`, and extend `tests/contract/test_port_parity.py` with set-equality
between ports and settings. For a sub-service, add the pure domain service, re-export it
from `domain/services.py`, wire it in `api/deps.py`, add deterministic boundary and behavior
tests, add eval and audit/demo coverage, then update SPEC, ARCHITECTURE, COMPLIANCE, runbook,
model card, and changelog.
