# Hue · move-predicted_state

| | |
|---|---|
| Result | pass |
| Date | 2026-10-28 |
| Source | rig run (`scripts/rig.py`), commit `33932a6` |
| Home Assistant | 2026.10.2 |
| Device | Hue ambiance lamp (`LTA009`), firmware `1.163.1`; Zone, firmware `unknown` |

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
| `bridge_scene_recall_mid_fade_shows_at_once[group]` | `light` (group) | pass |
| `bridge_scene_recall_mid_fade_shows_at_once[group] observed` | `light` (group) | not observed |
| `color_temp_shows_what_the_bridge_reports[light_ct]` | `light` (light_ct) | pass |
| `color_temp_shows_what_the_bridge_reports[group]` | `light` (group) | pass |

Tests marked `not observed` had nobody watching.

Its color temperature rows prove a call no longer offered: since 2026-10-28 `move` has no color temperature fields, as every halt of a Hue bulb's color temperature fade jumps visibly (`docs/plans/2026-10-28-z2m-move-stop.md`).
