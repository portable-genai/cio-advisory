# On-prem migration guide

Doc3 is reversible by construction (P-02, P-12). The on-prem adapter family
(`src/cio_advisory/adapters/onprem/`) is the migration target: each placeholder constructs
cleanly with no external dependencies, structurally satisfies the same port as the managed
adapter, and raises `NotImplementedError` from every method. Porting Doc3 to an on-premise
platform is a matter of filling those bodies in; the domain core and the service callers do
not change.

## What stays the same

- The entire `domain/` layer: models, `AdvisoryService`, `SuitabilityPolicy`,
  `TalkingPointsService`, `CioReviewPolicy`, prompts, serialization, errors.
- The `ports/` Protocols and the wiring contract in `config/settings.yaml`.
- The API, CLI, and agent edges (they depend on ports, not adapters).

## What you implement

Fill in each on-prem adapter against your on-premise platform:

| Port | On-prem adapter | What to implement |
|---|---|---|
| `HouseViewRetrievalPort` | `onprem/house_views.py` | Retrieve CIO house views from your on-prem document store, mapped to `HouseView`. |
| `PortfolioPort` | `onprem/portfolio.py` | Read portfolios and KYC profiles from your on-prem relational store. |
| `LLMPort` | `onprem/llm.py` | Call your on-prem model serving for synthesis and triage. |
| `GroundingPort` | `onprem/grounding.py` | Optional web grounding; keep `enabled = False` until wired. |
| `GuardrailPort` | `onprem/guardrail.py` | Screen prompts/responses. Must never fail-open. |
| `PIIRedactionPort` | `onprem/redaction.py` | De-identify PII before any model call or audit write. Must never pass PII through. |
| `AuditSinkPort` | `onprem/audit.py` | Append to an immutable (WORM) audit store. Must never drop a record. |
| `ObservabilityTracerPort` | `onprem/tracer.py` | Open spans with content capture OFF. |
| `EvaluationGatePort` | `onprem/evaluation.py` | Run the promotion gate against your evaluator. |
| `AgentRegistryPort` | `onprem/registry.py` | Register/resolve the AgentCard in your catalog. |
| `ToolCatalogPort` | `onprem/tool_catalog.py` | Serve the governed tool catalog. |

## How to switch

Set `CIO_PROFILE=onprem` (or `profile: onprem` in `config/settings.yaml`). The container
rebinds every port to the on-prem adapter. The contract test
(`tests/contract/test_port_parity.py`) already proves each placeholder constructs with a
single `Settings` argument and satisfies its Protocol, so once you fill in the bodies the
interface is guaranteed to hold.

## Safety invariants to preserve

When implementing the on-prem adapters, keep the R1 guarantees:

- Redaction runs before anything downstream; the redactor must raise rather than pass PII
  through unredacted.
- The guardrail must raise rather than allow traffic when unimplemented or unreachable.
- The audit sink must raise rather than silently drop a record.
- Trace spans never carry message content.
