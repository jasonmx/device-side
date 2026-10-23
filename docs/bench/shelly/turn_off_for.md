# Shelly · turn_off_for

| | |
|---|---|
| Result | pass |
| Date | 2026-10-23 |
| Source | rig run (`scripts/rig.py`), commit `4dc28b6` |
| Fingerprint | `dcbb54c1d3fd576b` (`platforms/shelly/turn_off_for.py`) |
| Home Assistant | 2026.10.1 |
| Device | Shelly 1 Mini Gen3 (`S3SW-001X8EU`), firmware `20260923-075459/2.0.1-ge1a198b` |
| Backing | `Switch` component, `Switch.Set` with `toggle_after` |
| Classes | `switch`; on/off `light` (same `Switch.Set`) |

## Tests

| Test | Target | Result |
|---|---|---|
| `test_off_then_on_after_duration[switch_plug]` | relay as a `switch` | pass |
| `test_off_then_on_after_duration[light_wrapped]` | `switch_as_x` light over that relay | pass |
| `test_off_then_on_after_duration[light_onoff]` | none in inventory | skipped |
| `test_unclaimed_dimmer_is_refused` | none in inventory | skipped |

The `light_wrapped` pass covers the on/off `light` class: the wrapper resolves to the same relay
and gets the same call as the switch. The dimmer refusal is covered by unit tests only.
