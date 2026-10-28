# Zigbee2MQTT · move

| | |
|---|---|
| Result | pass |
| Date | 2026-10-28 |
| Source | rig run (`scripts/rig.py`), commit `a09aca6` |
| Home Assistant | 2026.10.2 |
| Device | Hue white ambiance E27 800lm with Bluetooth (`8719514328242`), firmware `1.76.11`; Group, firmware `Zigbee2MQTT 2.14.2`; Hue Essential White and Color Ambiance A60 (`8720169392182`), firmware `1.126.9` |

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
| `light_moved_mid_room_move[group]` | `light` (group) | skipped |
| `light_moved_mid_room_move[group] observed` | `light` (group) | skipped |
| `saturation_to_a_limit[light_color]` | `light` (light_color) | pass |
| `saturation_to_a_limit[light_color] observed` | `light` (light_color) | not observed |

Tests marked `not observed` had nobody watching.
