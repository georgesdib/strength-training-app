# W11/W12 — DOCUMENTATION AND PUBLIC-DATA CLOSEOUT

**Status:** complete 2026-10-23. Documentation only; no code or prescription change.

---

## W11 — documentation consistency

| check | result | action |
|---|---|---|
| One session cap | Docs consistently say **80 min planned / 90 min hard**; templates use 80 | No change |
| Duration policy | Live workouts store measured duration; imported sessions are unmeasurable; rubric 1.1.0 now scores measured duration against 80/90 | Updated `OPEN-QUESTIONS` Q5, the rubric docstring and the rubric implementation |
| Test-count source | `ROADMAP.md` is the single current source | Removed the stale count from `USER-GUIDE`; labelled the W0 count historical |
| Architecture contract | `ARCHITECTURE.md`, `README.md` and `AGENTS.md` agree: Python computes; LLM narrates or chooses bounded precomputed options; no LLM arithmetic/veto | No change |
| Readiness/volume/age wording | W4/W8/W10 labels and reports are consistent with the engine | No change |

**W11 finding:** stale narrative counts and an outdated duration description were fixed.
Rubric 1.1.0 now scores measured live-workout duration; imported sessions remain unmeasured.

---

## W12 — public-data audit

### Inventory

| surface | content | status |
|---|---|---|
| `README.md` | purpose, status, architecture | public-safe |
| `USER-GUIDE.md` | workflows and illustrative sample output, explicitly labelled “numbers are illustrative” | public-safe |
| `ROADMAP.md` | project dates and phase history; exact retrospective counts removed | public-safe |
| `docs/` | method, evidence, decisions, audits | public-safe; qualitative sample descriptions |
| `config/` | rules, taxonomy, thresholds | public-safe |
| `tests/` | synthetic fixtures | public-safe |
| `data/` | raw exports and local database | **git-ignored** |
| `private/docs/` | exact personal context, evidence, baselines | **git-ignored** |

### Generalisation performed

Removed exact single-athlete sample counts from current public docs:

- retrospective evaluation date count;
- lift-session prediction count;
- continuity return count;
- exact readiness-coverage day count.

These are now described qualitatively in public docs, with exact values kept in the private
record. Model-error values that describe method performance (not personal performance) remain
as evidence of the rejection decision.

### Git history decision

Earlier commits still contain personal details. Removing them from the current tree does not
remove them from Git history.

**Decision: keep the history public; do not rewrite it.** This was already recorded in
`docs/PRIVACY.md` and is accepted rather than hidden. The repository is not claimed to be
anonymous.

### Residual risk

- Git history is immutable for practical purposes.
- A public repository can be mirrored; the history decision is the effective control.
- Future docs must follow `docs/PRIVACY.md`.

---

## Exit criteria

- W11 cap/count/architecture/duration checks: **complete**.
- W12 inventory and generalisation: **complete**.
- Git-history decision explicit: **complete**.
- No new personal data: **yes**.
- No code, config or prescription change: **yes**.

No training policy changed.
