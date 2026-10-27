# Shelly · turn_off_for

| | |
|---|---|
| Result | pass |
| Date | 2026-10-27 |
| Source | rig run (`scripts/rig.py`), commit `e330c4e` |
| Fingerprint | `6991c2aebe1adda0` (`integrations/shelly/turn_off_for.py`) |
| Home Assistant | 2026.10.2 |
| Device | Shelly 1 Mini Gen3 (`S3SW-001X8EU`), firmware `20260923-075459/2.0.1-ge1a198b`; Shelly 1 Mini Gen4 (`S4SW-001X8EU`), firmware `20260923-075524/2.0.1-ge1a198b`; Shelly Multicolor Bulb Gen3 (`S3BL-C010007AEU`), firmware `20261026-122229/2.0.3-g4601943` |
| Capabilities | `RGBCCT`, `Switch` |
| Fields | none |

## Tests

| Test | Target | Result |
|---|---|---|
| `off_then_on[switch_plug]` | `switch` (switch_plug) | pass |
| `off_then_on[light_onoff]` | light_onoff: none in inventory | skipped |
| `off_then_on[light_wrapped]` | `light` (light_wrapped) | pass |
| `bulb_off_then_on[light_dimmable]` | `light` (light_dimmable) | pass |
