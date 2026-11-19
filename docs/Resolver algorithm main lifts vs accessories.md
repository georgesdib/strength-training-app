**Resolver algorithm: main lifts vs accessories**  
The resolver is a deterministic, policy-driven exercise-selection and prescription algorithm. It is implemented primarily in the Python backend, in strength_coach/prescribe/.  
The important distinction is that it does not simply select the exercise with the highest individual score. It constructs eligible candidate pools, searches combinations of exercises across the entire session, evaluates those combinations through the actual prescription engine, and selects the best feasible complete session.  
This is a joint optimisation problem rather than a collection of independent exercise recommendations.  
The implementation also deliberately separates three responsibilities:  
* Blueprint: defines what the session is supposed to accomplish.  
* Generator: determines which exercises are eligible for each slot.  
* Beam search and evaluator: determine which combination produces the best executable prescription.  
The resolver is optional and remains disabled by default. When disabled, the existing fixed-template pathway is preserved.  
**1. Step one: identify the session and its slots**  
The resolver starts with the requested training date and session type.  
The four canonical session types are:  
* Squat  
* Hinge  
* Bench + squat  
* Bench + hinge  
It loads the corresponding SessionTemplate from templates.py.  
A template contains individual slots, each with attributes such as:  
* Slot ID.  
* Default exercise and possible variants.  
* Movement pattern.  
* Number of sets.  
* Rep range.  
* RIR range.  
* Rest period.  
* Whether the slot is essential.  
* Whether it is a power exercise.  
* Load source and quality-stop requirements.  
The resolver identifies three relevant exercise roles:  

| Role | Identification | Selection constraint |
| ---------------------- | -------------------------------- | ------------------------------------------------------- |
| Primary main lift | Template’s primary exercise slot | Must remain within the primary lift’s movement pattern |
| Secondary/support lift | Essential non-power slot | Must remain within its blueprint movement pattern |
| Accessory | Non-essential, non-power slot | Can use policy-authorised alternative movement patterns |
  
