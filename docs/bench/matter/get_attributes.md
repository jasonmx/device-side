# Matter · get_attributes

| | |
|---|---|
| Result | pass |
| Date | 2026-10-28 |
| Source | rig run (`scripts/rig.py`), commit `ab91067` |
| Home Assistant | 2026.10.2 |
| Device | WiZ Smart Plug (`8979`), firmware `v1.4` |

## Tests

| Test | Target | Result |
|---|---|---|
| `reads_while_off[light_ct]` | light_ct: none in inventory | skipped |
| `reads_while_off[group]` | group: none in inventory | skipped |
| `reads_a_running_timer[switch_plug]` | `switch` (switch_plug) | pass |
| `reads_a_running_timer[light_onoff]` | light_onoff: none in inventory | skipped |
| `reads_a_running_timer[light_wrapped]` | light_wrapped: none in inventory | skipped |
| `reads_a_running_timer[light_dimmable]` | light_dimmable: none in inventory | skipped |
| `reads_no_timer_after_a_turn_off[switch_plug]` | `switch` (switch_plug) | pass |
