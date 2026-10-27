# Shelly · get_attributes

| | |
|---|---|
| Result | pass |
| Date | 2026-10-27 |
| Source | rig run (`scripts/rig.py`), commit `b4beb24` |
| Home Assistant | 2026.10.2 |
| Device | Shelly Multicolor Bulb Gen3 (`S3BL-C010007AEU`), firmware `20261026-122229/2.0.3-g4601943`; Shelly 1 Mini Gen3 (`S3SW-001X8EU`), firmware `20261026-122213/2.0.3-g4601943`; Shelly 1 Mini Gen4 (`S4SW-001X8EU`), firmware `20261026-122156/2.0.3-g4601943` |
| Capabilities | `RGBCCT`, `Switch` |

## Tests

| Test | Target | Result |
|---|---|---|
| `reads_while_off[light_ct]` | `light` (light_ct) | pass |
| `reads_while_off[group]` | group: none in inventory | skipped |
| `reads_rgb_while_off[light_color]` | `light` (light_color) | pass |
| `reads_a_running_timer[switch_plug]` | `switch` (switch_plug) | pass |
| `reads_a_running_timer[light_onoff]` | light_onoff: none in inventory | skipped |
| `reads_a_running_timer[light_wrapped]` | `light` (light_wrapped) | pass |
| `reads_a_running_timer[light_dimmable]` | `light` (light_dimmable) | pass |
| `reads_a_turn_off_for_timer[switch_plug]` | `switch` (switch_plug) | pass |