Power slots are a fourth special case: they are fixed rather than dynamically selected.  
This distinction is important. An accessory is not simply a less important main lift. It has a fundamentally different degree of movement-pattern freedom.  
Relevant implementation: ++[generator.py](https://github.com/georgesdib/strength-training-app/blob/development/strength_coach/prescribe/generator.py?utm_source=chatgpt.com)++⁠ and ++[templates.py](https://github.com/georgesdib/strength-training-app/blob/development/strength_coach/prescribe/templates.py?utm_source=chatgpt.com)++⁠.  
**2. Step two: construct the candidate pool for every slot**  
The resolver obtains candidate exercises from the existing exercise catalogue, referenced through:  
```
config/variants.v1.yaml
```
The structural resolver policy can also define explicit slot-specific pools. An explicit pool takes precedence over the default exercise list and catalogue variants.  
The candidate list is therefore not generated from scratch. It is selected from a curated universe of exercises.  
For example, the hinge policy explicitly defines:  
```
slot_pools:
  hinge:
    hinge_main:
      - trap_bar_deadlift
      - sumo_deadlift
      - deadlift_w_bands
      - deadlift_w_chains
      - deadlift_w_chains_off_blocks
      - deficit_deadlift_w_chains
```
This is important because the standard catalogue does not have a hinge-main entry covering these alternatives.  
**The difference between main lifts and accessories**  
The most important difference is introduced when the resolver determines which movement patterns are permitted.  
The relevant function is _permitted_patterns().  
Primary main lift  
The primary main lift is restricted to the movement pattern of the original main lift.  
For example:  
* Squat session: squat remains squat.  
* Hinge session: hinge remains hinge.  
* Bench + squat: the main bench lift remains horizontal push.  
* Bench + hinge: the main bench lift remains horizontal push.  
The resolver cannot replace the primary squat with a leg press or the primary bench press with a shoulder press simply because those alternatives might score better.  
Secondary/support lift  
The secondary lift is also constrained to its original movement pattern.  
This preserves the structural identity of the session while allowing exercise variation within that identity.  
Accessories  
Accessories have explicitly configurable pattern flexibility.  
The current policy contains:  

| Accessory slot           | Permitted patterns                             |
| ------------------------ | ---------------------------------------------- |
| Accessory row            | Horizontal pull, vertical pull, rear-delt pull |
| Accessory pull-up        | Vertical pull, horizontal pull, lat isolation  |
| Accessory vertical press | Vertical push, horizontal push                 |
| Accessory knee flexion   | Knee flexion, hamstring eccentric              |
| Erector                  | Erector extension                              |
| Core anti-extension      | Core anti-extension, core stability            |
| Core flexion             | Core flexion, core stability                   |
| Accessory split squat    | Unilateral squat                               |
  
This is where the algorithm becomes particularly useful.  
For example, an accessory row slot can choose between a horizontal pulling exercise and a vertical pulling exercise, depending on what the rest of the session and weekly training requirements need.  
It does not have to preserve the original horizontal-pull pattern.  
The main lift cannot make that trade.  
One qualification: the policy’s flexibility is explicit, not unrestricted. An accessory can only move into patterns authorised for its slot.  
Source: ++[template-resolver.v1.yaml](https://github.com/georgesdib/strength-training-app/blob/development/config/template-resolver.v1.yaml?utm_source=chatgpt.com)++⁠.  
**3. Step three: apply hard eligibility filters**  
Once the raw candidate pools have been assembled, the resolver checks whether each exercise is actually eligible.  
This is one of the most important parts of the algorithm.  
The implementation uses _candidate_class() and _classify_candidates().  
Each candidate ends up in one of three categories:  
Automatic  
Eligible  
Can be selected without additional confirmation.  
Suggestion  
Confirmation  
Can be displayed to the athlete but cannot be silently selected as an automatic choice.  
Excluded  
Ineligible  
Cannot be selected or used as an automatic fallback.  
The filters are applied in the following order.  
**3.1 Movement-pattern eligibility**  
The exercise must belong to the patterns permitted for its slot.  
An otherwise excellent exercise is excluded if it violates the slot’s structural requirements.  
**3.2 Stored constraints**  
The resolver calls the constraints module and excludes exercises with hard stored contraindications.  
These are vetoes, not preferences.  
**3.3 Active injury signals**  
The resolver calculates current injury signals and checks whether an exercise is linked to an actively affected region.  
Exercises associated with active injury signals are excluded.  
This is separate from the soft injury-related scoring used in the earlier generator.  
## 3.4   
```
can_do
```
This is the most important suitability distinction.  
* can_do = false: excluded.  
* can_do = true: passes this requirement.  
* No suitability rating: behaviour depends on the configuration.  
When require_can_do is enabled:  
* unrated_mode = confirm: an unrated exercise becomes suggestion-only.  
* unrated_mode = exclude: an unrated exercise is excluded.  
When require_can_do is disabled, unrated candidates can be selected automatically.  
## 3.5   
```
will_do
```
## and   
```
feels_bad
```
These are not treated like hard contraindications.  
* will_do = false: suggestion-only or hidden, depending on configuration.  
* feels_bad = true: suggestion-only or hidden, depending on configuration.  
Neither can silently become an automatic choice.  
**3.6 Dwell and rotation**  
The algorithm also incorporates exercise dwell.  
The dwell counter tracks how frequently an exercise has been used since its last reset.  
Candidates at or above the configured dwell target are removed from the normal candidate pool.  
If every candidate exceeds the target, the algorithm retains the pool and issues a warning rather than making the slot impossible.  
There is also a rotation probability, which controls whether the previous exercise is temporarily excluded from the standalone generator’s selection.  
One important implementation distinction: the production joint resolver uses the eligibility/dwell filtering, but does not apply the standalone generator’s rotation draw to reorder its candidate pools.  
That matters when interpreting the actual production algorithm.  
**3.7 Candidate-pool structural feasibility**  
Finally, the generator checks whether the remaining eligible candidates can satisfy the session’s required movement patterns.  
This uses a small bipartite matching algorithm.  
The important detail is that each required pattern must be covered by a distinct slot.  
For example, if the session requires horizontal pull and vertical pull, one slot cannot satisfy both requirements merely because its candidate pool contains exercises from both patterns. The eventual assignment must provide the required patterns across distinct slots.  
If a slot has no eligible candidates, or the required patterns cannot be assigned, pool generation fails.  
There is no silent substitution of the original blueprint exercise.  
Source: ++[generator.py](https://github.com/georgesdib/strength-training-app/blob/development/strength_coach/prescribe/generator.py?utm_source=chatgpt.com)++⁠.  
**4. Step four: establish the session’s structural requirements**  
Before searching combinations, the resolver loads the required movement patterns from the YAML policy.  
These are session-specific.  
The current requirements are:  

| Session | Required patterns |
| ------------- | --------------------------------------------------------------------------------------------- |
| Squat | Squat, horizontal push, horizontal pull, erector extension, knee flexion, core anti-extension |
| Hinge | Hinge, horizontal push, vertical pull, horizontal pull, unilateral squat, knee flexion |
| Bench + squat | Horizontal push, squat, horizontal pull, vertical push, core anti-extension |
| Bench + hinge | Horizontal push, hinge, vertical pull, horizontal pull, vertical push, core flexion |
  
These requirements serve as structural constraints on the final assignment.  
They are not simply recommendations.  
For example, suppose a squat session has an accessory row slot that can choose:  
* A horizontal row.  
* A vertical pull.  
* A rear-delt pull.  
And another slot that can choose:  
* A knee-flexion exercise.  
* A hamstring eccentric exercise.  
The algorithm must select a combination that preserves the required pattern coverage.  
This allows the resolver to make substitutions without accidentally changing the training stimulus of the session.  
**Why this matters for accessories**  
This is where accessories gain their real optimisation advantage.  
Imagine the athlete has already accumulated sufficient horizontal pulling volume earlier in the week, but vertical pulling volume is behind target.  
The resolver can potentially use an accessory slot to supply vertical pulling instead.  
The primary main lift cannot make this kind of substitution.  
The accessory therefore acts as a flexible mechanism for balancing the training programme while preserving the main session identity.  
There is also a redundancy constraint in the policy:  
```
redundancy:
  max_per_pattern: 2
  max_per_primary_muscle: 2
```
This prevents the session from becoming excessively concentrated around the same movement pattern or primary muscle group.  
However, note that these limits are not absolute hard constraints in the production beam evaluator. They are part of the earlier standalone generator’s scoring. The production path relies on its structural requirements and full prescription evaluation.  
**5. Step five: build the candidate pools for joint optimisation**  
This is a particularly important architectural distinction.  
The generator has two different operating modes:  
* generate(): standalone, greedy exercise selection.  
* candidate_pools(): production resolver input for joint optimisation.  
The production resolver calls candidate_pools().  
It does not simply call generate() and take its highest-scoring exercise choices.  
This is intentional.  
The candidate pools contain:  
* The template.  
* The ordered eligible candidates for every slot.  
* The primary main-lift slot.  
* Required movement patterns.  
* Candidate-to-pattern mappings.  
* Suggestion-only candidates.  
* Policy and catalogue digests.  
The order of candidates is deterministic and comes from the template and catalogue ordering.  
This is a significant point: the production beam does not initially rank each exercise using the standalone generator’s readiness/fatigue score.  
Instead, it passes the ordered pools to the beam search.  
The reason is to avoid double-counting the generator’s individual scoring objective when the actual session is subsequently evaluated as a whole.  
**What happened to the individual scoring algorithm?**  
The standalone _score() function still exists.  
It evaluates five components:  

| Component | What it measures                        |
| --------- | --------------------------------------- |
| Readiness | Exercise-specific readiness suitability |
| Fatigue   | Recent stress exposure                  |
| Spinal    | Projected spinal loading                |
| Injury    | Injury-related exercise suitability     |
| Dwell     | Exercise usage/dwell                    |
  
It then combines these using configurable weights, coverage priority and a redundancy penalty.  
Conceptually:  
# S_{\text{individual}} =  
##    
## \frac{\sum_i w_i s_i}{\sum_i w_i}  
##    
## +  
##    
## \lambda(C-0.5)  
R  
Where:  
* represents the individual exercise component.  
* is its configured weight.  
* is weekly movement-pattern coverage.  
* is the redundancy penalty.  
* depends on coverage priority.  
Higher scores are better in this standalone generator.  
However, this is not the final production resolver’s assignment objective.  
The production resolver instead evaluates complete assignments through the actual prescription engine.  
That is a better approach for your objectives because an exercise cannot be judged independently of the other exercises, their prescribed workloads, and the athlete’s current training state.  
**6. Step six: bounded beam search**  
Core optimisation stage  
The production resolver now passes the candidate pools to:  
```
strength_coach/prescribe/beam.py
```
This is where the actual combination search takes place.  
The beam search is deterministic and bounded.  
Its defaults are:  

| Parameter                   | Default |
| --------------------------- | ------- |
| Beam width                  | 4       |
| Maximum candidates per slot | 6       |
| Full evaluation budget      | 4       |
  
The full evaluation budget is configurable through resolver settings. The beam width remains fixed in the production configuration.  
**6.1 Candidate truncation**  
The algorithm first limits each slot to its first six eligible candidates.  
There is an important exception.  
It protects candidates necessary to cover required movement patterns, even if those candidates appear beyond the first six positions.  
This prevents the candidate cap from accidentally removing the only exercise capable of satisfying an important session requirement.  
**6.2 Start with an empty assignment**  
The algorithm starts with one partial assignment:  
A_0 = \{\}  
It then processes slots in template order.  
For each slot, it expands every existing partial assignment with each candidate in that slot’s pool.  
For example, suppose there are three slots:  
Illustrative candidate pools  
Main lift  
3 candidates  
Squat ASquat BSquat C  
Accessory 1  
3 candidates  
Row AVertical pull BRear delt C  
Accessory 2  
3 candidates  
Knee flexion AHamstring BKnee flexion C  
The theoretical number of complete assignments is:  
3 \times 3 \times 3 = 27  
In a real session, the candidate pools can be larger, so unrestricted enumeration would become expensive.  
**6.3 Structural pruning**  
After expanding a slot, the beam checks whether each partial assignment can still satisfy the outstanding required movement patterns using the remaining slots.  
If it cannot, the branch is discarded immediately.  
For example:  
* Horizontal pull is still required.  
* Only one slot remains.  
* That slot has no horizontal-pull candidates.  
That partial assignment is discarded.  
This is an important optimisation because the algorithm avoids spending full prescription evaluations on combinations that are structurally invalid.  
**6.4 Beam-width pruning**  
The remaining partial assignments are sorted by a deterministic ordering.  
The ordering cost is:  
C(A) = \sum_{j=1}^{n} r_j  
Where is the candidate’s position in its respective slot pool, starting at zero.  
The tie-break order is:  
* Lowest total candidate rank.  
* Lexicographically lowest rank tuple.  
* Assignment tuple.  
Only the best four partial assignments survive.  
Important: this is not an exercise-quality score. It is a computational ordering heuristic.  
The algorithm does not yet know whether the resulting session will have appropriate loads, volume, spinal exposure or estimated duration.  
**6.5 Full evaluation**  
Once all slots have been assigned, the algorithm has at most four complete assignments.  
It then evaluates up to the configured full-evaluation budget.  
This is the critical transition from cheap combinatorial search to expensive physiological and prescription evaluation.  
The beam records:  
* Number of assignments evaluated.  
* Number pruned by beam width.  
* Structural pruning.  
* Candidates removed by the candidate cap.  
* Final assignments removed by the evaluation budget.  
* Whether the search was exhaustive.  
One subtle but important limitation: the beam is not guaranteed to find the globally optimal assignment.  
It is a bounded search, not an exhaustive optimiser. A good combination can theoretically be discarded by the beam-width heuristic before the full evaluator sees it.  
Source: ++[beam.py](https://github.com/georgesdib/strength-training-app/blob/development/strength_coach/prescribe/beam.py?utm_source=chatgpt.com)++⁠.  
**7. Step seven: evaluate each complete assignment through the real prescription engine**  
This is arguably the most important architectural decision in the entire implementation.  
The resolver does not invent a second prescription engine.  
Instead, every complete assignment is passed to:  
```
strength_coach/prescribe/evaluator.py
```
The evaluator builds a concrete template containing the selected exercises and invokes the existing build_prescription() pipeline.  
The selection is explicitly protected:  
* The assignment must cover every slot.  
* Each selected exercise must belong to that slot’s eligible pool.  
* No missing or unknown slots are permitted.  
* Selection overrides are disabled.  
* The normal prescription engine is called with use_resolver=False to prevent recursive resolver execution.  
The prescription engine then applies the actual training rules.  
**7.1 Readiness**  
The engine applies the athlete’s current readiness and associated load adjustments.  
This is not just an exercise-level readiness score. It affects the actual prescription.  
**7.2 Continuity and progression**  
The normal progression mechanisms are applied using the athlete’s training history.  
This includes the existing lift-specific progression and e1RM logic.  
**7.3 Deload**  
The existing deload decision is applied.  
The resolver does not independently decide that an athlete should deload.  
It uses the established deload system.  
**7.4 Spinal exposure**  
The complete prescription is evaluated against the spinal exposure rules and weekly cap.  
This is particularly important when comparing different hinge variations.  
For example, the policy comments explicitly distinguish the spinal costs of the hinge-main candidates:  

| Exercise                                         | Spinal cost |
| ------------------------------------------------ | ----------- |
| Trap-bar deadlift                                | 2           |
| Sumo deadlift                                    | 2.5         |
| Conventional deadlift with bands/chains variants | 3           |
  
These differences can affect whether the resulting weekly programme is feasible.  
**7.5 Volume budget**  
The existing volume engine is applied.  
This is critical because the resolver needs to evaluate the actual outcome after the volume budget has been applied, rather than assuming the original template’s volume will survive unchanged.  
The engine evaluates the post-budget volume distribution.  
**7.6 Time estimation**  
The prescription engine estimates the duration of the session.  
It can therefore identify combinations that are likely to exceed the planned time target.  
**7.7 Validation and constraints**  
Finally, the existing prescription validation and constraint pipeline runs.  
The result is a real prescription, not an abstract exercise list.  
This means that the resolver evaluates the downstream consequences of its exercise choices.  
It also means that a candidate assignment can be rejected if the prescription engine changes or replaces the selected exercises.  
Source: ++[evaluator.py](https://github.com/georgesdib/strength-training-app/blob/development/strength_coach/prescribe/evaluator.py?utm_source=chatgpt.com)++⁠.  
**8. Step eight: score the complete prescriptions**  
Once the real prescription has been built, the evaluator extracts its measurable outcomes.  
It uses a lower-is-better score.  
The current scoring weights are:  

| Component                     | Penalty               |
| ----------------------------- | --------------------- |
| Validation/constraint issues  | 10 per issue          |
| Non-executable prescription   | 2                     |
| Unknown load                  | 2 per unknown load    |
| Spinal cap exceeded           | 3                     |
| Session over planned duration | 1 + minutes over / 30 |
| Volume target error           | 2 × normalised error  |
| Prescription warnings         | 0.05 per warning      |
| Session/template replaced     | 5                     |
| Structural violations         | 10                    |
  
The volume error is calculated as:  
E_V = \frac{\sum_g |V_{g,\text{after}}-V_{g,\text{target}}|} {\sum_g V_{g,\text{target}}}  
Only groups with positive volume targets are included.  
The complete score is therefore approximately:  
S = 10N_{\text{issues}} +2I_{\text{non-executable}} +2N_{\text{unknown loads}} +3I_{\text{spinal}} +\left(1+\frac{T_{\text{over}}}{30}\right)I_{\text{time}} +2E_V +0.05N_{\text{warnings}} +P_{\text{replacement}} +P_{\text{structural}}  
Where the replacement and structural penalties are applied when applicable.  
The exact implementation is in score_components() and the subsequent assignment evaluation logic.  
**8.1 Hard feasibility versus soft optimisation**  
This distinction is particularly important.  
The resolver does not simply choose the prescription with the lowest numerical score.  
First, an assignment must pass hard feasibility.  
An assignment is feasible only when:  
* The prescription is executable.  
* There are no validation or constraint issues.  
* The weekly spinal cap is not exceeded.  
* The exact selected exercises are preserved.  
* The session has not been replaced.  
* Required movement patterns are satisfied.  
Time overruns, volume-target deviations and warnings are soft objectives.  
They influence the ranking of otherwise feasible prescriptions, but do not independently make an assignment infeasible.  
This is deliberate.  
For example, a session estimated at 65 minutes against a 60-minute target can still be feasible. It simply receives a penalty.  
Likewise, a session with some deviation from the volume target can still win if it has a better overall outcome.  
**8.2 How the winner is selected**  
The beam separates feasible and infeasible assignments.  
It then selects:  
A^* = \arg\min_{A \in \mathcal{F}} S(A)  
Where is the set of evaluated feasible assignments.  
If two assignments have the same score, the deterministic candidate-rank ordering breaks the tie.  
If no assignment is feasible, the resolver fails and returns diagnostic information about the best evaluated alternative.  
It does not quietly use the original blueprint.  
**8.3 Why this matters for main lifts versus accessories**  
Consider a simplified example.  
Suppose the resolver has two possible main lifts:  
* Squat A: slightly worse fatigue profile, but good progression continuity.  
* Squat B: better recent-fatigue profile, but higher spinal exposure.  
It also has two accessory alternatives:  
* Accessory A: preserves horizontal pulling.  
* Accessory B: supplies vertical pulling, which is currently more needed.  
The resolver evaluates complete combinations, not four independent scores.  
The best main lift might be Squat A, even though Squat B has a better individual fatigue profile.  
Likewise, Accessory B might be selected because its effect on the complete prescription is better.  
The final decision therefore reflects the interaction between:  
* The main lift.  
* Support lift.  
* Accessories.  
* Existing training history.  
* Weekly spinal exposure.  
* Volume budget.  
* Session duration.  
* Prescription executability.  
This is the main advantage of the current architecture.  
**9. Step nine: final integrity checks**  
After selecting the winning assignment, resolver.py performs additional checks.  
It verifies:  
* Required patterns are still satisfied.  
* The prescription retained the exact assigned exercise list.  
* The session type remains unchanged.  
* The generated prescription has valid provenance.  
* The snapshot can be validated.  
These checks are important because the evaluator is not trusted merely because it returned the lowest score.  
The winning prescription must satisfy the final production contract.  
If it fails, the resolver raises a structured ResolverBuildError.  
The error identifies the stage:  
* dispatch  
* pool_generation  
* assignment_search  
* prescription_evaluation  
* final_integrity  
This also makes failures easier to diagnose through the CLI, API and preview interface.  
**10. Step ten: preserve the result and its provenance**  
The resolver does not simply save the exercise IDs.  
It stores a generated-session snapshot containing:  
* Selected exercise per slot.  
* Original slot specifications.  
* Sets and rep ranges.  
* RIR range.  
* Rest.  
* Essential/power flags.  
* Load source.  
* Quality-stop requirements.  
* Template digest.  
* Policy digest.  
* Catalogue digest.  
* Input fingerprint.  
* Candidate pools.  
* Beam configuration.  
* Beam diagnostics.  
* Evaluation result.  
* Top-set information.  
The fingerprint is generated using deterministic canonicalisation and SHA-256.  
The current fingerprint version is prescription-input-v3.  
An important qualification: this is an audit fingerprint of the material inputs, candidate pools and configuration. It is not a guarantee that every historical database row is captured or that the prescription can be reconstructed from the fingerprint alone.  
The snapshot is particularly important for historical interpretation.  
If you subsequently change the resolver policy, an old prescription must still be interpreted according to the original assignment and slot structure, not the current policy.  
This is why the generated-session snapshot is also used by the historical critique and volume-accounting paths.  
**11. Two additional mechanisms worth understanding**  
**11.1 Minimum-session mode**  
The resolver supports a shortened-session mode.  
This is not simply a normal session with fewer sets.  
The resolver first constructs a reduced session shape, based on the requested duration and whether the main lift should be retained.  
It then generates candidate pools for the reduced template.  
For normal sessions, required movement patterns are retained only if they can be covered by the retained slots. Patterns associated exclusively with removed slots are recorded as omitted.  
For accessory-only mode, there is no main-lift coverage requirement.  
The remaining accessory slots still undergo normal eligibility, structural and redundancy checks.  
The reduced session then enters the same beam-search and evaluation process.  
This is important because the resolver optimises the actual shortened session rather than generating a full session and simply deleting exercises afterwards.  
**11.2 Top-set/back-off structure**  
Top-set selection is separate from exercise selection.  
The resolver chooses the exercise assignment first, then the normal prescription engine determines whether a top-set/back-off structure is appropriate.  
Only explicitly eligible primary main lifts can receive this structure.  
The current policy includes selected squat, deadlift and bench variants.  
Accessories do not receive top sets.  
The structure is also conditional on the caller’s request and the existing training rules:  
* Deload and taper suppress top sets.  
* The main scheme determines the target RIR.  
* Competition peak settings can override the normal target.  
* Top-set and back-off sets together preserve the original working-set total.  
* Top-set structure is never silently applied to accessories.  
This is a separate prescription-level decision, not another candidate-ranking mechanism.  
**12. Main lifts versus accessories: complete comparison**  
Here is the distinction across the entire algorithm.  

| Dimension | Primary main lift | Secondary/support lift | Accessories |
| ---------------------------- | --------------------------------- | ----------------------------- | ------------------------- |
| Candidate source | Catalogue / explicit pool | Catalogue / explicit pool | Catalogue / explicit pool |
| Pattern flexibility | Restricted to primary pattern | Restricted to support pattern | Explicitly configurable |
| Suitability filters | Yes | Yes | Yes |
| Injury exclusions | Yes | Yes | Yes |
| can_do requirement | Yes | Yes | Yes |
| will_do / feels_bad | Yes | Yes | Yes |
| Dwell filtering | Yes | Yes | Yes |
| Required pattern coverage | Usually provides core coverage | Contributes to coverage | Can fill missing patterns |
| Joint beam search | Yes | Yes | Yes |
| Full prescription evaluation | Yes | Yes | Yes |
| Progression continuity | Existing lift-specific mechanisms | Existing mechanisms | Existing mechanisms |
| Top set/back-off | Potentially eligible | No | No |
  
The most important distinction is that accessories have greater structural freedom, not a different prescription engine.  
All exercises are subject to the same final prescription pipeline.  
**13. My interpretation of the algorithm**  
There are three particularly important design decisions.  
1. Main lifts preserve programme identity.  
The main lift is not freely interchangeable with other exercises that happen to train similar muscles.  
This protects the progression and performance-tracking objectives of the programme.  
For example, rotating between different squat variations is acceptable, but replacing the squat with a leg press would fundamentally change the training objective.  
2. Accessories optimise the distribution of training stimulus.  
This is where the resolver has its greatest flexibility.  
Accessory selection can compensate for movement-pattern requirements and existing weekly volume distribution without changing the fundamental session identity.  
The distinction between a main lift and an accessory is therefore functional, not simply based on how many sets are prescribed.  
3. The actual prescription outcome determines the winner.  
This is the strongest part of the architecture.  
An exercise is not selected because an individual heuristic thinks it is optimal.  
It is selected because its inclusion in a particular combination produces the best feasible result after the actual prescription engine has applied readiness, progression, deload, spinal constraints, volume management and duration estimation.  
There are also two important limitations worth keeping in mind:  
* The beam search is approximate. A candidate combination can be pruned before receiving a full evaluation.  
* The score weights are heuristic ordering weights, not scientifically calibrated estimates of physiological utility.  
I would not describe the resulting prescription as a mathematically optimal training programme. It is the best feasible prescription found within a deliberately bounded search.  
**14. One particularly important distinction I want to highlight**  
There is a subtle architectural detail that is easy to miss when reading the code.  
The standalone generator still contains an individual exercise-ranking system based on readiness, fatigue, spinal cost, injury, dwell, coverage and redundancy.  
However, the actual production resolver uses candidate_pools() followed by beam.search() and the full evaluator.  
It deliberately does not apply the standalone _rank() score to the production candidate pools.  
That is the correct separation if the intention is to optimise the outcome of the complete session rather than optimise each exercise independently.  
I would preserve this distinction.  
The files I would consider the authoritative implementation references are:  
* ++[resolver.py](https://github.com/georgesdib/strength-training-app/blob/development/strength_coach/prescribe/resolver.py?utm_source=chatgpt.com)++⁠ — orchestration and final integrity.  
* ++[generator.py](https://github.com/georgesdib/strength-training-app/blob/development/strength_coach/prescribe/generator.py?utm_source=chatgpt.com)++⁠ — candidate eligibility and pattern constraints.  
* ++[beam.py](https://github.com/georgesdib/strength-training-app/blob/development/strength_coach/prescribe/beam.py?utm_source=chatgpt.com)++⁠ — combinatorial search.  
* ++[evaluator.py](https://github.com/georgesdib/strength-training-app/blob/development/strength_coach/prescribe/evaluator.py?utm_source=chatgpt.com)++⁠ — actual prescription evaluation and scoring.  
* ++[template-resolver.v1.yaml](https://github.com/georgesdib/strength-training-app/blob/development/config/template-resolver.v1.yaml?utm_source=chatgpt.com)++⁠ — structural policy.  
My overall assessment is that the architecture is sound: it separates exercise eligibility, structural constraints, combinatorial selection and physiological prescription evaluation rather than trying to solve everything with one exercise-scoring formula.  
