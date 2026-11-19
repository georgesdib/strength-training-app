# Resolver structure fixtures (synthetic)

Synthetic fixtures for WP0. No athlete data, no real export, no database copy.

| File | Use |
|---|---|
| `legacy_two_group_plan.json` | A legacy plan with role-based `set_groups`; read by list order. |
| `ordered_three_group_plan.json` | The ordered 1..N representation with no role; a display and validation fixture. The engine does not emit three groups. |
| `straight_set_plan_top_backoff_performance.json` | A straight-set plan performed as a top-set-like exposure plus back-offs; feeds the derived-structure and matching tests. |
| `rir6_import_row.csv` | An imported row at RPE 4, which the current RPE mapping turns into RIR 6; the WP5 import boundary. |
| `deload_taper_cases.json` | Blocked-by-design (`not_applicable`) versus unexpected (`unsatisfied`) structure status. |

The fixtures are consumed by backend tests in WP1/WP5. WP2 adds the client-side copies
needed for rendering; they must stay identical in shape.
