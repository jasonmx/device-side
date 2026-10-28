# Slice 13g: ZHA `set_attributes`

## Context

Slice 13 (`docs/plans/2026-10-27-zigbee-parity-timer-state.md`) brings Hue's actions to Zigbee before v0.1.0.
`set_attributes` writes brightness, color temperature or color without changing whether the light is on, so a
light that is off comes on at the new setting with no flash of the old one. On Zigbee that is a `MoveTo…`
command carrying the ZCL `ExecuteIfOff` options override (`options_mask: 1, options_override: 1`). Probe 13a
showed all three probed bulbs, the ZHA LTA004 among them, store the value while off and come on at it.

13g is built before 13f: 13f waits on 13i (`Transition` into `core/`), and 13g needs neither. ZHA's code freeze
moves to whichever of 13f/13g lands last.

Decided in the 2026-10-28 interview:
- **No read-back: a unicast that returns is `sent`, as on Hue.** zha raises on a delivery failure or a
  non-success ZCL status. A bulb that ignores the override isn't caught at run time. The probe and the rig catch
  it instead, and such a model is refused (step 1).
- **0.4 s transition** (`transition_time: 4`), the Hue bridge's default write fade, so a hue_dimmer call looks
  the same on both. While off it makes no difference.
- Kept from the slice plan: Hue's fields; a ZHA group expands to its members, written one at a time (9e);
  `homeassistant.update_entity` on each light after the write, since ZHA never applies color-temperature
  reports (13a finding 1); starts `experimental=True`.
- My calls: if both a color and `color_temp_kelvin` are given, color wins and CT isn't sent (two commands to
  one cluster, so the last would win anyway). Brightness 0 sends level 1, the lowest, as Hue sets its lowest.

## Steps

0. **Set up.** Worktree `wt/zha-set-attributes` off `release/v0.0.2`. Save this plan as
   `docs/plans/2026-10-28-zha-set-attributes.md` in the first commit.

1. **Probe the Sengled E11-G13** (the rig ZHA group's other bulb, never probed). From a scratchpad script, as
   in 13a: with the bulb off, send `MoveToLevel` 40 with and without the override, then read `CurrentLevel`
   and send a plain HA `light.turn_on`. The rig is pre-authorized for 2026-10-28 only; on any other day ask
   Jason first. Check the rig lock first. Also confirm the zigpy parameter names the steps below use against
   zigpy's `general.py`/`lighting.py` (zigpy isn't in `.venv`; read the version zha 2.3.1 pins on GitHub).
   - If it stores the value: no refusal rule; note it in the docs' tested behavior.
   - If it drops it: `supports()` refuses the model with `unsupported`, detail `execute_if_off_unsupported`
     (device registry model, a small frozenset in the adapter), per the slice plan's support rule.

2. **`zha/zcl.py`.** Add Level `MOVE_TO_LEVEL = 0x00`, Color `MOVE_TO_HUE_AND_SATURATION = 0x06`,
   `MOVE_TO_COLOR = 0x07`, `MOVE_TO_COLOR_TEMP = 0x0A`, and a helper
   `async def command(hass, addr, cluster_id, command, params, context)` wrapping
   `zha.issue_zigbee_cluster_command` (`cluster_type: "in"`, `command_type: "server"`, `blocking=True`). Switch
   `turn_on_for._unicast` to it (a refactor: no flag change). 13f reuses it.

