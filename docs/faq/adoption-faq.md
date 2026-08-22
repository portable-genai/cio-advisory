# Adoption FAQ

For an engineering lead forking this repo as their institution's base. The step-by-step is
[`docs/ADOPTING.md`](../ADOPTING.md); this answers the "will it hurt later?" questions.

### How do I rebrand it for my institution?

`scripts/rename_fork.py` rewrites the package name (`cio_advisory`), CLI entry point
(`cio-advisory`), `CIO_` env prefix, and resource ids in one pass (preview with `--dry-run`,
apply with `--yes`). In this repo the CLI name and the resource stem are the same string
(`cio-advisory`), so pass matching `--cli` and `--resource`; the distribution name defaults
to the `--resource` value. Then recreate the venv, `pip install -e ".[dev]"`, and run
`make lint test eval`. The script does the mechanical rename; the human decisions (region,
IdP, PII pack, suitability policy, fixtures, eval golden set) are the checklist in
`ADOPTING.md`.

### If five banks fork this, how does each take upstream security fixes?

Track upstream via **git tags** (semver). The repo declares a **core-vs-adopter-owned boundary** (ADOPTING §2): upstream owns
the neutral types in `domain/models.py`, `ports/`, `tests/contract/`, the eval harness
mechanics and CI; you own `config/settings.yaml` values, fixtures, the seeded house-view
corpus, `adapters/onprem/*`, UI theming, and the eval golden set. Rebase your adopter-owned
changes onto each release rather than merging `main` continuously, so conflicts stay in the
files you were told to expect.

### How do I add a new outbound dependency (a new port)?

There is a fixed touch list, and the contract test fails loudly if you miss part of it
(`tests/contract/test_port_parity.py` includes a reverse set-equality drift guard): define
the `@runtime_checkable` Protocol under `ports/`, re-export it, implement one adapter per
profile (at least `local` and `onprem`), bind all of them in `config/settings.yaml`, add the
port to the `PORT_PROTOCOLS` parity map, and wire it through the `Container` and `api/deps.py`.
Full instructions in [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

### How do I retune the suitability policy without touching the pipeline?

The numbers a compliance function owns are the `suitability.concentration_limit` in
`config/settings.yaml` and the risk-appetite / complex-asset / knowledge-rank gates in
`domain/suitability_policy.py`. The suitability engine is pure and deterministic, so changing
the policy changes behavior without rewiring the pipeline. Pin the behavior you want with a
unit test; the shipped defaults are a reference, not your policy.

### How do I change the taxonomy (suitability bands, asset kinds)?

They are `StrEnum`s (a base from the shared `hex-service-kit` commons) and the engines are
typed on the string values, so you extend the vocabulary through the enums and the policy
tables without editing engine mechanics. Serialized JSON values are the enum strings. To
replace the taxonomy wholesale for a different vertical, edit the enums in `domain/models.py`
and the label maps in the UI.

### Does the CI run for my fork out of the box?

Yes. CI, the eval gate, and the contract tests run on the `local` / `onprem` profiles with
**no cloud credentials and no org secrets**, so a fork's build is green immediately. You add
secrets only when you wire the `gcp`/`platform` profiles. Note the eval gate measures the
*reference* advisory vertical until you rebuild the golden set; that is an explicit adoption
step, not a silent pass. The `no_advice_safety` and `pii_safety` metrics are generic and
transfer, but the golden cases are yours.

### Will the demo rot after I diverge?

The offline demo (`make demo`, and the presenter-controlled `make demo-server` on port 8099)
runs entirely on synthetic, fictional data with no cloud and no API key, and the demo scripts
are exercised in CI. A refactor that breaks the walkthrough fails the PR rather than surfacing
the morning of a stakeholder presentation.

### Can I use this for a non-advisory decision-support product?

Yes, that is the point of the neutral-machinery / vertical split. The reusable core
(citations, grounding, the deterministic suitability / alignment engine, redaction, audit,
eval, maker-checker routing) transfers to insurance suitability, product-appropriateness
checks, portfolio-alignment copilots, and similar. You replace the artifact models and
prompts and retune the policy and taxonomy. See [`docs/ADOPTING.md`](../ADOPTING.md).
