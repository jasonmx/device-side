# Zigbee2MQTT · stop

| | |
|---|---|
| Result | pass |
| Date | 2026-10-28 |
| Source | rig run (`scripts/rig.py`), commit `33932a6` |
| Home Assistant | 2026.10.2 |
| Device | Hue white ambiance E27 800lm with Bluetooth (`8719514328242`), firmware `1.76.11`; Group, firmware `Zigbee2MQTT 2.14.2`; Hue Essential White and Color Ambiance A60 (`8720169392182`), firmware `1.126.9` |

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
| `hue_cycle_stop[light_color]` | `light` (light_color) | pass |
| `hue_cycle_stop[light_color] observed` | `light` (light_color) | not observed |
| `saturation_down_stop[light_color]` | `light` (light_color) | pass |
| `saturation_down_stop[light_color] observed` | `light` (light_color) | not observed |

Tests marked `not observed` had nobody watching.
