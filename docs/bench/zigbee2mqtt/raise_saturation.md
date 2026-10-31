# Zigbee2MQTT · raise_saturation

| | |
|---|---|
| Result | pass |
| Date | 2026-10-31 |
| Source | rig run (`scripts/rig.py`), commit `37ffeaa` |
| Home Assistant | 2026.10.2 |
| Device | Hue Essential White and Color Ambiance A60 (`8720169392182`), firmware `1.126.9` |

## Tests

| Test | Target | Result |
|---|---|---|
| `saturation_to_a_limit[light_color]` | `light` (light_color) | pass |
| `saturation_to_a_limit[group_color]` | group_color: none in inventory | skipped |
