# Slice 13j: Zigbee2MQTT `set_attributes`

## Context

Slice 13 (`docs/plans/2026-10-27-zigbee-parity-timer-state.md`) brings Hue's actions to Zigbee before v0.1.0. 13j
is Z2M's `set_attributes`: write brightness, color temperature or color without changing whether the light is on, so
a light that is off comes on at the new setting with no flash of the old one. It is the last Z2M slice. Z2M code
freezes after it, and then the Z2M A60 run (13k step 1) clears `experimental`.

Facts this builds on:
- 13a (`docs/plans/2026-10-27-zigbee-probe.md`): a `MoveTo…` with `optionsMask: 1, optionsOverride: 1` is stored
  while off on the A60 and the Z2M CT bulb, and without the override it is dropped. Z2M's generic `command`
  payload works with herdsman's parameter names. Success is silent and a failure is logged on `bridge/logging`.
- 13a finding 3: Z2M publishes no state after a raw `command`, so HA keeps the old values. A `/get` while off fixed
  that on the CT bulb, but the probe's own off was raw, so HA thought the bulb was on. With HA showing it off, this
  is untested.
- `read.py`'s `Reader` reads live through Z2M's generic `read`, and Z2M updates its state from the reply as it
  would from a report. A failed read raises.
- Z2M groupcast is rig-proved on `turn_on_for` (#59/#62), `move`, `stop` and `get_attributes`, with every group
  case passing in their bench records.
- ZHA's `set_attributes` (13g, #120) already turns fields into `MoveTo…` commands.

Decided in the 2026-10-28 interview:
- **Live read-back, `confirmed`.** After the write, `Reader.read_cluster` reads each written cluster from the
  bulb. Z2M's state, and so HA's, takes the stored values from the reply. A light whose level or color temperature
  doesn't come back as written is `rejected` with detail `not_stored`, which catches a bulb that ignores the
  override at run time. Color isn't compared, because the bulb clamps it to its gamut (the read still refreshes
  HA). The adapter is `confirmable=True`.
- **Groups are a groupcast** (`native_groups=True`, as the other Z2M adapters): one raw command per field to the
  group topic, then each member (`members.py:member_lights`) is read back. The group's result is `confirmed` only
  if every member is. The exception is `min/max_brightness` alone: each member clamps from its own level, so each
  member gets its own unicast, as Hue writes a room light by light.
- **The pure field-to-command logic moves to `core/`**, shared with ZHA. Each adapter maps the neutral commands to
  its own wire names (zigpy's vs herdsman's). For ZHA this is a refactor, so its flag doesn't change.
- Kept from 13g: Hue's fields (no `transition`), a 0.4 s transition, never the `WithOnOff` variants, color wins
  over CT, brightness 0 sends level 1, and new adapters start `experimental=True`.

## Steps

0. **Set up.** Create worktree `wt/z2m-set-attributes` off `release/v0.0.2`. Save this plan as
   `docs/plans/2026-10-28-z2m-set-attributes.md` in the first commit. In the same commit, update the slice plan's
   13j row: live read-back, `confirmed`, groupcast, and drop the "Hue native cluster path" alternative.

1. **Probe on the A60, the CT bulb and the rig's Z2M group** (scratchpad script modeled on 13a's, with `.env.rig`
   from the main checkout; unattended). Check the rig lock first. Rig runs are pre-authorized on 2026-10-28 only;
   on any other day, ask Jason. First confirm herdsman's parameter names (`level`, `colortemp`, `colorx`/`colory`,
   `hue`/`saturation`, `transtime`, `optionsMask`, `optionsOverride`) against its ZCL cluster definitions on
   GitHub. Then:
   a. **HA off.** Turn the light off through HA, write level 102 and 370 mireds raw with the override, then
      `read` both clusters. Does Z2M publish the values, and does HA show them after a plain HA `light.turn_on`?
   b. **After a soft off.** Repeat (a) after an off with a transition (Z2M keeps the old level and restores it on
      the next plain on, as `read.py` notes), with `hue_native_control` on and then off. Does the plain on come on
      at the stored level or at Z2M's kept one?
   c. **Groupcast.** Send a raw `command` with the override to the group topic while every member is off. Does
      every member store it, read member by member?
   d. **Read-back values.** Check that level and mireds read back exactly as written, both while off and while on.
      While on, the read has to come after the 0.4 s fade. Measure the delay that works, and also read back an
      out-of-gamut red (rgb 255,0,0) on the A60.
   Write the findings into the plan doc. If (a) or (b) fails, take it to Jason before writing the adapter: a fix
   for (b) would change what a plain on does.

