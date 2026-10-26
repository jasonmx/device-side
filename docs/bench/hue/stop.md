# Hue · stop

| | |
|---|---|
| Result | pass |
| Date | 2026-10-26 |
| Source | rig run (`scripts/rig.py`), commit `b7f2228` |
| Fingerprint | `07d9e930bfc5970e` (`integrations/hue/stop.py`) |
| Home Assistant | 2026.10.2 |
| Device | Hue ambiance lamp (`LTA009`), firmware `1.163.1`; Zone, firmware `unknown` |
| Capabilities | every capability the adapter addresses |
| Fields | none |

## Tests

| Test | Target | Result |
|---|---|---|
| `halts_a_move[light_ct]` | `light` (light_ct) | pass |
| `halts_a_move[light_ct] observed` | `light` (light_ct) | pass |
| `halts_a_move[group]` | `light` (group) | pass |
| `halts_a_move[group] observed` | `light` (group) | pass |
| `halts_a_move_to_off[light_ct]` | `light` (light_ct) | pass |
| `halts_a_move_to_off[light_ct] observed` | `light` (light_ct) | pass |
| `halts_a_move_to_off[group]` | `light` (group) | pass |
| `halts_a_move_to_off[group] observed` | `light` (group) | pass |
| `stop_when_idle[light_ct]` | `light` (light_ct) | pass |
| `stop_when_idle[group]` | `light` (group) | pass |
