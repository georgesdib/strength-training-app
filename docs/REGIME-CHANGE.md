# REGIME-CHANGE DETECTION

**Status:** implemented 2026-10-24. Read-only; no prescription effect.

---

## 1. What it detects

A **regime change** is a persistent shift in what is actually being trained, not a single
missed session.

The signature is:

```text
a main lift's working volume falls sharply
while a same-category substitute rises
```

Example:

```text
SSB squat: 4 sets in the baseline window → 0 in the current window
split squat: 0 → 2 sets
```

The finding is a **question for the athlete**:

- was the main lift avoided because of an irritation?
- did equipment access change?
- was this a deliberate programme choice?
- was it a correct clinical decision?

It is not a verdict and it does not change a load, set or exercise.

## 2. Windows

- Compare the latest **8 or 12 weeks** with the immediately preceding window of equal length.
- Working sets only; warm-ups (`RIR 6`) are excluded.
- Exercises use their canonical identity; variants are not spliced.

## 3. Rule

For each **main lift**:

1. it must have at least **4 working sets** in the baseline window;
2. current volume must be **≤25%** of baseline;
3. find same-category exercises with a rise of at least **2 sets**, and at least 2 current
   sets.

The output keeps both:

- collapses **with** a rising substitute;
- collapses **without** one, labelled `no same-category substitute`.

The 4-set, 25% and 2-set thresholds are descriptive heuristics, not evidence-based limits.

## 4. Surfaces

```bash
strength-coach regime --weeks 8
strength-coach regime --weeks 12 --json
```

```text
GET /api/regime?weeks=8&date=YYYY-MM-DD
```

UI: **Prescribe → Regime change → Check 8-week regime**.

Output:

- main lift;
- category;
- baseline/current sets and per-week rates;
- drop percentage;
- rising same-category substitutes;
- coverage and a review-question note.

## 5. What it does not do

- no automatic prescription change;
- no diagnosis or injury verdict;
- no inference that avoidance was inappropriate;
- no cross-category comparison;
- no variant splicing;
- no conclusion from sparse data.

Category mapping follows the readiness movement categories, so a squat main lift can be
compared with unilateral squat work; a bench can be compared with another horizontal press.

## 6. Files

- `features/regime_change.py`
- `cli.py` (`regime`)
- `web/server.py` (`/api/regime`)
- `web/static` Prescribe panel
- `tests/test_regime_change.py`, `tests/test_web.py`
- `docs/TRAINING-GUIDELINES.md` §8

## Related

- **UI surface:** [UI-MAP.md](UI-MAP.md)
- **Evidence:** [REFERENCES.md](REFERENCES.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