2. **Refactor: `core/zcl_write.py`** (its own commit, no behavior change). Move `_level`, `_brightness`,
   `_mireds`, `_color`, `wants_level` and `commands` out of `integrations/zha/set_attributes.py`. They return
   neutral frozen dataclasses, `MoveToLevel(level)`, `MoveToColorTemp(mireds)`, `MoveToColor(x, y)` (0–1) and
   `MoveToHueAndSaturation(hue, saturation)` (ZCL units), plus the `dropped` flag. ZHA maps them to
   `(cluster, command, params)` with its `_EXECUTE_IF_OFF`. Move the pure-logic tests from
   `tests/integrations/zha/test_set_attributes.py` to `tests/core/test_zcl_write.py`, and keep the ZHA tests that
   assert the service calls.

3. **Adapter: `integrations/zigbee2mqtt/set_attributes.py`**, `Z2MSetAttributes(Adapter[SetAttributesRequest])`:
   - Scope: `AdapterScope(experimental=True, domains={"light"}, fields=<ZHA's set>, confirmable=True,
     native_groups=True)`.
   - `supports`: `super()`, then `not_addressable` as `get_attributes` does.
   - `_wire(command) -> dict`: the Z2M payload
     `{"command": {"cluster": "genLevelCtrl"|"lightingColorCtrl", "command": "moveToLevel"|…, "payload": {…,
     "transtime": 4, "optionsMask": 1, "optionsOverride": 1}}}`, with xy × 65535.
   - Current level for `min/max_brightness`: while on, read live. While off, take Z2M's brightness, the level the
     light comes back at. Factor this out of `Reader.read` into a `Reader.level(target)` that both use.
   - `execute` per target, inside `async with reader(hass, lights)`:
     - Group with `min/max` only: per member, read its level, clamp, publish to the member's topic.
     - Otherwise: build the commands from the target's own state (`supported_color_modes`, kelvin range) and
       publish each one to the target's topic.
     - Nothing to send: `unchanged`, with `within_limits` or `fields_dropped`.
     - Wait out the fade (step 1d's delay), then `read_cluster` each written cluster on each light. Compare level
       and mireds. On a mismatch the light is `rejected` with `not_stored`; otherwise it is `confirmed`, with
       detail `fields_dropped` if a field was dropped.
     - A read that fails raises, so core raises `targets_failed` (9f).
   - Register it in `integrations/zigbee2mqtt/__init__.py` `ADAPTERS`.

4. **Unit tests: `tests/integrations/zigbee2mqtt/test_set_attributes.py`**, faking MQTT and the Reader as
   `test_get_attributes.py` and `test_stop.py` do. Assert the exact payloads. Cover:
   - brightness alone, and 0 → level 1;
   - CT clamped;
   - rgb/hs/xy on an xy light, and color on an hs-only light;
   - color + CT (color only);
   - min raises, max lowers, within limits (no publish);
   - a group with min/max (one unicast per member) and a group with brightness (one groupcast, every member
     read);
   - a dropped field, and every field dropped;
   - an `onoff`-only light;
   - a mismatched read → `not_stored`;
   - a read that times out → `targets_failed`;
   - `not_addressable`, and an empty group.
   Line coverage must be ≥95%.

5. **Rig.** `tests/rig/steps/set_attributes.yaml` already reaches Z2M through `light_ct`, `group` and
   `light_color` (the A60 is on Z2M). Check that the ranges hold for Z2M: 40 % → level 102 → HA 102, and 2700 K →
   370 mireds. Run `scripts/rig.py --action set_attributes` in the background, unattended. The observed
   `sets_color_while_off` case goes to the Z2M A60 run. Write `docs/bench/zigbee2mqtt/set_attributes.md`.
   `experimental` stays until 13k step 1.

6. **Docs.**
   - `docs/integrations.md`:
     - Add a Z2M `### set_attributes` section before `get_attributes`. It covers: the raw command and the
       override; never on; the 0.4 s fade; fields as ZHA's; the groupcast and the per-member min/max; the live
       read-back, `confirmed` and `not_stored`; color not verified.
     - In "What Device Side changes", add `set_attributes` to `filtered_cache`'s line.
     - Add step 1's findings to sharp edges where they bite (e.g. a soft off's kept level).
   - `README.md`: add the Z2M `set_attributes` cell, marked as other experimental cells are.
   - `TODO.md`: tick 13j and mark the Z2M code freeze.

