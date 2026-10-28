# Zigbee2MQTT · get_attributes

| | |
|---|---|
| Result | pass |
| Date | 2026-10-28 |
| Source | rig run (`scripts/rig.py`), commit `e9808be` |
| Home Assistant | 2026.10.2 |
| Device | Hue white ambiance E27 800lm with Bluetooth (`8719514328242`), firmware `1.76.11`; Group, firmware `Zigbee2MQTT 2.14.2`; Hue Essential White and Color Ambiance A60 (`8720169392182`), firmware `1.126.9` |

## Tests

| Test | Target | Result |
|---|---|---|
| `reads_while_off[light_ct]` | `light` (light_ct) | pass |
| `reads_while_off[group]` | `light` (group) | pass |
| `reads_xy_while_off[light_color]` | `light` (light_color) | pass |
| `reads_a_group_timer[group]` | `light` (group) | pass |
| `reads_a_running_timer[switch_plug]` | switch_plug: none in inventory | skipped |
| `reads_a_running_timer[light_onoff]` | light_onoff: none in inventory | skipped |
| `reads_a_running_timer[light_wrapped]` | light_wrapped: none in inventory | skipped |
| `reads_a_running_timer[light_dimmable]` | `light` (light_dimmable) | pass |
| `reads_a_turn_off_for_timer[switch_plug]` | switch_plug: none in inventory | skipped |
