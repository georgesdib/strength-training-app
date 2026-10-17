# ARCHITECTURE

One page. The long version is the rest of `docs/`.

## 1. Shape

Hybrid by construction: a deterministic Python core, with an LLM layer bolted on the
outside that may only *explain* and *select among pre-approved options*.

```
                    ┌─────────────────────────────────────────────┐
   data/raw/*.csv ─▶│ ingest    clean → canonical sets → sessions │
                    └──────────────────┬──────────────────────────┘
                                       ▼
                    ┌─────────────────────────────────────────────┐
                    │ store     SQLite, append-only               │
                    └──────────────────┬──────────────────────────┘
                                       ▼
        ┌──────────────────────────────┴───────────────────────────┐
        │ features   tonnage · e1RM · ACWR · readiness composite   │
        │            weekly spinal cost · erector dose             │
        │ vbt        calibration records (versioned)               │
        └──────────────────────────────┬───────────────────────────┘
                                       ▼
        ┌──────────────────────────────────────────────────────────┐
        │ rules      versioned YAML → citable rule IDs → predicates │
        └───────┬──────────────────────────────────┬───────────────┘
                ▼                                  ▼
   ┌────────────────────────┐        ┌────────────────────────────────┐
   │ prescribe (deterministic)│      │ critique (deterministic rubric)│
   │ → full prescription      │      │ → facts + rubric scores        │
   └────────┬───────────────┘        └──────────────┬─────────────────┘
            ▼                                       ▼
   ┌──────────────────────────────────────────────────────────────┐
   │ agents  LLM receives FACTS + CITED RULES, returns prose      │
   │         and option choices only — never numbers              │
   └──────────────────────────────┬───────────────────────────────┘
                                  ▼
   ┌──────────────────────────────────────────────────────────────┐
   │ policy  validates any LLM output; VETO → deterministic        │
   │         fallback; logs every verdict                         │
   └──────────────────────────────┬───────────────────────────────┘
                                  ▼
                    trace    run record: inputs hash, features,
                             tool calls, LLM text, verdicts, output
```

## 2. Layers and what each may not do

| Layer | Owns | Must never |
|---|---|---|
| `utils` | pure helpers: dates, numeric sentinels, stats, exercise resolution | import domain code |
| `domain` | e1RM, load rounding, RIR logic, velocity logic, progression, fatigue mods | do I/O |
| `ingest` | CSV → raw → cleaned → sets → sessions | invent values; drop rows silently |
| `store` | SQLite schema, append-only writes | mutate a prescription/critique |
| `features` | feature store, VBT calibration | contain rule thresholds (those are config) |
| `rules` | load/hash/version rule docs; evaluate predicates | be edited at runtime |
| `prescribe` | deterministic prescription from template + state + rules | call an LLM |
| `critique` | deterministic rubric scores from rules + facts | call an LLM |
| `policy` | veto/downgrade checks | let the LLM override a veto |
| `agents` | prompt assembly, tool calls, prose | compute a load, invent a rule, cite an uncited source |
| `eval` | backtest harness, labelled rubric set | write to production tables |

## 3. Where the LLM sits (and where it must not)

**Sits:** the *why*. Narrative critique, rubric rationale, rationale sentences that cite
stable rule IDs, and choosing among a small set of pre-approved session options.

**Does not sit:** any number. Loads, reps, RIR targets, velocity targets, rest, time
allocation, tonnage, e1RM, progression decisions, session-type selection logic, or the
rubric arithmetic. Those are Python, always.

Three hard boundaries:

1. **Numbers arrive by tool call.** If the prescription agent wants a load, it calls
   `compute_load_from_velocity(...)` or `next_load(...)`; the tool returns the value and
   the agent may only echo it.
2. **Every LLM output is validated.** The policy engine re-checks the composed
   prescription against the hard rules. Failure ⇒ deterministic fallback prescription is
   used, and the run is marked `llm_downgraded`.
3. **The LLM is optional at runtime.** `NullLLM` returns the deterministic prescription
   with no narrative. This path is exercised by a test, so "LLM unavailable" is a tested
   state, not a hope.

## 4. Run lifecycle and trace

A run is identified by `run_id` and records, in order: the input window, the hash of the
two CSVs' relevant rows, the code version, the config/rule versions, the computed
features, the candidate prescriptions, every tool call with arguments and result, the raw
LLM output, each policy verdict, and the final artifacts. Replaying a day means re-running
with the same `run_id` inputs and diffing.

## 5. Why SQLite and not "just CSVs"

The append-only requirement (`prescription` → `critique` compares prescribed vs performed)
and the replay requirement both want referential integrity and cheap atomic writes.
SQLite is a single local file, needs no server, and keeps the whole audit trail in one
place. DataFrames are for computation; SQLite is for memory.

## 6. Deliberate omissions

- No UI (explicitly deferred).
- No vector database for v0: the rules document is small and cited by ID, so exact
  retrieval by ID beats semantic search. RAG is planned only for the *programme prose*,
  where chunk IDs must be stable.
- No multi-user, no cloud, no auth.
