# Hue · move

| | |
|---|---|
| Result | pass |
| Date | 2026-10-27 |
| Source | rig run (`scripts/rig.py`), commit `d16a62b` |
| Fingerprint | `1520029e790936f8` (`integrations/hue/move.py`) |
| Home Assistant | 2026.10.2 |
| Device | Hue ambiance lamp (`LTA009`), firmware `1.163.1`; Zone, firmware `unknown` |
| Capabilities | every capability the adapter addresses |
| Fields | `brightness` |
| Options | `predicted_state` |

## Tests

| Test | Target | Result |
|---|---|---|
| `holds_the_start_then_shows_the_end[light_ct]` | `light` (light_ct) | pass |
| `holds_the_start_then_shows_the_end[group]` | `light` (group) | pass |
| `soft_off_stays_on_until_its_end[light_ct]` | `light` (light_ct) | pass |
| `soft_off_stays_on_until_its_end[group]` | `light` (group) | pass |
| `up_from_off_shows_the_dimmest[light_ct]` | `light` (light_ct) | pass |
| `up_from_off_shows_the_dimmest[group]` | `light` (group) | pass |
| `ha_change_mid_fade_shows_at_once[light_ct]` | `light` (light_ct) | pass |
| `ha_change_mid_fade_shows_at_once[group]` | `light` (group) | pass |