3. **Adapter: `integrations/zha/set_attributes.py`** `ZHASetAttributes(Adapter[SetAttributesRequest])`:
   - Scope: `AdapterScope(experimental=True, domains={"light"}, fields={brightness, color_temp_kelvin,
     hs_color, rgb_color, xy_color, min_brightness, max_brightness}, max_concurrency=2)`. Not confirmable.
   - `supports`: `super()` or `unsupported_reason` (as `turn_on_for`), plus step 1's refusal if any.
   - What a light can take comes from its state's `supported_color_modes` (present while off), as in
     `get_attributes`: brightness if modes go beyond `onoff`; CT if `color_temp`; color if `xy` or `hs`.
   - A pure `_commands(request, modes, attrs, current_level) -> (list[(cluster, command, params)], dropped)`:
     - **Brightness:** `level = max(1, round(pct * 254 / 100))`. With only `min/max_brightness`, live-read
       `CurrentLevel` (`zcl.read_attributes`, only then), clamp in percent, and send nothing when the clamped
       level equals the current one: `unchanged`, `within_limits`. An explicit `brightness` wins.
     - **CT:** kelvin → mireds (`color_temperature_kelvin_to_mired`), clamped to the state's
       `min/max_color_temp_kelvin`.
     - **Color:** `hue/colors.py:color_xy` gives xy (rgb, then hs, then xy). Move `color_xy` to
       `core/color.py` so ZHA doesn't import from `hue/`. `xy` mode: `MoveToColor` with x, y × 65535. `hs`-only
       bulb: `color_xy_to_hs`, then `MoveToHueAndSaturation` with hue × 254/360, sat × 254/100. No gamut clamp:
       the bulb clamps to its own gamut.
     - Every command carries `transition_time: 4, options_mask: 1, options_override: 1`. Never the `WithOnOff`
       variants.
   - `execute`: `self.gather` per light: send the commands one after another, then `update_entity` on the
     light (with the request's context; a failure there is logged, not raised). `Unauthorized` → `rejected`,
     `admin_required`. Results: `sent` (detail `fields_dropped` if any field was dropped); `unchanged` with
     `fields_dropped` or `within_limits` when nothing was sent. Other errors raise, so `gather` rejects that
     light and core raises `targets_failed` (9f).
   - Register in `integrations/zha/__init__.py` `ADAPTERS`.

4. **Unit tests: `tests/integrations/zha/test_set_attributes.py`**, faking `hass.services` and
   `zcl.read_attributes` as `test_turn_on_for.py` and `test_get_attributes.py` do. Assert the exact service
   calls. Cover: brightness alone (and 0 → level 1); CT clamped at both ends; rgb/hs/xy on an `xy` bulb; color on
   an `hs`-only bulb; color + CT (color only); min raises, max lowers, within limits (no command, `unchanged`);
   color on a CT bulb (`fields_dropped`), and every field dropped; `onoff`-only light; `update_entity` after
   each write; `admin_required`; a command error → `targets_failed`; `not_addressable`; a ZHA group → one write
   per member. ≥95% coverage. Extend `test_zcl.py` for `command`.

5. **Rig.** `tests/rig/steps/set_attributes.yaml` already reaches ZHA (`light_ct`, `group`, `light_color`).
   Check `sets_while_off`'s ranges hold for ZHA (40 % → level 102 → HA 102: in `100–104`; 2700 K → 370
   mireds → 2703 K: in range). Run `scripts/rig.py --action set_attributes` in the background. If the
   Sengled is refused in step 1, the group's members list (inventory, private) already names only the LTA004.
   Write `docs/bench/zha/set_attributes.md`. `sets_color_while_off` skips until the A60 is on ZHA (13k step 3),
   so `experimental` stays.

6. **Docs.**
   - `docs/integrations.md`: a ZHA `### set_attributes` section, before `get_attributes`: the override, never
     on; 0.4 s fade on a light that's on; fields and units as Hue's; color wins over CT; the bulb clamps color
     to its gamut; `update_entity` after each write; no read-back, so a bulb that ignores the override reports
     `sent`. Add the Sengled finding to ZHA's tested behavior.
   - `README.md`: the ZHA `set_attributes` cell, marked as other experimental cells are.
   - Slice plan: 13g row says built before 13f, no read-back, 0.4 s. `TODO.md`: move 13g to Done, and move
     "ZHA code freezes" onto 13f.

7. **Land it.** `.venv/bin/pytest`, `pre-commit run --all-files`, `scripts/check_release.py --coverage`;
   `/audit-code` on the diff and fix its findings; PR into `release/v0.0.2`;
   `merge-green <n> --squash --delete-branch` in the background; remove the worktree and branch, and
   fast-forward the main checkout.

## Critical files

- New: `integrations/zha/set_attributes.py`, `tests/integrations/zha/test_set_attributes.py`,
  `docs/bench/zha/set_attributes.md`
- Edited: `integrations/zha/{__init__,zcl,turn_on_for}.py`, `core/color.py`, `integrations/hue/colors.py`
  (import `color_xy` from core), `docs/integrations.md`, `README.md`, the slice 13 plan, `TODO.md`
- Reused: `zha/addressing.py:address`/`unsupported_reason`, `zha/zcl.py:read_attributes`,
  `zha/groups.py:expand_group`, `hue/set_attributes.py` (result details, field-dropping shape),
  `actions/set_attributes.py:SetAttributesRequest`

## Verification

- Unit: `.venv/bin/pytest tests/integrations tests/actions`, then `scripts/check_release.py --coverage`.
- Rig: in a passing `set_attributes` run, the LTA004 and the group's members stay off when written, then come
  on at 40 % and 2700 K in HA after a plain turn on. The min/max steps clamp a light that's on. Hue's steps
  still pass, and the color step skips for lack of a ZHA `light_color`.
