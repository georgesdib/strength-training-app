# EXERCISE DEMANDS — companion demand catalogue

**Status:** Phase 1 scaffolding landed 2026-10-28; **no values are populated yet.** The
catalogue file, its validator (`strength_coach/features/demands.py`), its tests and the
coverage report (`tools/demands_report.py`) exist; the current report is **0/63 rated**, all
six dimensions unknown. The evidence table is filled in the next Phase 1 step.

**Why a companion file, not new taxonomy fields.** The taxonomy is exercise *identity*
(patterns, muscles, loadability, history equivalence). Demand profiles are a separate,
reviewable body of claims with provenance that changes on a different cadence. Keeping them in
`config/exercises/demands.v1.yaml`, keyed by canonical id, avoids touching 140 identity
entries, keeps the evidence table in one place, and gives the whole catalogue a single digest
that a prescription can cite. The taxonomy stays the source of identity; this file is the
source of demand claims. Adding an exercise still means editing the taxonomy, not Python.

## 1. Dimensions

Six dimensions are allowed; four are in scope for decisions. Each is independent and has its
**own** meaning of low/moderate/high — the categories are deliberately not interchangeable.

| key | in scope | what it describes | explicitly not |
|---|---|---|---|
| `axial_spinal` | yes | compressive/shear demand on the trunk and spine from the exercise's typical loading, independent of the prescription | not total fatigue, not injury risk |
| `trunk_stability` | yes | demand to resist unwanted trunk/pelvis motion and maintain position under load | not balance skill alone, not joint stability |
| `technical` | yes | motor-skill complexity and precision needed for a safe, effective repetition | not physiological fatigue |
| `local_muscular` | yes | capacity to impose challenging local work on the prime movers at typical prescriptions | not muscle size or activation percentage |
| `systemic` | allowed, `unknown` by default | whole-body cardiovascular/metabolic demand, only where actually measured | not inferred from "compound" |
| `eccentric_damage` | allowed, `unknown` by default | evidence of elevated eccentric loading with damage/recovery markers | not assumed from eccentric emphasis |

### 1.1 Level definitions per dimension

`unknown` is always allowed and is the default. **`unknown` is not `low`.** The same word does
not mean the same thing across dimensions:

| level | axial_spinal | trunk_stability | technical | local_muscular |
|---|---|---|---|---|
| **high** | the spine/trunk is a limiting structure at working loads (barbell squat, deadlift, RDL, good morning, heavy back extension) | standing or unilateral free-weight work where position must be actively controlled under load | multi-joint free-weight lift with positions that fail silently and need coaching (squat, deadlift, Olympic-adjacent, heavy row) | large-range, multi-joint work on the prime movers at the prescribed effort |
| **moderate** | meaningful trunk loading but not the limiting structure (front squat, split squat, supported row, hip thrust) | some postural demand, partly supported (trap-bar deadlift, standing press) | a stable variant with a real positional requirement (trap-bar deadlift, leg press with setup) | isolated or supported work with a real strength stimulus |
| **low** | supported, seated, supine or fixed-path work that does not load the spine meaningfully (leg curl, leg extension, chest-supported row, pushdown) | machine or bench-supported work (leg press, belt squat, seated press) | fixed-path machine with little positional risk (leg extension, leg curl, pushdown) | small-muscle or short-range isolation |
| **unknown** | no defensible claim | no defensible claim | no defensible claim | no defensible claim |

Local muscular demand is a property of the *typical prescription*, so it is the weakest of the
four: record it only where the exercise's role in this programme makes it meaningful.

### 1.2 Ranges and the upper-bound rule

The seed table in the specification uses ranges ("moderate–high"). Storing a range makes a
strict "lower on the targeted dimension" comparison ambiguous, so:

- record **one level**, the **upper** end of the plausible range (conservative: assume more
  demand), and put the range in `rationale`;
- if two dimensions' evidence conflicts so that no upper bound is defensible, set `unknown`.

A substitution may only use a dimension when **both** exercises have a level other than
`unknown` for it (hard rule, tested in Phase 4).

## 2. File schema (proposed)

