# Variant pattern audit — 2026-10-20

Status: **approved and applied 2026-10-20** for the high-confidence pattern/muscle fixes. Targeted online check of the 115 generated identities, plus the pre-existing split-squat entry.
Most names were high-confidence by movement semantics; the exceptions below were checked online.

## Decisions / corrections

| raw | id | current pattern | proposed | confidence | status | note |
|---|---|---|---|---|---|---|
| Dumbbell Pullover | `dumbbell_pullover` | `lat_isolation` | `lat_isolation` | medium | **confirmed** | Kept as lat_isolation by decision. |
| Face Pull | `face_pull` | `rear_delt_pull` | `rear_delt_pull` | high | **applied** | Pattern is right; log Main_Muscle=front_delts is wrong. Face pull targets rear delts/rotator cuff. |
| Half-Kneeling Single Arm Cable Row | `half_kneeling_single_arm_cable_row` | `horizontal_pull` | `horizontal_pull` | high | **applied** | Pattern is right; log Main_Muscle=triceps is wrong. |
| Landmine Press | `landmine_press` | `vertical_push` | `vertical_push` | medium | **confirmed** | Hybrid angled press; kept as vertical_push by decision. |
| Rear Lateral Raise | `rear_lateral_raise` | `rear_delt_pull` | `rear_delt_pull` | high | **applied** | Pattern is right; log Main_Muscle=front_delts is wrong. |
| Reverse Nordic Curl | `reverse_nordic_curl` | `hamstring_eccentric` | `knee_extension` | high | **applied** | Reverse Nordic is a quadriceps eccentric; PubMed 39214520 and ExRx classify it with quadriceps, not hamstrings. Current hamstring_eccentric is wrong. |
| Seated Dumbbell External Rotation | `seated_dumbbell_external_rotation` | `rotator_cuff` | `rotator_cuff` | high | **applied** | Pattern is right; log Main_Muscle=front_delts is wrong. |
| Speed Bench Press | `speed_bench_press` | `horizontal_push` | `horizontal_push` | medium | **applied** | Pattern is right (power-intent bench); log Main_Muscle=front_delts is too narrow. |
| T Bar Row | `t_bar_row` | `horizontal_pull` | `horizontal_pull` | high | **applied** | Pattern is right; log Main_Muscle=upper_trap is too narrow. |
| Tib Bar Calves | `tib_bar_calves` | `plantar_flexion` | `dorsiflexion` | high | **applied** | Tibialis raise is ankle dorsiflexion, not plantarflexion. A separate `dorsiflexion` pattern was added deliberately with no readiness category. |
| Split Squat / Bulgarian Split Squat | `split_squat (existing)` | `squat` | `squat_unilateral` | high | **applied** | Existing taxonomy (not generated) has Split Squat/Bulgarian Split Squat as pattern:squat; they are unilateral. |

## Full table

