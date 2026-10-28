# Hue · stop

| | |
|---|---|
| Result | pass |
| Date | 2026-10-28 |
| Source | rig run (`scripts/rig.py`), commit `33932a6` |
| Home Assistant | 2026.10.2 |
| Device | Hue ambiance lamp (`LTA009`), firmware `1.163.1`; Zone, firmware `unknown` |

## Tests

| Test | Target | Result |
|---|---|---|
| `halts_a_move[light_ct]` | `light` (light_ct) | pass |
| `halts_a_move[group]` | `light` (group) | pass |
| `halts_a_move_to_off[light_ct]` | `light` (light_ct) | pass |
| `halts_a_move_to_off[light_ct] observed` | `light` (light_ct) | not observed |
| `halts_a_move_to_off[group]` | `light` (group) | pass |
| `halts_a_move_to_off[group] observed` | `light` (group) | not observed |
| `stop_when_idle[light_ct]` | `light` (light_ct) | pass |
| `stop_when_idle[group]` | `light` (group) | pass |
| `halts_a_combined_move[light_ct]` | `light` (light_ct) | pass |
| `halts_a_combined_move[light_ct] observed` | `light` (light_ct) | not observed |
| `halts_a_combined_move[group]` | `light` (group) | pass |
| `halts_a_combined_move[group] observed` | `light` (group) | not observed |
| `halts_a_move_to_off_and_warmer[light_ct]` | `light` (light_ct) | pass |
| `halts_a_move_to_off_and_warmer[group]` | `light` (group) | pass |

Tests marked `not observed` had nobody watching.
