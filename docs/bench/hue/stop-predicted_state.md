# Hue · stop

| | |
|---|---|
| Result | pass |
| Date | 2026-10-27 |
| Source | rig run (`scripts/rig.py`), commit `385b8bd` |
| Fingerprint | `2cd8590ca67795ed` (`integrations/hue/stop.py`) |
| Home Assistant | 2026.10.2 |
| Device | Hue ambiance lamp (`LTA009`), firmware `1.163.1`; Zone, firmware `unknown` |
| Capabilities | every capability the adapter addresses |
| Fields | none |
| Options | `predicted_state` |

## Tests

| Test | Target | Result |
|---|---|---|
| `shows_the_halt[light_ct]` | `light` (light_ct) | pass |
| `shows_the_halt[group]` | `light` (group) | pass |
| `shows_the_halt_of_a_move_to_off[light_ct]` | `light` (light_ct) | pass |
| `shows_the_halt_of_a_move_to_off[group]` | `light` (group) | pass |
