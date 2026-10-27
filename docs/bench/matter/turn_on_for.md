# Matter · turn_on_for

| | |
|---|---|
| Result | pass |
| Date | 2026-10-27 |
| Source | rig run (`scripts/rig.py`), commit `6ef74a3` |
| Fingerprint | `380c3288d5853e35` (`integrations/matter/turn_on_for.py`) |
| Home Assistant | 2026.10.2 |
| Device | WiZ Smart Plug (`8979`), firmware `v1.4` |
| Capabilities | every capability the adapter addresses |
| Fields | none |

## Tests

| Test | Target | Result |
|---|---|---|
| `on_then_off[switch_plug]` | `switch` (switch_plug) | pass |
| `on_then_off[light_onoff]` | light_onoff: none in inventory | skipped |
| `on_then_off[light_wrapped]` | light_wrapped: none in inventory | skipped |
| `refuses_brightness_on_a_wrapper[light_wrapped]` | light_wrapped: none in inventory | skipped |
| `bulb_on_then_off[light_dimmable]` | light_dimmable: none in inventory | skipped |
