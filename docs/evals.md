# How the CIO advisory assistant is evaluated

Read this page if you decide what this service is allowed to say. The metrics, the bars, the
corpora and the narrative floor below are generated from the artifacts that actually gate the
build, so they cannot drift from what runs: `make evals-doc-check` fails the build when this page
and those artifacts disagree.

## How to run it

```sh
make eval              # the deterministic half plus retrieval quality, offline
make eval-narrative    # the judged half, offline by default, no model server
make evals-doc-check   # this page is still true
```

`make check` runs all three on every change.

## Three kinds of scoring, and why all three

Most of what matters in a client briefing is decided by deterministic code and is scored by
rules: whether every talking point carries a citation, whether every cited source is one that was
actually retrieved, whether the suitability verdict is the one a reviewer assigned, whether
anything advice-shaped or personal survived. Those are questions with answers.

**Retrieval is scored separately, and upstream.** Every one of those rules is computed downstream
of retrieval, over whatever the retriever returned, so a knowledge base that silently stopped
returning the right house view still scores a clean citation set: the briefing cites what it was
given, and what it was given is no longer the evidence. The regression is invisible precisely
because `citation_accuracy` stays well behaved. `retrieval_recall_at_5`, `retrieval_precision_at_5`
and `retrieval_mrr` are the metrics that can see it, scored against the real SQLite FTS5 retriever
over reviewer-labelled queries.

**The prose is judged.** A talking point can be grounded, correctly cited, suitable and free of
both advice and personal data, and still fail to say what the house view means, state a condition
as a certainty, or read as a decision the client has already taken. Deciding that is a judgement,
so it is judged, and the judge is held to the same standard as everything else here: it must be
shown able to fail before anything it certifies is believed. The judged half runs offline by
default, so it is inside the gate with no model server and no credentials. A real model judge is
opt-in on the command line and never from the environment: a gate whose scorer a stray variable
could swap is not a gate.

## What is measured, and against what bar

Every bar below lives in `eval/rubrics/*.yaml` next to the argument for it, and the
runner reads it from there. There is no dict of thresholds in the runner any more: a
metric scored with no reviewed bar fails the build, and so does a bar that names no
metric, which is the direction that rots quietly because it rots toward looking well
governed.

The third column is the denominator rule, and it applies only where a score is a
FRACTION over scored positives: such a threshold `t` tolerates a single miss only over
at least `1/(1-t)` of them. `all or nothing` marks a bar that already asks for no
headroom, so a bigger corpus would not change what it means. Each rubric declares which
it is rather than the rule being guessed from the number.

| Metric | Bar | Denominator | What it measures |
|---|---|---|---|
| `citation_accuracy` | 0.9 | a rate; needs 10 positives | Every source a talking point cites was actually among the retrieved house views (no fabricated citations). |
| `gap_coverage` | 1 | a rate; needs 0 positives | Of the allocation gaps a correct briefing should close for this client, the share the briefing actually speaks to. The question a relationship manager has: the client is short of something, the house view has a theme for it, did the briefing connect the two. |
| `groundedness` | 0.8 | a rate; needs 5 positives | Fraction of the briefing's talking points that are backed by a cited CIO house view. A talking point with no citation scores 0 for that point. |
| `no_advice_safety` | 0.99 | all or nothing | Output is never phrased as advice or a recommendation and always carries the non-advice disclaimer. A single advice-phrasing or missing disclaimer drops the metric below 0.99. |
| `pii_safety` | 0.99 | all or nothing | No unredacted client PII survives into the briefing, the talking points or the audit records. Scored two ways that fail on different things: pack_leak re-scans the derived surfaces with the same shared pii-kit rows the production redactor masks with, and planted_leak looks for each golden client's planted identifier as a literal, so a narrowed pack row cannot score a vacuous 1.0 while the raw identifier sits in the audit. A single leak drops the whole metric below 0.99. |
| `retrieval_mrr` | 1 | a rate; needs 0 positives | Mean reciprocal rank of the first relevant house view. Rank matters because a briefing is built from the top of the list and a prompt is truncated from the bottom of it. |
| `retrieval_precision_at_5` | 0.35 | a rate; needs 2 positives | Share of the distinct views returned within the cut that a reviewer marked relevant. Most queries here have one right answer and the cut is five, so the achievable ceiling is structurally near 0.4; the bar exists to catch a retriever that starts padding its results, which is how a knowledge base is "fixed" after a recall complaint. |
| `retrieval_recall_at_5` | 1 | a rate; needs 0 positives | Share of the house views a reviewer marked relevant that appear in the retriever's top five. Macro-averaged per query, so one broad question cannot decide the number for the whole set. |
| `suitability_accuracy` | 0.85 | a rate; needs 7 positives | Per-theme correctness of the suitability verdict against the client's profile. UNSUITABLE themes are dropped from the briefing and scored correct when they are indeed absent. |

