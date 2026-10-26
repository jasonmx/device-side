# Hue · move

| | |
|---|---|
| Result | pass |
| Date | 2026-10-26 |
| Source | rig run (`scripts/rig.py`), commit `b7f2228` |
| Fingerprint | `4e3cd6516a94e753` (`integrations/hue/move.py`) |
| Home Assistant | 2026.10.2 |
| Device | Hue ambiance lamp (`LTA009`), firmware `1.163.1`; Zone, firmware `unknown` |
| Capabilities | every capability the adapter addresses |
| Fields | `brightness`, `brightness_limit` |

## Tests

| Test | Target | Result |
|---|---|---|
| `raise[light_ct]` | `light` (light_ct) | pass |
| `raise[light_ct] observed` | `light` (light_ct) | pass |
| `raise[group]` | `light` (group) | pass |
| `raise[group] observed` | `light` (group) | pass |
| `lower_to_off[light_ct]` | `light` (light_ct) | pass |
| `lower_to_off[light_ct] observed` | `light` (light_ct) | pass |
| `lower_to_off[group]` | `light` (group) | pass |
| `lower_to_off[group] observed` | `light` (group) | pass |
| `raise_from_off[light_ct]` | `light` (light_ct) | pass |
| `raise_from_off[light_ct] observed` | `light` (light_ct) | pass |
| `raise_from_off[group]` | `light` (group) | pass |
| `raise_from_off[group] observed` | `light` (group) | pass |
| `raise_after_soft_off[light_ct] observed` | `light` (light_ct) | pass |
| `raise_after_soft_off[group] observed` | `light` (group) | pass |
| `lower_to_a_limit[light_ct]` | `light` (light_ct) | pass |
| `lower_to_a_limit[group]` | `light` (group) | pass |
| `raise_stop_raise[light_ct]` | `light` (light_ct) | pass |
| `raise_stop_raise[light_ct] observed` | `light` (light_ct) | pass |
| `raise_stop_raise[group]` | `light` (group) | pass |
| `raise_stop_raise[group] observed` | `light` (group) | pass |
| `lower_stop_lower[light_ct]` | `light` (light_ct) | pass |
| `lower_stop_lower[light_ct] observed` | `light` (light_ct) | pass |
| `lower_stop_lower[group]` | `light` (group) | pass |
| `lower_stop_lower[group] observed` | `light` (group) | pass |
| `light_moved_mid_room_move[group]` | `light` (group) | pass |
| `light_moved_mid_room_move[group] observed` | `light` (group) | pass |
