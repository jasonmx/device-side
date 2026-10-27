# Shelly · turn_on_for

| | |
|---|---|
| Result | pass |
| Date | 2026-10-27 |
| Source | rig run (`scripts/rig.py`), commit `e330c4e` |
| Fingerprint | `b15176fa0812dc25` (`integrations/shelly/turn_on_for.py`) |
| Home Assistant | 2026.10.2 |
| Device | Shelly 1 Mini Gen3 (`S3SW-001X8EU`), firmware `20260923-075459/2.0.1-ge1a198b`; Shelly 1 Mini Gen4 (`S4SW-001X8EU`), firmware `20260923-075524/2.0.1-ge1a198b`; Shelly Multicolor Bulb Gen3 (`S3BL-C010007AEU`), firmware `20261026-122229/2.0.3-g4601943` |
| Capabilities | `RGBCCT`, `Switch` |
| Fields | `brightness`, `color_temp_kelvin`, `rgb_color`, `transition` |

## Tests

| Test | Target | Result |
|---|---|---|
| `on_then_off[switch_plug]` | `switch` (switch_plug) | pass |
| `on_then_off[light_onoff]` | light_onoff: none in inventory | skipped |
| `on_then_off[light_wrapped]` | `light` (light_wrapped) | pass |
| `refuses_brightness_on_a_wrapper[light_wrapped]` | `light` (light_wrapped) | pass |
| `refuses_brightness_on_a_relay_light[light_onoff]` | light_onoff: none in inventory | skipped |
| `bulb_on_then_off[light_dimmable]` | `light` (light_dimmable) | pass |
| `bulb_brightness_then_off[light_dimmable]` | `light` (light_dimmable) | pass |
| `bulb_color_temp_then_off[light_ct]` | `light` (light_ct) | pass |
| `bulb_transition_then_off[light_dimmable]` | `light` (light_dimmable) | pass |
| `rgbcct_bulb_rgb_then_off[light_color]` | `light` (light_color) | pass |
| `rgbcct_bulb_rgb_then_off[light_color] observed` | `light` (light_color) | pass |
