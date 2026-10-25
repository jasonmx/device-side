# Hue · get_attributes

| | |
|---|---|
| Result | pass |
| Date | 2026-10-25 |
| Source | rig run (`scripts/rig.py`), commit `f0d49e5` |
| Fingerprint | `5f39b58de10830a2` (`integrations/hue/get_attributes.py`) |
| Home Assistant | 2026.10.2 |
| Device | Hue ambiance lamp (`LTA009`), firmware `1.163.1`; Zone, firmware `unknown` |
| Capabilities | every capability the adapter addresses |
| Fields | none |

## Tests

| Test | Target | Result |
|---|---|---|
| `reads_while_off[light_ct]` | `light` (light_ct) | pass |
| `reads_while_off[group]` | `light` (group) | pass |