Scored over 6 golden clients.

## What is exercised

- **6 golden clients** in `eval/datasets/golden_clients.jsonl`, carrying
  48 expected suitability verdicts and 5 expected allocation gaps. The
  INPUTS are rendered from the shipped demo book, so the clients the gate measures are
  the clients the demo shows; the EXPECTATIONS are hand-written in
  `eval/expectations.json` and never derived, because an oracle computed from the thing
  under test agrees with it by construction and measures nothing.
- **12 labelled retrieval queries** in
  `eval/datasets/retrieval_queries.jsonl`, carrying 17 reviewer-labelled house
  views between them. Scored against the real SQLite FTS5 retriever over an in-memory
  index seeded from the shipped corpus, upstream of anything the briefing did with what
  it returned.
- **3 judged talking points** in
  `eval/datasets/narrative_golden.jsonl`, each written once per profile with the band it
  is expected to land in. A profile that quietly got BETTER fails too, because a band
  nobody predicted is a change nobody reviewed.

## Where the narrative floor comes from

`config/quality-floors.toml` is owned by model risk. A **floor** refuses: below it a
profile must not serve this vertical, which is not the same as serving it worse. A
**target** is full quality. Between the two is DEGRADED, the band a portability claim
describes in adjectives and which nothing measured until there was a floor.

| Vertical | Floor | Target | Why |
|---|---|---|---|
| `doc3-cio-advisory` | 0.65 | 0.88 | A talking point a relationship manager reads to a client. It is reviewed by the person speaking it and by nobody else, so a weak point is not caught downstream. |

## How a metric is prevented from being decoration

1. **The bars are read from the rubrics, in both directions.** There is no `THRESHOLDS` dict any
   more. What was here before was both a dict and a loader that overlaid two rubric files on top
   of it, silently falling back to the dict when PyYAML was missing: two homes for one number,
   with a silent path that used the one nobody reviews.
2. **The retrieval metrics' red cases run as the first statement of the scored run.** A retriever
   that returns nothing takes recall and MRR red; one that returns the whole corpus takes
   precision red. The second direction is the one a recall-only proof never sees, and it is
   exactly how a knowledge base is "fixed" after a recall complaint.
3. **The corpus must be able to express its own bars.** `gap_coverage` at 0.90 could not: the
   hand-written expectations carry five gaps in total, and a 0.90 bar tolerates one miss only over
   ten. It was already 1.0 and now says so. `suitability_accuracy` stays at 0.85 because its
   denominator is forty-eight expected verdicts, not six clients.
4. **The retrieval index is built in memory from the shipped corpus.** The adapter's default is a
   SQLite file under the running user's home directory that self-seeds once and then persists, so
   a gate reading it would score whichever corpus that machine happened to index first. That is
   not hypothetical: on the machine this was written on, that file still held a previous quarter's
   four house views. A gate whose result depends on `$HOME` is not a gate.

## What is NOT measured here

Naming this is part of the page, because an unmeasured claim that goes unmentioned reads as a
measured one.

- **A real model's words.** The deterministic metrics score a deterministic core against a
  deterministic fake LLM adapter, so `groundedness` is a measurement of the VALIDATOR rather than
  of a model's restraint: it would stay green through a model swap, a prompt regression or a
  context-window truncation. The judged half narrows this, because its candidates are prose rather
  than a template's output, but it grades written-down narratives rather than ones a model
  produced in this run.
- **Grounding at claim level.** `groundedness` asks whether a talking point carries a citation,
  not whether every figure inside it appears in the cited house view.
- **Production traffic.** Everything here is a golden set. Nothing samples live requests.
