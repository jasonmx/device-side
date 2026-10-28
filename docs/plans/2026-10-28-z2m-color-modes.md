# Slice 14: Zigbee2MQTT color modes fixed for HA, on by default

## Context

A full-color light on Zigbee2MQTT (one whose definition exposes both `color_xy` and `color_hs`) gets announced to
Home Assistant with only one of the two color modes. Z2M's discovery (`lib/extension/homeassistant.ts`,
`colorModes`) deliberately picks a single mode, usually `xy`. Whenever the bulb is in the other mode, Z2M's
state says so (`color_mode: "hs"`), and HA rejects any mode it wasn't announced. It drops the color and keeps
showing the old one.

**What triggers it.** Hue/saturation stops, `hue_step`, Hue gradient scenes, remote bindings, and a power cut
(the bulb comes back in hs mode). Z2M's cache then re-sends the `hs` state on every check-in, about every
5 minutes.

**How widespread.** 18 Z2M issues since 2022, including about 10–15 reporters of this full-color case, mostly in
Koenkk/zigbee2mqtt#28757. Named devices are Hue color bulbs, IKEA CWS (LED2110R3, KAJPLATS) and Hue gradient
lights.

**Upstream won't fix it.** Koenkk refused advertising both modes by default as "quite risky" (#33025), and both
open fixes (#32917, #33339) exclude this case.

**The fix.** Z2M's per-device `homeassistant` option overrides its discovery message, with user overrides
applied last and a list replacing the default (`homeassistant.ts`, the `add()` merge before
`getDiscoveryTopic`). Setting `homeassistant.light.supported_color_modes` to both color modes (plus
`color_temp` where Z2M announced it) tells HA the truth. HA then accepts every state Z2M sends, whatever the
trigger, and the bulb is never touched.

device_side should cost users zero setup effort, since that drives adoption. So the fix is applied
automatically and can be switched off.

Decided in the interview (2026-10-28):
- **On by default, with an opt-out toggle** in device_side's options.
  - Saving with it off puts back what Z2M announces by itself where device_side set the override (amended after
    probe (a): the API can't delete it). It doesn't touch overrides the user set.
  - Each change is logged at info and documented, as `hue_native_control` is today.
- **Applied at setup and whenever Z2M announces a new or changed device or group,** not lazily, so lights that
  only HA or remotes use are fixed too.
- **Which lights qualify:** any Z2M light whose definition exposes both `color_hs` and `color_xy`, whatever the
  brand. Also any Z2M group whose members all qualify. A light exposing one color model is never touched,
  which keeps out the Tuya lights that crash on mixed color modes (the reason behind Koenkk's refusal).
- **Order:** this slice lands before the Z2M A60 run, alongside 13j, so that run proves it and v0.1.0 ships it.
  It touches the Z2M package, so it counts toward the Z2M freeze.
- **13i's xy write-back is backed out** once this slice is built and rig-proved (step 8a). A user who opts out
  goes back to HA showing a stale color after a hue or saturation stop, documented as a sharp edge. The
  color `/get` after a saturation stop on an xy fade stays: it fixes Z2M's stale cached x/y, not the hs drop.

## Steps

0. **Set up.** Create worktree `wt/z2m-color-modes` off `release/v0.0.2`. Save this plan as
   `docs/plans/2026-10-28-z2m-color-modes.md` in the first commit. In the same commit, add slice 14 to the
   repo plan's delivery table (before 12) and to `TODO.md` (before the Z2M A60 run).

1. **Probe on the rig (no code yet).** Check the rig lock first; rig runs are pre-authorized only on 2026-10-28,
   so on any other day ask Jason. Unattended, on the A60 and one Z2M group. Confirm each point:
   a. **Merge behavior.** `bridge/request/device/options` with
      `{"homeassistant": {"light": {"supported_color_modes": [...]}}}` must merge into the device's existing
      `homeassistant` options and not replace them. Test with a dummy key set beforehand. Then check what
      removing works with (`null` on the key, or on `light`), and what it leaves behind.
   b. **Rediscovery.** Z2M republishes the light's discovery message after the options change, with no Z2M
      restart, and HA's entity keeps its `entity_id` and gains `hs` in `supported_color_modes`.
   c. **HA accepts hs.** After `hue_move` + `hue_move: stop`, HA's `hs_color` matches a live read, with no
      "Invalid color mode" warning in HA's log.
   d. **HA's own commands still work.** `light.turn_on` with `hs_color`, `xy_color`, `rgb_color` and
      `color_temp_kelvin` each land correctly on the A60. Check what HA sends for `hs_color` now that it can
      send hs. This one is watched, so brief Jason and gate it on his go.
   e. **Groups.** The same override on a group's options re-announces the group entity with both modes.
   f. **Triggers for re-checking.** Which retained or event topics fire when a device joins, is re-interviewed,
      or is renamed, or a group's members change (`bridge/devices`, `bridge/groups`, `bridge/event`)?

   Write the findings into the plan doc. If one contradicts a step below, take it to Jason before writing code.

   **Findings (2026-10-28, unattended script, A60 on Z2M 2.14.2; source read at that tag):**
   a. The override deep-merges: a dummy `homeassistant.ds_probe` set first survived it. **Removal can't be done
      through the options API.** `changeEntityOptions` strips nulls everywhere except under `homeassistant`
      (`NULLABLE_SETTINGS`), where a null has a meaning. `supported_color_modes: null` is kept, and the discovery
      merge deletes the key from the message, so HA would lose the light's color modes. `light: null` excludes
      the light from discovery: Z2M cleared it, and HA deleted the entity (restored with `light: {}`, same
      entity_id). `homeassistant: null` excludes the whole device. **Decided with Jason:** opting out (and
      deleting device_side) writes back the modes Z2M announces by itself, computed from the exposes as its
      discovery does (`xy`, or `hs` when a light lists `color_hs` first, plus `color_temp`). Both values are
      device_side's own; any other is the user's.
   b. Z2M republished the discovery message at once, with no restart. HA's entity kept its `entity_id` and
      showed `color_temp`, `hs`, `xy`.
   c. After `hue_move: 10` and `hue_move: stop`, Z2M published `color_mode: "hs"` (232°, 94 %) and HA took it, with
      no "Invalid color mode" entry in HA's log. A `{"color": ""}` get then made Z2M publish xy, which HA also
      took. The bulb's hs and xy disagree (13i's finding), so HA's color moves when Z2M switches between them.
   d. Watched: not yet run (needs Jason's go).
   e. On a temporary group holding only the A60: Z2M announced it with `xy`, `color_temp`; the same override on the
      group's options re-announced it with `xy`, `hs`, `color_temp` at once, and HA's group entity showed all
      three. Removing the group cleared its discovery message.
   f. From the source (`lib/extension/bridge.ts`): `bridge/devices` is republished on join, leave, interview,
      announce (a bulb back from a power cut), network address change and rename; `bridge/groups` on group
      add, remove and member changes. An options change republishes only `bridge/info`, so watching
      `devices` and `groups` doesn't re-trigger on device_side's own writes.

2. **Option.**
   - `const.py`: `CONF_Z2M_COLOR_MODES = "z2m_color_modes"` and `Z2M_COLOR_MODES_DEFAULT = True`.
   - `config_flow.py`: a second bool on the options page.
   - `strings.json` / `translations/en.json`: a label and a one-line description saying what it changes in
     Z2M's settings.

3. **`integrations/zigbee2mqtt/color_modes.py`.**
   - `qualifies(definition)`: the light expose has both `color_hs` and `color_xy` features.
   - The modes to write: `xy` and `hs`, plus `color_temp` when the expose has `color_temp`. Read them from the
     exposes, the way Z2M's discovery computes them, never hard-coded per brand.
   - `async ensure_color_modes(hass, enabled)`:
     - read the retained `bridge/devices` and `bridge/groups`;
     - for each qualifying device and each group whose members all qualify, call `bridge.py:ensure_options`
       (`kind` device or group) with a `wanted` function. When enabled, it returns the override unless the
       user's own `homeassistant.light.supported_color_modes` is already set; device_side never overwrites
       theirs. When disabled, it writes Z2M's own modes back only where the value equals exactly what
       device_side writes (probe (a)).
     - Log each change at info. Never raise: a failure logs a warning and leaves that light as it was.
   - `async_watch(hass, entry)`: subscribe to the topics probe (f) names, and re-run `ensure_color_modes` for
     what changed, debounced. Return the unsubscribe for `entry.async_on_unload`.

4. **Wiring.**
   - `__init__.py:async_setup_entry`: when MQTT is set up and Z2M answers, run `ensure_color_modes` in a
     background task (never blocking setup), then start `async_watch` if the option is on.
   - Saving the options reloads the entry, so turning the option off puts Z2M's modes back on the next setup.
     Never do that on unload, which also runs at HA shutdown.
   - Add `async_remove_entry`, so deleting device_side puts Z2M's modes back.
   - With no Z2M (no `bridge/info` within the timeout), do nothing, quietly.

5. **Unit tests** (`tests/integrations/zigbee2mqtt/test_color_modes.py`, using the existing MQTT mocks and
   bridge fixtures):
   - `qualifies` for both models, one model, and no color;
   - the modes written with and without `color_temp`;
   - a user's own override left untouched;
   - Z2M's modes written back only over device_side's exact value;
   - a group with all members qualifying, and one with a mixed member;
   - a new device announced, then fixed;
   - no Z2M present, and a Z2M error reply, each logged and never raised;
   - setup isn't blocked;
   - the options flow default and the write-back on reload;
   - `async_remove_entry`.

   New modules need ≥95% coverage.

6. **Docs.**
   - `docs/integrations.md`, Z2M section: "What device_side changes in Zigbee2MQTT". Cover:
     - `hue_native_control`, `filtered_cache` and this override, each with why;
     - how to opt out;
     - the cause, citing Koenkk/zigbee2mqtt#28757 and #33025.
   - The 13i sharp edge: the xy write-back now only acts when this option is off or failed.
   - README: one line under features ("Fixes Home Assistant showing the wrong color for full-color bulbs on
     Zigbee2MQTT").
   - `TODO.md`: tick slice 14 in the PR.

7. **Rig steps.** A new `tests/rig/steps/z2m_color_modes.yaml` (or a case in an existing Z2M file, whichever the
   engine's per-action layout requires):
   - on `light_color` (Z2M): `supported_color_modes` includes `hs`;
   - after `hue_move` + stop, HA's `hs_color` is within tolerance of `get_attributes`;
   - on `group`: `hs` is in its modes when every member qualifies.

   The opt-out round trip runs as an options-flow case, if the engine's option handling allows it.

8a. **Back out 13i's xy write-back**, in this PR, once the step 7 cases pass on the rig.
   - Remove the hs branch of `xy_writeback.py` (the live x/y read and the xy write) and its unit tests. Keep the
     skip-branch color `/get` after a saturation stop on an xy fade, renaming the module to fit what's left.
   - Update `move.py` / `stop.py` call sites and the plan doc `docs/plans/2026-10-28-z2m-move-stop.md`.
   - In `docs/integrations.md`, replace the 13i write-back sharp edge with the opt-out consequence above.
   - Re-run `move` and `stop` on Z2M (the next step) to prove nothing regressed, with the option on.

8. **Rig run, then land it.**
   - Run the new step file (and `move` / `stop` on Z2M, which this changes indirectly) in the background, after
     checking the lock and the deployed tree. Write `docs/bench/zigbee2mqtt/color_modes.md`.
   - Run `.venv/bin/pytest` and `pre-commit run --all-files`, then `/audit-code` on the diff and fix its
     findings.
   - Open a PR into `release/v0.0.2`, run `merge-green <n> --squash --delete-branch` in the background, remove
     the worktree, and fast-forward the main checkout.

## Critical files

- **New:** `integrations/zigbee2mqtt/color_modes.py`, its tests, the rig step file, and
  `docs/bench/zigbee2mqtt/color_modes.md`.
- **Edited:** `const.py`, `config_flow.py`, `strings.json`, `translations/en.json`, `__init__.py`,
  `docs/integrations.md`, `README.md`, `TODO.md`, and the repo plan.
- **Reused:**
  - `zigbee2mqtt/bridge.py` (`ensure_options`, `group_members`, `first_payload`, `wait`);
  - `native_control.py` as the pattern for an option device_side sets and logs;
  - `read.py:_with_read_key` as the pattern for merging with the user's own entries.

## Verification

- **Unit:** `.venv/bin/pytest tests/integrations/zigbee2mqtt tests/test_config_flow.py`, then
  `scripts/check_release.py --coverage`.
- **Rig:**
  - the A60 and the group are announced with `hs`;
  - HA shows the halted color after a hue stop, with no "Invalid color mode" warning;
  - Z2M `move` / `stop` still pass;
  - turning the option off writes Z2M's modes back and the entity goes back to `xy` only.
- **By eye** (briefed, gated on Jason's go): HA's color picker still drives the A60 correctly in each mode.
