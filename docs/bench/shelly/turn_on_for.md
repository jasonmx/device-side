# Shelly · turn_on_for

| | |
|---|---|
| Result | pass |
| Date | 2026-10-25 |
| Source | rig run (`scripts/rig.py`), commit `2f48523` |
| Fingerprint | `c0e28e7223fe3e2f` (`integrations/shelly/turn_on_for.py`) |
| Home Assistant | 2026.10.2 |
| Device | Shelly 1 Mini Gen3 (`S3SW-001X8EU`), firmware `20260923-075459/2.0.1-ge1a198b` |
| Capabilities | `Switch` |
| Fields | none |

## Tests

| Test | Target | Result |
|---|---|---|
| `on_then_off[switch_plug]` | `switch` (switch_plug) | pass |
| `on_then_off[light_onoff]` | light_onoff: none in inventory | skipped |
| `on_then_off[light_wrapped]` | `light` (light_wrapped) | pass |
| `refuses_brightness_on_a_wrapper[light_wrapped]` | `light` (light_wrapped) | pass |
| `refuses_brightness_out_of_scope[light_onoff]` | light_onoff: none in inventory | skipped |
