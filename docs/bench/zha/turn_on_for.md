# ZHA · turn_on_for

| | |
|---|---|
| Result | pass |
| Date | 2026-10-27 |
| Source | rig run (`scripts/rig.py`), commit `4ce60dc` |
| Home Assistant | 2026.10.2 |
| Device | LTA004, firmware `0x01001416`; ZBDongle-E, firmware `unknown` |

## Tests

| Test | Target | Result |
|---|---|---|
| `on_then_off[switch_plug]` | switch_plug: none in inventory | skipped |
| `on_then_off[light_onoff]` | light_onoff: none in inventory | skipped |
| `on_then_off[light_wrapped]` | light_wrapped: none in inventory | skipped |
| `refuses_brightness_on_a_wrapper[light_wrapped]` | light_wrapped: none in inventory | skipped |
| `bulb_on_then_off[light_dimmable]` | `light` (light_dimmable) | pass |
| `bulb_brightness_then_off[light_dimmable]` | `light` (light_dimmable) | pass |
| `bulb_color_temp_then_off[light_ct]` | `light` (light_ct) | pass |
| `group_on_then_off[group]` | `light` (group) | pass |
| `group_on_then_off[group] observed` | `light` (group) | not observed |
| `group_brightness_then_off[group]` | `light` (group) | pass |

Tests marked `not observed` had nobody watching.
