# ZHA · get_attributes

| | |
|---|---|
| Result | pass |
| Date | 2026-10-28 |
| Source | rig run (`scripts/rig.py`), commit `624b21d` |
| Home Assistant | 2026.10.2 |
| Device | LTA004, firmware `0x01001416`; ZBDongle-E, firmware `unknown` |

## Tests

| Test | Target | Result |
|---|---|---|
| `reads_while_off[light_ct]` | `light` (light_ct) | pass |
| `reads_while_off[group]` | `light` (group) | pass |
| `reads_color_while_off[light_color]` | light_color: none in inventory | skipped |
| `reads_a_running_timer[switch_plug]` | switch_plug: none in inventory | skipped |
| `reads_a_running_timer[light_onoff]` | light_onoff: none in inventory | skipped |
| `reads_a_running_timer[light_wrapped]` | light_wrapped: none in inventory | skipped |
| `reads_a_running_timer[light_dimmable]` | `light` (light_dimmable) | pass |
| `reads_a_turn_off_for_timer[switch_plug]` | switch_plug: none in inventory | skipped |
