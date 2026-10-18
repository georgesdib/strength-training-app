# RIR EVIDENCE — why the effort window is 1-4 with a 2-3 target

The constitution used to hold primary compounds at RIR 2-3 and forbid RIR 0-1. The athlete
asked for that window to be evidence-based rather than fixed. This note records the evidence
and the resulting decision (`DEC-RIR-02`).

---

## Evidence

**Strength is similar across a wide range of RIR.** A series of meta-regressions on estimated
proximity to failure found that confidence intervals for the strength slope contained the null
in every best-fit model: strength gains did not meaningfully depend on RIR (Robinson, Pelland,
Remmert, Refalo, Jukic, Steele & Zourdos, *Sports Medicine* 2024,
doi:10.1007/s40279-024-02069-2).

**Failure is not required for strength, and may be slightly worse.** A 2026 meta-analysis of 20
studies (556 participants) found non-failure training superior for dynamic strength
(SMD 0.24, 95% CI 0.06-0.42) and equivalent for isometric strength, hypertrophy, endurance and
power (Wu et al., *BMC Sports Sci Med Rehabil* 2026, doi:10.1186/s13102-026-01861-z). An earlier
meta-analysis found no overall strength difference and a hypertrophy advantage for failure that
disappeared once volume was equalized (Vieira et al., *J Strength Cond Res* 2021,
doi:10.1519/JSC.0000000000003936).

**Hypertrophy does respond to proximity to failure, but not enough to justify a hard floor.**
The 2024 meta-regression found hypertrophy increased as sets were taken closer to failure; a
2023 meta-analysis found no advantage for momentary failure over non-failure for hypertrophy
(ES 0.12, 95% CI -0.13 to 0.37) (Refalo et al., *Sports Medicine* 2023,
doi:10.1007/s40279-022-01784-y). Training at 1-3 RIR produced hypertrophy and strength
comparable to failure in recent within-participant trials (Vasconcelos et al. 2026,
doi:10.3390/muscles5030061).

**RIR is self-reported and imprecise.** Estimation error improves with practice — mean absolute
error fell by up to 2.3 reps across six sessions — and the error is load-dependent: at 80% 1RM
lifters estimate RIR 3 accurately, while at 60% 1RM they substantially underestimate how many
reps remain (Wiedenmann et al. 2026, doi:10.1186/s13102-026-01997-y; Ferrari et al. 2026,
doi:10.21203/rs.3.rs-8899476/v1). A tight 2-3 veto therefore punishes estimation error as much as
effort.

**Closer to failure costs more fatigue.** Neuromuscular and perceptual fatigue rise as sets
approach failure (Cowley et al. 2026, doi:10.1080/02640414.2026.2703381; Varela-Olalla et al.,
*J Strength Cond Res* 2025, doi:10.1519/JSC.0000000000005194). That matters for a longevity-first
athlete with a back history.

**No direct injury evidence.** There is no good trial evidence that RIR 2-3 is safer than
RIR 1-4. The fatigue and technique-degradation argument is plausible but is reasoning, not data.

---

## Decision

`PRG-RIR-001` now:

- **allows RIR 1-4** on primary compounds;
- keeps **RIR 0 forbidden** (a grinding set is the failure mode the rule exists to prevent);
- keeps **max singles and 1RM testing inside a block forbidden**, except a declared test
  session (see `docs/TRAINING-DYNAMICS.md`);
- keeps **2-3 as the default target** — the prescription aims there, and the menu's
  "harder"/"easier" options move within 1-4.

Why not 0-5: RIR 0 is the fatigue/injury-adjacent case the athlete wants excluded, and RIR 5 is
far enough from failure that it is hard to call a working set. Why not keep 2-3: the evidence
does not support that floor, and RIR 1 is a legitimate strength exposure.

## How to change it again

The window lives in `config/rules/programme.v1.yaml` (`params.default_rir`) and in
`domain.rir.ALLOWED_RIR_WINDOW` (a consistency test keeps them equal). Changing it also changes:

- the proposal menu (wider window → more options),
- `validate_prescription`'s `RIR_OUTSIDE_WINDOW` check,
- the rubric's `RIR_ADHERENCE` score.

That is why a change needs a `DEC-` row and updated tests, not just a YAML edit.

---

Full bibliography with DOIs: [`docs/REFERENCES.md`](REFERENCES.md).
