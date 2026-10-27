# Hue · set_attributes

| | |
|---|---|
| Result | pass |
| Date | 2026-10-27 |
| Source | rig run (`scripts/rig.py`), commit `385b8bd` |
| Fingerprint | `792fa07342e02ba1` (`integrations/hue/set_attributes.py`) |
| Home Assistant | 2026.10.2 |
| Device | Hue ambiance lamp (`LTA009`), firmware `1.163.1`; Zone, firmware `unknown` |
| Capabilities | every capability the adapter addresses |
| Fields | `brightness`, `color_temp_kelvin`, `max_brightness`, `min_brightness` |

## Tests

| Test | Target | Result |
|---|---|---|
| `sets_while_off[light_ct]` | `light` (light_ct) | pass |
| `sets_while_off[group]` | `light` (group) | pass |
| `sets_color_while_off[light_color]` | light_color: none in inventory | skipped |
| `sets_color_while_off[light_color] observed` | light_color: none in inventory | skipped |
| `min_brightness_raises[light_ct]` | `light` (light_ct) | pass |
| `min_brightness_raises[group]` | `light` (group) | pass |
| `min_brightness_leaves_brighter[light_ct]` | `light` (light_ct) | pass |
| `min_brightness_leaves_brighter[group]` | `light` (group) | pass |
| `max_brightness_lowers[light_ct]` | `light` (light_ct) | pass |
| `max_brightness_lowers[group]` | `light` (group) | pass |
