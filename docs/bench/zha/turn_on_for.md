# ZHA · turn_on_for

| | |
|---|---|
| Result | pass |
| Date | 2026-10-25 |
| Source | rig run (`scripts/rig.py`), commit `1d12461` |
| Fingerprint | `a0fef920e49c0716` (`integrations/zha/turn_on_for.py`) |
| Home Assistant | 2026.10.2 |
| Device | LTA004, firmware `0x01001416` |
| Capabilities | every capability the adapter addresses |
| Fields | `brightness`, `color_temp_kelvin` |

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
