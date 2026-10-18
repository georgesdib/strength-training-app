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
| `DEC-STORE-01` | 2026-10-17 | Store identity is **(which file, which line)**, never content: `raw_row` is keyed by (table, source_row, file_sha256) and `clean_set` by `raw_id` | Content-keyed deduplication is exactly what `DEC-DUP-01` forbids, and it would also merge a re-export into the original instead of recording it as a separate provenance. Keying on the source line makes a re-import a no-op while two identical sets stay two rows. | `store/migrations/0001_initial.sql` (`UNIQUE` keys), `store/repositories.py` |
| `DEC-STORE-02` | 2026-10-17 | Append-only is enforced by **SQLite triggers**, not by convention | A comment cannot stop a scripted `UPDATE`. The triggers make a mutation fail loudly, which is the only version of append-only that survives an agent "fixing" a row. `session` and `run` are deliberately exempt: the first is derived and recomputed, the second must record when it finished. | `store/migrations/0001_initial.sql` (`*_no_update` / `*_no_delete`) |
| `DEC-RULES-01` | 2026-10-17 | A rule whose inputs are absent returns **`unknown`**, never `pass`, and every evidence reference must resolve or evaluation raises | An unassessable rule counted as compliance is the failure mode the whole policy layer exists to prevent. Unresolvable evidence is a hallucination even when Python produced it, so it fails loudly rather than being stored. | `rules/registry.py` (per-predicate missing inputs), `rules/policy.py` (`UnresolvedReference`) |
| `DEC-RULES-02` | 2026-10-17 | Only an **approved** constitution version is published; a draft is refused rather than given a fabricated `effective_from` | "Which version was in force on this date" must stay answerable. `rule_document.effective_from` is NOT NULL for that reason, and inventing a date for an unapproved draft would make the answer wrong. | `rules/policy.py` (`publish`) |
| `DEC-READINESS-01` | 2026-10-17 | Readiness is materialised as one row per date using the **most-complete row, ties to the latest**, and the composite is left empty | The prescription engine needs a readiness signal for MOD-FAT-001, and leaving 1,013 dates in raw form would mean the modifier never fires. Completeness-equals-authority is an assumption (ASSUMPTION-04), so `merge_note` records every candidate and why one won. The composite needs declared metric directions (Q6 part 2) and is left null rather than guessed. | `ingest/readiness.py`, `store/repositories.py` (`upsert_readiness_days`) |
| `DEC-CRITIQUE-01` | 2026-10-17 | A rubric item the data cannot support is stored `measurable = 0` with a NULL score, and the composite is a weighted mean **renormalised over the measured items only** | Treating a missing metric as 0.0 would punish every session for something the export never recorded; treating it as 1.0 would flatter it. Renormalising keeps the composite honest and the `measurable` flag keeps the gap visible. | `critique/rubric.py` (`_unmeasurable`, `Critique.composite`), `store/migrations/0001_initial.sql` (`CHECK measurable = 1 OR score IS NULL`) |
| `DEC-CRITIQUE-02` | 2026-10-17 | Rotation is scored **split by workout label**: app-assigned rotation is neutral, self-directed churn is penalised | The logging app deliberately rotates variations between Sheiko sessions, so penalising rotation there would flag the programme's own design. In a self-directed session the opposite is true: changing lifts every week is the failure pattern. The label is the only provenance the export carries. | `critique/rubric.py` (`_rotation`, `APP_ASSIGNED_LABELS`) |
| `DEC-PRESCRIBE-01` | 2026-10-17 | Prescribed loads are solved from a recent e1RM and rounded **down** to 0.5 kg | The athlete owns 0.25 kg microplates, so 0.25 kg per side is the smallest real jump; 2.5 kg steps would leave most of that resolution unused. Rounding down because rounding up would push the set above the target RIR — the failure direction that costs a session. The 84-day e1RM window stops a two-year-old peak from prescribing today's load. | `config/thresholds.v1.yaml`, `prescribe/loads.py`, `domain/e1rm.py` (`load_for_reps`) |
| `DEC-PRESCRIBE-02` | 2026-10-17 | MOD-FAT-001 applies the **smaller** reduction (5%, not 10%), and only reduces | The rule allows 5-10%. Taking 5% first keeps the session completable as written, and a reduce-only modifier cannot accidentally increase a load through rounding. Every application cites `readiness:<date>` so the downgrade is explainable. | `config/thresholds.v1.yaml`, `prescribe/engine.py` |
| `DEC-STORE-03` | 2026-10-17 | Readiness is persisted as `raw_row` only until the duplicate-row merge rule (DQ-RD-01) is decided | Materialising `readiness_day` requires choosing which of several conflicting rows wins. That is open question Q6; writing a guess into storage would make it indistinguishable from a measured fact. | `store/importer.py` (readiness imported raw, not merged) |

## Open questions that are *not* decided

See `docs/OPEN-QUESTIONS.md`. Each has a documented default so work can continue without an
answer.

## Superseded

| id | superseded by | date | why |
|---|---|---|---|
| `DEC-STORE-03` | `DEC-READINESS-01` | 2026-10-17 | Readiness is now materialised because the prescription engine needs it for MOD-FAT-001. The merge rule it was waiting for is the documented Q6 default, and the `readiness_day` table already existed for exactly this. |