| raw | id | current | proposed | muscles (current → proposed) | status |
|---|---|---|---|---|---|
| 1 Arm Row | `1_arm_row` | `horizontal_pull` | `horizontal_pull` | upper_back | keep |
| 1 Arm Tricep Pushdown | `1_arm_tricep_pushdown` | `triceps_extension` | `triceps_extension` | triceps | keep |
| Barbell Calf Raises | `barbell_calf_raises` | `plantar_flexion` | `plantar_flexion` | calves | keep |
| Barbell Curl | `barbell_curl` | `elbow_flexion` | `elbow_flexion` | biceps | keep |
| Belt Squat | `belt_squat` | `squat` | `squat` | quadriceps | keep |
| Bench Dips | `bench_dips` | `horizontal_push_bw` | `horizontal_push_bw` | triceps | keep |
| Bench Press (elevated legs) | `bench_press_elevated_legs` | `horizontal_push` | `horizontal_push` | chest | keep |
| Bench Press (explosive) | `bench_press_explosive` | `horizontal_push` | `horizontal_push` | chest | keep |
| Bench Press (from pins) | `bench_press_from_pins` | `horizontal_push` | `horizontal_push` | chest | keep |
| Bench Press (medium grip) | `bench_press_medium_grip` | `horizontal_push` | `horizontal_push` | chest | keep |
| Bench Press (negative) | `bench_press_negative` | `horizontal_push` | `horizontal_push` | chest | keep |
| Bench Press (reverse grip) | `bench_press_reverse_grip` | `horizontal_push` | `horizontal_push` | chest | keep |
| Bench Press (w/bands) | `bench_press_w_bands` | `horizontal_push` | `horizontal_push` | chest | keep |
| Bench Press (w/cambered bar) | `bench_press_w_cambered_bar` | `horizontal_push` | `horizontal_push` | chest | keep |
| Bench Press (w/chains) | `bench_press_w_chains` | `horizontal_push` | `horizontal_push` | chest | keep |
| Bench Press (wide grip) | `bench_press_wide_grip` | `horizontal_push` | `horizontal_push` | chest | keep |
| Bent Over Row | `bent_over_row` | `horizontal_pull` | `horizontal_pull` | upper_back | keep |
| Bird dog | `bird_dog` | `core_stability` | `core_stability` | abs | keep |
| Board Press | `board_press` | `horizontal_push` | `horizontal_push` | chest | keep |
| Cable Bent-over Triceps Extension | `cable_bent_over_triceps_extension` | `triceps_extension` | `triceps_extension` | triceps | keep |
| Cable Glute Kickback | `cable_glute_kickback` | `hip_extension` | `hip_extension` | glutes | keep |
| Cable Pull Through | `cable_pull_through` | `hip_extension` | `hip_extension` | hamstrings | keep |
| Close Grip Pulldown | `close_grip_pulldown` | `vertical_pull` | `vertical_pull` | lats | keep |
| Deadlift (above knees, off blocks) | `deadlift_above_knees_off_blocks` | `hinge` | `hinge` | glutes | keep |
| Deadlift (below knees, off blocks) | `deadlift_below_knees_off_blocks` | `hinge` | `hinge` | glutes | keep |
| Deadlift (below knees, off blocks, pause above) | `deadlift_below_knees_off_blocks_pause_above` | `hinge` | `hinge` | glutes | keep |
| Deadlift (from center block) | `deadlift_from_center_block` | `hinge` | `hinge` | hamstrings | keep |
| Deadlift (pause above knees) | `deadlift_pause_above_knees` | `hinge` | `hinge` | glutes | keep |
| Deadlift (pause below knees) | `deadlift_pause_below_knees` | `hinge` | `hinge` | glutes | keep |
| Deadlift (plus deadlift from above knees) | `deadlift_plus_deadlift_from_above_knees` | `hinge` | `hinge` | glutes | keep |
| Deadlift (plus deadlift from below knees) | `deadlift_plus_deadlift_from_below_knees` | `hinge` | `hinge` | glutes | keep |
| Deadlift (snatch grip, slow descent) | `deadlift_snatch_grip_slow_descent` | `hinge` | `hinge` | glutes | keep |
| Deadlift (to knees) | `deadlift_to_knees` | `hinge` | `hinge` | glutes | keep |
| Deadlift (to knees, plus full deadlift) | `deadlift_to_knees_plus_full_deadlift` | `hinge` | `hinge` | glutes | keep |
| Deadlift (w/bands) | `deadlift_w_bands` | `hinge` | `hinge` | glutes | keep |
| Deadlift (w/chains) | `deadlift_w_chains` | `hinge` | `hinge` | glutes | keep |
| Deadlift (w/chains, off blocks) | `deadlift_w_chains_off_blocks` | `hinge` | `hinge` | glutes | keep |
| Decline Bench Press | `decline_bench_press` | `horizontal_push` | `horizontal_push` | chest | keep |
| Deep Squat | `deep_squat` | `squat` | `squat` | quadriceps | keep |
| Deficit Deadlift (conventional) | `deficit_deadlift_conventional` | `hinge` | `hinge` | glutes | keep |
| Deficit Deadlift (pause above knees) | `deficit_deadlift_pause_above_knees` | `hinge` | `hinge` | glutes | keep |
| Deficit Deadlift (pause below knees) | `deficit_deadlift_pause_below_knees` | `hinge` | `hinge` | glutes | keep |
| Deficit Deadlift (sumo) | `deficit_deadlift_sumo` | `hinge` | `hinge` | glutes | keep |
| Deficit Deadlift (w/chains) | `deficit_deadlift_w_chains` | `hinge` | `hinge` | glutes | keep |
| Depth Jumps | `depth_jumps` | `power_jump` | `power_jump` | quadriceps | keep |
| Dips | `dips` | `horizontal_push_bw` | `horizontal_push_bw` | triceps | keep |
| Dumbbell Bench Press | `dumbbell_bench_press` | `horizontal_push` | `horizontal_push` | chest | keep |
| Dumbbell Chest Supported Row | `dumbbell_chest_supported_row` | `horizontal_pull` | `horizontal_pull` | lats | keep |
| Dumbbell Kickbacks | `dumbbell_kickbacks` | `triceps_extension` | `triceps_extension` | triceps | keep |
| Dumbbell Press (alternating) | `dumbbell_press_alternating` | `vertical_push` | `vertical_push` | front_delts | keep |
| Dumbbell Pullover | `dumbbell_pullover` | `lat_isolation` | `lat_isolation` | chest → lats,chest | confirmed |
| Dumbbell Row | `dumbbell_row` | `horizontal_pull` | `horizontal_pull` | lats | keep |
| Dumbbell Tricep Extension | `dumbbell_tricep_extension` | `triceps_extension` | `triceps_extension` | triceps | keep |
| Dumbell Curl (alternating) | `dumbell_curl_alternating` | `elbow_flexion` | `elbow_flexion` | biceps | keep |
| Face Pull | `face_pull` | `rear_delt_pull` | `rear_delt_pull` | front_delts → rear_delts,rotator_cuff | applied |
| Flat Dumbbell Flyes | `flat_dumbbell_flyes` | `horizontal_push_isolation` | `horizontal_push_isolation` | chest | keep |
| Flat-bench Sit-ups | `flat_bench_sit_ups` | `core` | `core` | abs | keep |
| Floor Press | `floor_press` | `horizontal_push` | `horizontal_push` | chest | keep |
| French Press | `french_press` | `triceps_extension` | `triceps_extension` | triceps | keep |
| Front Raise | `front_raise` | `shoulder_abduction` | `shoulder_abduction` | front_delts | keep |
| Front Squat | `front_squat` | `squat` | `squat` | quadriceps | keep |
| Front Squat (to box) | `front_squat_to_box` | `squat` | `squat` | quadriceps | keep |
| Hack Squat | `hack_squat` | `squat` | `squat` | quadriceps | keep |
| Half-Kneeling Single Arm Cable Row | `half_kneeling_single_arm_cable_row` | `horizontal_pull` | `horizontal_pull` | triceps → lats,upper_back | applied |
| High Bar Squat | `high_bar_squat` | `squat` | `squat` | quadriceps | keep |
| High To Low Cable Chop | `high_to_low_cable_chop` | `core` | `core` | abs | keep |
| Hip Thrust | `hip_thrust` | `hip_extension` | `hip_extension` | glutes | keep |
| Incline DB Bench Press | `incline_db_bench_press` | `horizontal_push` | `horizontal_push` | chest | keep |
| Incline Press | `incline_press` | `horizontal_push` | `horizontal_push` | chest | keep |
| Incline Sit-ups | `incline_sit_ups` | `core` | `core` | abs | keep |
| Jump Squats | `jump_squats` | `power_jump` | `power_jump` | quadriceps | keep |
| Kettlebell Swing | `kettlebell_swing` | `hinge_ballistic` | `hinge_ballistic` | glutes | keep |
| Landmine Press | `landmine_press` | `vertical_push` | `vertical_push` | front_delts → front_delts,triceps,chest | confirmed |
| Landmine Squat | `landmine_squat` | `squat` | `squat` | quadriceps | keep |
| Leg Extension | `leg_extension` | `knee_extension` | `knee_extension` | quadriceps | keep |
| Lying Leg Curls | `lying_leg_curls` | `knee_flexion` | `knee_flexion` | hamstrings | keep |
| Nordic Curl | `nordic_curl` | `hamstring_eccentric` | `hamstring_eccentric` | hamstrings | keep |
| Overhead Press (behind the neck) | `overhead_press_behind_the_neck` | `vertical_push` | `vertical_push` | front_delts | keep |
| Overhead Press (seated) | `overhead_press_seated` | `vertical_push` | `vertical_push` | front_delts | keep |
| Overhead Tricep Extension | `overhead_tricep_extension` | `triceps_extension` | `triceps_extension` | triceps | keep |
| Pallof Press | `pallof_press` | `core_stability` | `core_stability` | abs | keep |
| Preacher Curl | `preacher_curl` | `elbow_flexion` | `elbow_flexion` | biceps | keep |
| Pushups (chest emphasis) | `pushups_chest_emphasis` | `horizontal_push_bw` | `horizontal_push_bw` | chest | keep |
| Pushups (tricep emphasis) | `pushups_tricep_emphasis` | `horizontal_push_bw` | `horizontal_push_bw` | triceps | keep |
| Rear Lateral Raise | `rear_lateral_raise` | `rear_delt_pull` | `rear_delt_pull` | front_delts → rear_delts | applied |
| Reverse Nordic Curl | `reverse_nordic_curl` | `hamstring_eccentric` | `knee_extension` | quadriceps | applied |
| SL Glute Bridge | `sl_glute_bridge` | `hip_extension` | `hip_extension` | glutes | keep |
| Seal Row | `seal_row` | `horizontal_pull` | `horizontal_pull` | upper_back | keep |
| Seated Cable Row | `seated_cable_row` | `horizontal_pull` | `horizontal_pull` | upper_back | keep |
| Seated Calf Raises | `seated_calf_raises` | `plantar_flexion` | `plantar_flexion` | calves | keep |
| Seated Dumbbell External Rotation | `seated_dumbbell_external_rotation` | `rotator_cuff` | `rotator_cuff` | front_delts → rotator_cuff | applied |
| Shoulder Shrugs | `shoulder_shrugs` | `upper_trap` | `upper_trap` | upper_trap | keep |
| Side Lunges | `side_lunges` | `squat_unilateral` | `squat_unilateral` | quadriceps | keep |
| Single Arm Cable Triceps Kickback | `single_arm_cable_triceps_kickback` | `triceps_extension` | `triceps_extension` | triceps | keep |
| Single Leg DB RDL | `single_leg_db_rdl` | `hinge_unilateral` | `hinge_unilateral` | hamstrings | keep |
| Speed Bench Press | `speed_bench_press` | `horizontal_push` | `horizontal_push` | front_delts → chest,triceps,front_delts | applied |
| Squat (2s pause halfway down) | `squat_2s_pause_halfway_down` | `squat` | `squat` | quadriceps | keep |
| Squat (2s pause halfway up) | `squat_2s_pause_halfway_up` | `squat` | `squat` | quadriceps | keep |
| Squat (2s pause) | `squat_2s_pause` | `squat` | `squat` | quadriceps | keep |
| Squat (down slow, up fast) | `squat_down_slow_up_fast` | `squat` | `squat` | quadriceps | keep |
| Squat (from pins) | `squat_from_pins` | `squat` | `squat` | quadriceps | keep |
| Squat (narrow stance) | `squat_narrow_stance` | `squat` | `squat` | quadriceps | keep |
| Squat (negatives) | `squat_negatives` | `squat` | `squat` | quadriceps | keep |
| Squat (partial range of motion) | `squat_partial_range_of_motion` | `squat` | `squat` | quadriceps | keep |
| Squat (slow downwards & upwards) | `squat_slow_downwards_and_upwards` | `squat` | `squat` | quadriceps | keep |
| Squat (to box) | `squat_to_box` | `squat` | `squat` | quadriceps | keep |
| Squat (w/bands) | `squat_w_bands` | `squat` | `squat` | quadriceps | keep |
| Squat (w/chains) | `squat_w_chains` | `squat` | `squat` | quadriceps | keep |
| Standing Single-Arm Cable Curls (Shoulder Flexed) | `standing_single_arm_cable_curls_shoulder_flexed` | `elbow_flexion` | `elbow_flexion` | biceps | keep |
| Straight Arm Pulldown | `straight_arm_pulldown` | `lat_isolation` | `lat_isolation` | lats | keep |
| Straight Bar Cable Curl | `straight_bar_cable_curl` | `elbow_flexion` | `elbow_flexion` | biceps | keep |
| T Bar Row | `t_bar_row` | `horizontal_pull` | `horizontal_pull` | upper_trap → lats,upper_back | applied |
| Tib Bar Calves | `tib_bar_calves` | `plantar_flexion` | `dorsiflexion` | calves → tibialis_anterior | applied |
| Tricep Pushdown | `tricep_pushdown` | `triceps_extension` | `triceps_extension` | triceps | keep |
| Upright Row | `upright_row` | `shoulder_abduction` | `shoulder_abduction` | upper_trap | keep |
| Split Squat / Bulgarian Split Squat | `split_squat (existing)` | `squat` | `squat_unilateral` |  → quadriceps,glutes | applied |

## Sources used

- Reverse Nordic: [PubMed 39214520](https://pubmed.ncbi.nlm.nih.gov/39214520/)
- Tibialis raise / dorsiflexion: [tibialis raise](https://research.poin-t-go.com/en/exercises/tibialis-raise-shin-strength)
- Face pull: [Wikipedia](https://en.wikipedia.org/wiki/Face_pull_(exercise))
- T-bar row: [PureGym](https://www.puregym.com/exercises/back/rows/landmine-row/), [BarBend](https://barbend.com/news/how-to-t-bar-row-joe-bennett/)
- Dumbbell pullover: [Legion](https://legionathletics.com/dumbbell-pullover/)
- Landmine press: [Onnit](https://www.onnit.com/blogs/the-edge/the-expert-s-guide-to-the-landmine-press)
- Split squat: [Training & Conditioning](https://training-conditioning.com/article/splitting-your-squat/)
