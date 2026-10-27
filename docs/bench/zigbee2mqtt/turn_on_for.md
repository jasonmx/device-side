# Zigbee2MQTT · turn_on_for

| | |
|---|---|
| Result | pass |
| Date | 2026-10-27 |
| Source | rig run (`scripts/rig.py`), commit `c3c72f2` |
| Fingerprint | `2a32db41f3856c10` (`integrations/zigbee2mqtt/turn_on_for.py`) |
| Home Assistant | 2026.10.2 |
| Device | Hue white ambiance E27 800lm with Bluetooth (`8719514328242`), firmware `1.76.11`; Hue Essential White and Color Ambiance A60 (`8720169392182`), firmware `1.126.9`; Group, firmware `Zigbee2MQTT 2.14.2` |
| Capabilities | every capability the adapter addresses |
| Fields | `brightness`, `color_temp_kelvin`, `hs_color`, `rgb_color`, `xy_color` |

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
| `bulb_rgb_then_off[light_color]` | `light` (light_color) | pass |
| `bulb_rgb_then_off[light_color] observed` | `light` (light_color) | pass |
| `bulb_hs_then_off[light_color]` | `light` (light_color) | pass |
| `bulb_xy_then_off[light_color]` | `light` (light_color) | pass |
| `group_on_then_off[group]` | `light` (group) | pass |
| `group_on_then_off[group] observed` | `light` (group) | pass |
