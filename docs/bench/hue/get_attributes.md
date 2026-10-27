# Hue · get_attributes

| | |
|---|---|
| Result | pass |
| Date | 2026-10-27 |
| Source | rig run (`scripts/rig.py`), commit `b3bf589` |
| Fingerprint | `2f831d2367b79ec8` (`integrations/hue/get_attributes.py`) |
| Home Assistant | 2026.10.2 |
| Device | Hue ambiance lamp (`LTA009`), firmware `1.163.1`; Zone, firmware `unknown` |
| Capabilities | every capability the adapter addresses |
| Fields | none |

## Tests

| Test | Target | Result |
|---|---|---|
| `reads_while_off[light_ct]` | `light` (light_ct) | pass |
| `reads_while_off[group]` | `light` (group) | pass |
| `predicts_mid_move[light_ct]` | `light` (light_ct) | pass |
| `predicts_mid_move[group]` | `light` (group) | pass |