```yaml
schema_version: "1.0.0"
reviewed_on: "2026-10-28"
# One entry per claim, cited by id from the exercise entries.
evidence:
  EV-SQUAT-AXIAL-01:
    citation: "Author. Title. Journal, year."
    doi: "10.xxxx/xxxxx"          # or url; one is required
    study_type: systematic_review # systematic_review | controlled | biomechanical | expert
    population: "trained lifters" # as reported, not invented
    outcome: "spinal compression at 80% 1RM"
    applicability: "barbell back squat; not a belt squat transfer"
    confidence: supported         # supported | provisional | contested
exercises:
  ssb_squat:
    axial_spinal:   {level: high, confidence: supported, reason: "...", evidence: [EV-SQUAT-AXIAL-01]}
    trunk_stability:{level: moderate, confidence: provisional, reason: "safety-bar squat; ..."}
    technical:      {level: high, confidence: provisional, reason: "..."}
    local_muscular: {level: high, confidence: provisional, reason: "..."}
    systemic:       {level: unknown}
    eccentric_damage:{level: unknown}
```

Every non-unknown entry carries a single `level`, a `reason`, and — when the claim is
`supported` — at least one `evidence` id. There is no range field and no aggregate.

### 2.1 Validation rules

1. Every key under `exercises` must be a canonical taxonomy id; unknown ids are refused.
2. `level` ∈ {`unknown`, `low`, `moderate`, `high`}; `unknown` may omit `reason`/`evidence`.
3. A non-unknown level must have a `reason` and a `confidence` (default `provisional`);
   `supported` and `contested` must cite at least one existing `evidence` id.
4. An evidence entry must have `citation`, one of `doi`/`url`, `study_type`, `confidence`,
   and `reviewed_on` on the file.
5. No aggregate, no weights, no 1–10 rescaling: a test refuses a top-level "score" key.
6. A rendered coverage report states, per dimension: covered ids, `unknown` rate, and the
   provisional/supported split.

### 2.2 Relationship to existing properties

- `axial_spinal` is **not** `spinal_cost`. `spinal_cost` is the ordinal cost of one
  high-fatigue exposure under `PRG-SPINE-001`; `axial_spinal` is a descriptive demand class.
  Where both exist they must not contradict (`high_fatigue_spinal: false` + `axial_spinal: high`
  is allowed — a supported row still loads the trunk less than a squat — but a test should flag
  the obviously inconsistent direction).
- `local_muscular` is **not** `primary_muscles`; the muscle list stays in the taxonomy and is
  used for stimulus preservation in Phase 4.
- Nothing here changes load, RIR, sets or progression.

## 3. Scope and coverage

- **Coverage target:** the 63 canonical ids reachable from the shipped templates and their
  configured candidates. Ids outside that set stay absent (treated as `unknown`), which is the
  honest answer for an unrated exercise.
- **Deep research:** about 25 ids, chosen as the exercises the athlete actually trains plus the
  plausible substitution candidates for those slots.
- **Never populate** synthetic/`pattern:*` ids.

## 4. What these values may and may not be used for

Allowed: display in the Exercises catalogue; a deterministic "targeted dimension is strictly
lower and both are rated" check for a suggested substitution; explaining why a suggestion was
declined.

Not allowed: ranking all exercises, aggregating dimensions, converting to a fatigue score,
sending values to the LLM as if they were measured, or treating `low` as safe. A demand
profile is evidence about a movement, not a prediction about a person on a given day.

## 5. Open evidence questions for Phase 1

1. Which of the four in-scope dimensions has enough exercise-specific evidence to be
   `supported` rather than `provisional`? (Expect: axial only, and even then partly
   inference.)
2. Trap-bar high vs low handles: does the catalogue distinguish them, and is there
   implement-specific evidence? If not, both stay `provisional`.
3. Belt squat and leg press: axial `low` is defensible; `systemic` stays `unknown`.
4. Nordic curl: eccentric damage evidence is direct (injury literature), but is it damage or
   adaptation? Keep `eccentric_damage` provisional and `local_muscular` high.
5. Any exercise where the specification's seed value cannot be defended: retain `unknown`.
