# Shelly · turn_off_for

| | |
|---|---|
| Result | pass |
| Date | 2026-10-25 |
| Source | rig run (`scripts/rig.py`), commit `2f48523` |
| Fingerprint | `a9d2084b2c700e20` (`integrations/shelly/turn_off_for.py`) |
| Home Assistant | 2026.10.2 |
| Device | Shelly 1 Mini Gen3 (`S3SW-001X8EU`), firmware `20260923-075459/2.0.1-ge1a198b` |
| Capabilities | `Switch` |
| Fields | none |

## Tests

| Test | Target | Result |
|---|---|---|
| `off_then_on[switch_plug]` | `switch` (switch_plug) | pass |
| `off_then_on[light_onoff]` | light_onoff: none in inventory | skipped |
| `off_then_on[light_wrapped]` | `light` (light_wrapped) | pass |
| `refuses_a_dimmer_out_of_scope[light_dimmable]` | light_dimmable: none in inventory | skipped |
