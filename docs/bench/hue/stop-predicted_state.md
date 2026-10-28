# Hue · stop-predicted_state

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
| `shows_the_halt[light_ct]` | `light` (light_ct) | pass |
| `shows_the_halt[group]` | `light` (group) | pass |
| `shows_the_halt_of_a_move_to_off[light_ct]` | `light` (light_ct) | pass |
| `shows_the_halt_of_a_move_to_off[group]` | `light` (group) | pass |
