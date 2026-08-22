"""Local deployment profile adapters: a WORKING, offline laptop stack.

The ``local`` profile is the third deployment option alongside ``gcp`` (managed
Google Cloud services) and ``onprem`` (fail-fast Google Distributed Cloud migration
placeholders). Unlike ``onprem``, every adapter here is a *real, deterministic*
implementation that runs the whole B3 advisory pipeline end to end with **no Google
Cloud, no API key, and no running emulators by default**:

* House-view retrieval (A2 governed KB) -> a ``sqlite3`` **FTS5** index over the CIO
  house-view articles (BM25 rank), mapped back to :class:`HouseView` objects.
* Portfolio / KYC profile -> an in-process store seeded with synthetic clients.
* LLM (Gemini) -> a deterministic, schema-driven generator (no model, no network).
* Guardrail (Model Armor) -> a heuristic that blocks prompt-injection / jailbreak text.
* PII redaction (DLP) -> regex de-identification (SG NRIC/FIN, emails, SG phones).
* Audit (Cloud Logging WORM) -> an append-only local store (SQLite), read-back supported.
* Tracer (Cloud Trace) -> no-op spans.
* Registry / sessions / memory -> in-process stores, seedable.
* Grounding (google_search) -> disabled (no public-web egress) by default.
* Evaluation (Gen AI eval) -> delegates to the in-repo offline eval gate.

Everything is **seedable** so the test suite stays deterministic, and the default code
path imports **no google-cloud package at module top level**. Optional higher-fidelity
local runs route to Google's official emulators when the standard ``*_EMULATOR_HOST``
env vars are set (the google client is imported lazily, only on that branch); see
:mod:`cio_advisory.adapters.local._emulator`.
"""
