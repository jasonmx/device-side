# Hue · move

| | |
|---|---|
| Result | pass |
| Date | 2026-10-27 |
| Source | rig run (`scripts/rig.py`), commit `bfba654` |
| Fingerprint | `31adc08629d34287` (`integrations/hue/move.py`) |
| Home Assistant | 2026.10.2 |
| Device | Hue ambiance lamp (`LTA009`), firmware `1.163.1`; Zone, firmware `unknown` |
| Capabilities | every capability the adapter addresses |
| Fields | `brightness`, `brightness_limit`, `color_temp`, `color_temp_limit` |

## Tests

| Test | Target | Result |
|---|---|---|
| `raise[light_ct]` | `light` (light_ct) | pass |
| `raise[light_ct] observed` | `light` (light_ct) | not observed |
| `raise[group]` | `light` (group) | pass |
| `raise[group] observed` | `light` (group) | not observed |
| `lower_to_off[light_ct]` | `light` (light_ct) | pass |
| `lower_to_off[light_ct] observed` | `light` (light_ct) | not observed |
| `lower_to_off[group]` | `light` (group) | pass |
| `lower_to_off[group] observed` | `light` (group) | not observed |
| `raise_from_off[light_ct]` | `light` (light_ct) | pass |
| `raise_from_off[group]` | `light` (group) | pass |
| `raise_after_soft_off[light_ct] observed` | `light` (light_ct) | not observed |
| `raise_after_soft_off[group] observed` | `light` (group) | not observed |
| `lower_to_a_limit[light_ct]` | `light` (light_ct) | pass |
| `lower_to_a_limit[group]` | `light` (group) | pass |
| `raise_stop_raise[light_ct]` | `light` (light_ct) | pass |
| `raise_stop_raise[light_ct] observed` | `light` (light_ct) | not observed |
| `raise_stop_raise[group]` | `light` (group) | pass |
| `raise_stop_raise[group] observed` | `light` (group) | not observed |
| `lower_stop_lower[light_ct]` | `light` (light_ct) | pass |
| `lower_stop_lower[group]` | `light` (group) | pass |
| `light_moved_mid_room_move[group]` | `light` (group) | pass |
| `light_moved_mid_room_move[group] observed` | `light` (group) | not observed |
| `ha_change_mid_move[light_ct]` | `light` (light_ct) | pass |
| `ha_change_mid_move[group]` | `light` (group) | pass |
| `late_stop_report[light_ct]` | `light` (light_ct) | pass |
| `late_stop_report[group]` | `light` (group) | pass |
| `warmer[light_ct]` | `light` (light_ct) | pass |
| `warmer[group]` | `light` (group) | pass |
| `cooler_to_a_limit[light_ct]` | `light` (light_ct) | pass |
| `cooler_to_a_limit[group]` | `light` (group) | pass |
| `warmer_stop_warmer[light_ct]` | `light` (light_ct) | pass |
| `warmer_stop_warmer[light_ct] observed` | `light` (light_ct) | not observed |
| `warmer_stop_warmer[group]` | `light` (group) | pass |
| `warmer_stop_warmer[group] observed` | `light` (group) | not observed |
| `color_temp_at_limit[light_ct]` | `light` (light_ct) | pass |
| `color_temp_at_limit[group]` | `light` (group) | pass |
| `color_temp_on_off_light[light_ct]` | `light` (light_ct) | pass |
| `color_temp_on_off_light[group]` | `light` (group) | pass |
| `brighter_and_cooler[light_ct]` | `light` (light_ct) | pass |
| `brighter_and_cooler[light_ct] observed` | `light` (light_ct) | not observed |
| `brighter_and_cooler[group]` | `light` (group) | pass |
| `brighter_and_cooler[group] observed` | `light` (group) | not observed |

Tests marked `not observed` had nobody watching; their fields and capabilities are not listed.
