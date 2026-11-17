# ARCHITECTURE

One page. The long version is the rest of `docs/`.

## 1. Shape

Hybrid by construction: a deterministic Python core, with an LLM layer bolted on the
outside that may *explain* and answer read-only questions. It never selects an exercise or edits
the plan.

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
        │ features   tonnage · e1RM · exposure ratio (planned) · readiness     │
        │            score · injury signal · weekly spinal cost · erector dose │
        │ vbt        calibration records (versioned)               │
        └──────────────────────────────┬───────────────────────────┘
                                       ▼
        ┌──────────────────────────────────────────────────────────┐
        │ rules      versioned YAML → citable rule IDs → predicates │
        └───────┬──────────────────────────────────┬───────────────┘
                ▼                                  ▼
   ┌────────────────────────┐        ┌────────────────────────────────┐
   │ prescribe (deterministic)│      │ critique (retired; facts only) │
   │ → full prescription      │      │ → historical rows, read-only   │
   └────────┬───────────────┘        └──────────────┬─────────────────┘
            ▼                                       ▼
   ┌──────────────────────────────────────────────────────────────┐
   │ agents  LLM receives FACTS + CITED RULES, returns prose      │
   │         and read-only answers (never load/RIR/velocity       │
   │         numbers or plan changes)                             │
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
| `critique` | historical facts + stored rubric rows (scoring is retired, `DEC-EVAL-09`) | score or persist a session |
| `policy` | veto/downgrade checks | let the LLM override a veto |
| `agents` | prompt assembly, tool calls, prose | compute a load, invent a rule, cite an uncited source |
| `eval` | read-only diagnostics (fatigue diagnostics; the rubric backtest was removed) | write to production tables |

## 3. Where the LLM sits (and where it must not)

**Sits:** the *why*. Narrative, chat over supplied facts, a local knowledge explainer and
read-only weekly-review prose, always citing stable rule IDs where facts are asserted.

**Does not sit:** any computed training number or any plan edit. Loads, RIR targets, velocity
targets, percentages, tonnage, e1RM, progression decisions, session-type selection logic, exercise
selection, set counts and rubric arithmetic are Python.

Three hard boundaries:

1. **Computed numbers are supplied, never generated.** Facts arrive in the prompt or through
   read-only tools; any future tool-call interface would still return the value from Python. The
   boundary, not the transport, is the invariant.
2. **Every LLM output is validated.** The policy engine re-checks the composed
   prescription against the hard rules. Failure ⇒ deterministic fallback prescription is
   used, and the run is marked `llm_downgraded`.
3. **The LLM is optional at runtime.** `NullLLM` returns the deterministic prescription
   with no narrative. This path is exercised by a test, so "LLM unavailable" is a tested
   state, not a hope.

### 3.1 Current intelligence layer and retired write path

The read-only capability layer and the separately deployable MCP server are implemented and
specified in the portfolio
[Training Intelligence plan](https://github.com/georgesdib/strength-app/blob/main/docs/plans/TRAINING-INTELLIGENCE.md).
They use one deterministic, versioned evidence package and never become the source of a load,
e1RM, volume or safety verdict.

The former **constrained proposer** was withdrawn on 2026-11-17: the CLI `run --propose` surface
was removed for CLI/UI parity, and `DEC-LLM-09` is closed rather than deferred. No LLM may select
an exercise or propose a plan change. Retrieval/RAG remains deferred (INT-12).

## 4. Run lifecycle and trace

A run is identified by `run_id` and records, in order: the input window, the hash of the
two CSVs' relevant rows, the code version, the config/rule versions, the computed
features, the candidate prescriptions, every tool call with arguments and result (when a
client uses tools), the raw LLM output, each policy verdict, and the final artifacts. Replaying
a day means re-running
with the same `run_id` inputs and diffing.

## 5. Why SQLite and not "just CSVs"

The append-only requirement (`prescription` → `critique` compares prescribed vs performed)
and the replay requirement both want referential integrity and cheap atomic writes.
SQLite is a single local file, needs no server, and keeps the whole audit trail in one
place. DataFrames are for computation; SQLite is for memory.

## 6. Deliberate omissions and current surface

- **No hosted UI, no multi-user, no cloud.** A home-network web UI exists in
  `strength_coach/web/` and calls the same core; it is not a hosted product and has no
authentication yet (`LIM-57`).
- No vector database for v0: the rules document is small and cited by ID, so exact
  retrieval by ID beats semantic search. RAG is planned only for the *programme prose*,
  where chunk IDs must be stable.
- No multi-user, no cloud, no authentication yet; the owner accepted temporary
  unauthenticated HTTP on the home LAN (`LIM-57`). Authentication and per-user data are
  planned in `ROADMAP.md` §4.19.


## Local web UI

`strength_coach/web/` is a thin HTTP layer above the same core. It serialises prescriptions,
critiques, readiness score/overrides and calibration; it never computes a load or a score. The server binds to
0.0.0.0 and has no authentication; it is intended for the home LAN only. The CLI remains
the automation surface. Auth/per-user/TLS are planned in `ROADMAP.md` §4.19.

## Related

- **UI surface:** [UI-MAP.md](UI-MAP.md)
- **Evidence:** [REFERENCES.md](REFERENCES.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
