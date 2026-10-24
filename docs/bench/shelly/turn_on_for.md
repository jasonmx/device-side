# Shelly · turn_on_for

| | |
|---|---|
| Result | pass |
| Date | 2026-10-23 |
| Source | rig run (`scripts/rig.py`), commit `4dc28b6` |
| Fingerprint | `970267045fd012dc` (`platforms/shelly/turn_on_for.py`) |
| Home Assistant | 2026.10.1 |
| Device | Shelly 1 Mini Gen3 (`S3SW-001X8EU`), firmware `20260923-075459/2.0.1-ge1a198b` |
| Backings | `Switch` component, `Switch.Set` with `toggle_after` |
| Fields | none (on/off only) |

## Tests

| Test | Target | Result |
|---|---|---|
| `test_on_then_off_after_duration[switch_plug]` | relay as a `switch` | pass |
| `test_on_then_off_after_duration[light_wrapped]` | `switch_as_x` light over that relay | pass |
| `test_unclaimed_brightness_on_a_light_raises[light_wrapped]` | `switch_as_x` light over that relay | pass |
| `light_onoff` cases | none in inventory | skipped |

The `light_wrapped` pass shows the backing covers an on/off `light` too: the wrapper resolves to the same relay
and gets the same call as the switch.
