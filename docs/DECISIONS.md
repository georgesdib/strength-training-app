# DECISION LOG

Append-only. Every decision that is expensive to reverse, or that an agent might "helpfully"
undo, gets an id, a reason and a pointer to where it is enforced.

Two id namespaces:

* `DEC-*` — a decision the athlete or the project made.
* `DQ-*` — a data-quality finding, documented in `docs/DATA-QUALITY.md`.

Numbers are never reused. Superseding a decision adds a new row; it never edits the old one.

---

| id | date | decision | why | enforced at |
|---|---|---|---|---|
| `DEC-TRAPBAR-01` | 2026-10-17 | "Competition Deadlift" in the log **is** the trap-bar deadlift | The logging app records it under the powerlifting name. Without this the hinge main lift appeared to have no history at all. | `config/exercises/taxonomy.v1.yaml` (`alias_overrides`) |
| `DEC-BACKEXT-01` | 2026-10-17 | Back extension ≡ hyperextension **going forward only**; historical rows keep their own identity | Same movement from now on, but the historical rows may not have used the same bench, so projecting the equivalence backwards would silently fabricate erector-dose history. | taxonomy `alias_overrides` + `forward_alias`; `utils.exercises.forward_name` |
| `DEC-RIR-01` | 2026-10-17 | `RIR 6` marks a **warm-up set**, not an easy set | The athlete confirmed the meaning. It carried a quarter of all rows, so treating it as effort inflated volume, fatigue and e1RM. | `domain/rir.py` (`classify`) |
| `DEC-LOAD-02` | 2026-10-17 | Bodyweight progression acts on **added load**; total mass is used only for e1RM | The athlete's choice. Programming a pull-up as "bodyweight + 2.5 kg" is actionable; programming it as a three-digit total mass is not. | `domain/load.py` (`progression_load`) |
| `DEC-WINDOW-01` | 2026-10-17 | The trap bar's RIR window is amended from 3-4 to the default **2-3** | The tighter window fired on ~43% of trap-bar sets because of window definition, not effort: the athlete trains the hinge at ~RIR 2. One window now covers every primary compound. | `domain/rir.py` (`PER_EXERCISE_RIR_TARGET`, now empty) + `config/rules/programme.v1.yaml` |
| `DEC-DUP-01` | 2026-10-17 | Training rows are **never** deduplicated | Identical repeated rows trace a textbook set structure (mostly pairs, then threes, fours, fives). Blanket dedupe would delete real volume. | `ingest/clean.py` (no dedupe step, by design) |
| `DEC-NULLDATE-01` | 2026-10-17 | Rows with a null date are **quarantined**, not deleted | They form a plausible session fragment and would otherwise leak into violation counts. Visible and counted beats silently removed. | `ingest/clean.py` (`quarantine`) |
| `DEC-ACWR-01` | 2026-10-17 | ACWR is **advisory only** and may never veto a prescription | The "sweet spot" interpretation of acute:chronic ratio is actively contested in the literature. | planned `rules/policy.py` severity `advisory` |
| `DEC-VELOCITY-01` | 2026-10-17 | Within-set velocity loss is reported as **not measurable**, with a labelled decay proxy | The export stores one average velocity per set; a mean has no within-set variance. | `docs/SANITY-CHECKS.md` §C |
| `DEC-PRIVACY-01` | 2026-10-17 | No training data, bodyweight, injury history or derived metrics in this repository | The repository is public. Personal documents live in the git-ignored `private/`. | `.gitignore`, `AGENTS.md` §3.13 |

## Open questions that are *not* decided

See `docs/OPEN-QUESTIONS.md`. Each has a documented default so work can continue without an
answer.

## Superseded

Nothing yet.
