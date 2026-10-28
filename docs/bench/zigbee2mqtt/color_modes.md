# Zigbee2MQTT · color modes

device_side's `z2m_color_modes` option (on by default): a full-color light announced to Home Assistant with both
color modes. Not an action, so it has no suite of its own; its rig cases ride in
[`get_attributes.md`](get_attributes.md), and the rest comes from the slice 14 probe
(`docs/plans/2026-10-28-z2m-color-modes.md`, step 1).

| | |
|---|---|
| Result | pass |
| Date | 2026-10-28 |
| Source | rig run (`scripts/rig.py --integration zigbee2mqtt --action get_attributes`), commit `7711910`; probe script |
| Home Assistant | 2026.10.2 |
| Zigbee2MQTT | 2.14.2 |
| Device | Hue Essential White and Color Ambiance A60 (`8720169392182`), firmware `1.126.9`; a temporary group holding only it |

## Rig cases

| Test | Result |
|---|---|
| `announced_with_both_color_modes[light_color]`: HA's `supported_color_modes` is `color_temp`, `hs`, `xy` after device_side's setup | pass |
| `keeps_and_reads_hs_while_off[light_color]`: with Hue native control off, an `hs_color` from HA leaves HA in `color_mode: hs`, and `get_attributes` reads it back while off | pass |

## Probe

| Check | Result |
|---|---|
| The override merges into the device's other `homeassistant` options | pass |
| Z2M re-announces at once, with no restart; HA keeps the `entity_id` | pass |
| After `hue_move` and `hue_move: stop`, HA takes Z2M's `hs` state, with no "Invalid color mode" in HA's log | pass |
| The override on a group re-announces the group with both modes | pass |
| Removing the override through Z2M's options API | not possible: a null under `homeassistant` is kept, so opting out writes Z2M's own modes back |
| HA's `hs_color`, `xy_color`, `rgb_color` and `color_temp_kelvin` each land on the bulb, Hue native control on (watched by eye) | pass: blue, red, green, 2700 K, each on cue with no flicker; HA sent `color: {h, s}` for hs and RGB, `{x, y}` for xy, `color_temp` for 2700 K, and logged no color-mode warning |