7. **Land it.** Run `.venv/bin/pytest`, `pre-commit run --all-files` and `scripts/check_release.py --coverage`.
   Run `/audit-code` on the diff and fix its findings. Open a PR into `release/v0.0.2`, then run
   `merge-green <n> --squash --delete-branch` in the background. Afterwards, remove the worktree and branch and
   fast-forward the main checkout.

## Critical files

- **New:** `core/zcl_write.py`, `integrations/zigbee2mqtt/set_attributes.py`, their tests,
  `docs/bench/zigbee2mqtt/set_attributes.md`.
- **Edited:** `integrations/zha/set_attributes.py` (uses core), `integrations/zigbee2mqtt/{__init__,read}.py`,
  `tests/integrations/zha/test_set_attributes.py`, `docs/integrations.md`, `README.md`, the slice 13 plan,
  `TODO.md`.
- **Reused:**
  - `zigbee2mqtt/read.py:reader`/`Reader.read_cluster`
  - `zigbee2mqtt/members.py:member_lights`
  - `zigbee2mqtt/bridge.py:publish`
  - `zigbee2mqtt/addressing.py:topic`/`state_topic`
  - `core/color.py:color_xy`
  - `actions/set_attributes.py:SetAttributesRequest`

## Verification

- Unit: `.venv/bin/pytest tests/core tests/integrations tests/actions`, then `scripts/check_release.py --coverage`.
  ZHA's tests still pass unchanged in what they assert.
- Rig: in a passing `set_attributes` run, the CT bulb, the group's members and the A60 stay off when written and
  come on at 40 % / 2700 K (red on the A60) in HA after a plain turn on. The min/max steps clamp lights that are
  on, and the response is `confirmed`.

## Step 1 findings (probe, 2026-10-29)

Unattended, from a scratchpad script: raw `command` payloads with the override, then Z2M's generic `read` with a
`state_property`, and HA's state. Both Z2M bulbs had `hue_native_control` on unless stated.

Herdsman's parameter names are as assumed: `level`, `colortemp`, `colorx`/`colory`, `hue`/`saturation`,
`transtime`, `optionsMask`, `optionsOverride` (`src/zspec/zcl/definition/cluster.ts`).

- **(a) HA off: passes on both bulbs.** With the light turned off through HA, a raw write of level 102 and 370 mireds
  leaves it off, and HA shows nothing new. The live read returns 102 and 370, and Z2M's published state takes them
  (`brightness: 102`, `color_temp: 370`) while HA still shows the light off. A plain HA `light.turn_on` then comes on
  showing 102 and 370, and the bulb reads 102 and 370.
- **(b) After a soft off: fails for brightness, on both `hue_native_control` settings.** After an HA off with a 2 s
  transition, the write and the read go as in (a), and Z2M publishes `brightness: 102`. The plain on comes on at
  254, the level from before the off, and the bulb reads 253; the color temperature is the stored 370. Cause:
  Z2M's `light_onoff_brightness` converter keeps the pre-off brightness and a `turnedOffWithTransition` flag in its
  `globalStore` on an off with a transition, and an on without a brightness restores that level with
  `moveToLevelWithOnOff`. A raw command and a read update Z2M's published state, not that store; only an on or a
  brightness through the converter does, and both turn the light on.
- **(c) Groupcast: not run.** Both members of the rig's Z2M group were `unavailable` in HA for the whole probe.
- **(d) Read-back values.** While on, the level and mireds read back exactly as written at every delay tried, from
  0.2 s after the write (inside the 0.4 s fade) to 1.5 s: a Hue bulb on Z2M answers a read with the target, not the
  mid-fade value, like the Hue bridge. So no fade wait is needed for the comparison. While off, they read back
  exactly too. Red (xy 45914/19615) on the A60 reads back as 45317/20204, clamped to the gamut, on and off, so
  color can't be compared.
