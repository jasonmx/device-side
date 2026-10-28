# Slice 13i: Zigbee2MQTT `move` and `stop`

## Context

Slice 13 (`docs/plans/2026-10-27-zigbee-parity-timer-state.md`) brings the Hue-only actions to Zigbee before
v0.1.0. 13i is Z2M's `move` (hold-to-dim: brightness, saturation and hue ramp on the bulb itself; color
temperature was dropped after the watched tests) and `stop` (the release: halt where it is). The A60, the rig's only color bulb, is on Z2M now. After 13i
come 13j and the Z2M A60 run, which freezes Z2M code.

Facts this builds on:
- 13a (`docs/plans/2026-10-27-zigbee-probe.md`) found the following:
  - A level `Stop` or `StopMoveStep` halts a raw `MoveTo…` fade, and a live read mid-fade returns the bulb's
    real value.
  - Z2M reads the bulb back after `brightness_move: stop` (0.65–0.71 s) and `color_temp_move: stop`
    (0.23 s).
  - After a hue or saturation stop, Z2M publishes the color as `color_mode: "hs"`, which HA drops for a light
    it lists as `xy` + `color_temp`.
- The HA drop is Z2M's bug. Its discovery (`lib/extension/homeassistant.ts`) advertises `xy` or `hs`, never
  both, then publishes the other. It's tracked upstream as Koenkk/zigbee2mqtt#28757, which is open with no fix.
  HA is right to drop it.
- How Z2M's converters behave (zigbee-herdsman-converters `toZigbee.ts`, `lib/philips.ts`):
  - With `hue_native_control` on (the rig's Hue bulbs have it), Z2M sends `brightness`, `color_temp`,
    `color` and `transition` as one Philips-cluster command. A `color` given as hue/saturation becomes xy on
    that path.
  - `*_move` keys always take the standard converters. `hue_move` and `saturation_move` are the 8-bit
    `moveHue` and `moveSaturation`, and their stop reads back `currentHue` or `currentSaturation` plus
    `colorMode`.

Decided in the interview (2026-10-28):
- **Color temperature moves are out of scope** (decided after the watched tests below, 2026-10-28). No command
  halts a color temperature fade on a Hue bulb without a visible jump, so `color_temp` and `color_temp_limit`
  are left out of the adapter's fields and refused, never dropped. The rest of this plan is edited to match.
- **Moves write an end point.** Brightness and saturation each write their limit (or range
  end) with a `transition` worked out from the predicted start, as `hue/move.py` does.
  - Down to 0 is Z2M's soft off (`state: OFF` + `transition`), which keeps the level for the next plain on.
  - Z2M publishes the end value at once, as the Hue bridge does. No overlay on HA state (slice decision).
- **Hue is a native rate move.** A hue move is `hue_move`, with rate `round(254 / sweep_time)` clamped to
  1–254 steps per second, so a full cycle takes at least about 1 s and at most 254 s.
  - It is offered only on lights whose Z2M device definition lists the `color_hs` feature.
  - This departs from the slice's EnhancedMoveHue decision for Z2M only; ZHA (13f) keeps EnhancedMoveHue.
  - What we give up: very slow cycles, and rate rounding (6% off at a 60 s cycle). Those belong to Z2M's
    `colorloop` effect anyway.
- **Superseded by slice 14** (`2026-10-28-z2m-color-modes.md`): device_side now announces full-color lights with both
  color modes, so HA takes Z2M's hs. The write-back below was backed out there; only the color get after a
  saturation stop, a saturation move's end and a group stop stays, in `color_refresh.py`.
- **HA's hs drop is fixed with an xy write-back to the bulb** (amended 2026-10-28, after probe (a)).
  - Only for a light whose HA `supported_color_modes` lack `hs`: a light announced as `hs` takes Z2M's own
    read-back, and gets nothing extra.
  - After a hue or saturation stop, and at the end of a saturation move: read the bulb's `colorMode`, `currentX`
    and `currentY` in one live `lightingColorCtrl` read (13h's `Reader`). Only if it is in hs mode (`colorMode`
    0), publish `{"color": {"x", "y"}, "transition": 0}` with the bulb's own x/y. Z2M then publishes
    `color_mode: "xy"`, which HA takes. Z2M's own hs read-back may still publish first; it is ignored.
  - Never a conversion from Z2M's hue and saturation: it misses the bulb's own xy by up to 0.05 (finding a) and
    could visibly jump.
  - Why not the republish: it leaves Z2M's cache in hs, so every later publish re-sends hs (an HA warning each
    time, and the color can come back stale after an HA restart), and it puts a message Z2M didn't send on its
    state topic. The write-back leaves the bulb, Z2M and HA all in xy.
  - **Fallback:** the state republish (probe (a), first run) if a write-back check fails; Jason is told.
  - `docs/integrations.md` cites Koenkk/zigbee2mqtt#28757 as the cause.
- **`get_attributes` stays live** (13h's reads already see mid-fade values). The slice plan's line "13h's
  get_attributes reads its prediction" is deleted.
- **The core `Transition` cache is used only for a move's start**, keyed by light entity_id and attribute, in
  percent and mirek as on Hue.
- **Depends on the `Transition` refactor PR** (moves `hue/transition_cache.py` into `core/`). That PR runs in
  its own session in parallel. 13i's probe (step 1) doesn't need it, but step 2 onward waits for it to merge.
  Z2M needs a short guard window (Z2M's stop read-back is right within ~0.7 s), so the core cache must take the
  settle time as a parameter. Hue keeps its 15 s.
- `experimental=True` on both adapters. The Z2M A60 run (13k step 1) clears it.

## Steps

0. **Set up.** Create worktree `wt/z2m-move-stop` off `release/v0.0.2`. Save this plan as
   `docs/plans/2026-10-28-z2m-move-stop.md` in the first commit, and in the same commit:
   - fix the slice plan's 13i row and its "get_attributes predicts" decision line (live reads; native
     `hue_move`; the hs republish);
   - fix the hue line under "Move attributes on Zigbee" (EnhancedMoveHue on ZHA only).

1. **Probe on the A60 and the Z2M CT bulb (no code yet).**
   - Write a scratchpad script modeled on the 13a and 13h probes, with `.env.rig` from the main checkout.
   - Check the rig lock first. Rig runs are pre-authorized only on 2026-10-28; on any other day, ask Jason.
   - It runs unattended, except point (b), which needs eyes. Brief Jason on it and gate it on his go
     (watched-session rule).

   Confirm each point:
   a. **The republish.** After `hue_move: stop` and after `saturation_move: stop`, publish Z2M's state back on
      `zigbee2mqtt/<name>` with `color_mode: "xy"` and the converted x/y. Confirm:
      - HA's `xy_color` updates and Z2M logs nothing for it;
      - Z2M's next publish (a brightness change) doesn't revert HA's color;
      - whether HA needs the whole state or takes a partial payload.
   b. **A stop against an end-point fade sent as a Philips-cluster command** (`hue_native_control` on). Check
      `brightness` + `transition` halted by `brightness_move: stop`, and `color_temp` + `transition` halted by
      `color_temp_move: stop`. Repeat with the option off.
   c. **Saturation end point.** Compare `color: {hue: <current>, saturation: X}` + `transition` (native control
      turns it into an xy fade) with the raw `moveToSaturation` command. Check that the fade holds its hue, and
      what Z2M publishes for each. Pick the one that holds hue; prefer the one HA takes directly.
   d. **Brightness and color temperature published as two messages** with different transitions: do both fades
      run, or does the second cut the first?
   e. **Group stop read-back.** Z2M reads back only the group's first member: do the other members' HA states
      update?
   f. **A move up from Z2M's soft off:** does it start at the bottom or jump to the kept level? This only
      records the behavior.

   a2. **The xy write-back** (amended after (a)), on the A60, after `hue_move: stop` and `saturation_move: stop`:
      - HA's `xy_color` updates to match a live read;
      - the bulb doesn't visibly change at the write-back (needs eyes: brief Jason, gate on his go);
      - a later `hue_move` and saturation move start smoothly from xy mode.
      If one fails, fall back to the republish and tell Jason.

   Write the findings into the plan doc. If one contradicts a step below, take it to Jason before writing the
   adapters.

   **Findings (2026-10-28, unattended script; A60 and CT bulb on Z2M, both with `hue_native_control` on; the
   A60's definition lists `color_hs`, the CT bulb's doesn't):**
   a. A full-state republish on the state topic with `color_mode: "xy"` works: HA took the color, Z2M logged
      nothing, and Z2M's next publish (hs, after a brightness change) didn't revert it, since HA drops that one too.
      A partial payload (`color_mode` and `color` only) was ignored by HA, so the republish carries the whole
      state. **The converted color is off:** HA's hs→xy of Z2M's hue and saturation missed the bulb's own xy by up
      to 0.05 (saturation stop: converted 0.584, 0.344 against a live read of 0.530, 0.395), and the x/y Z2M
      publishes alongside is further off (0.454, 0.355). The bulb's hue/saturation and its xy disagree (hue 191°
      against 203° from xy), so no conversion recovers it.
   b. `brightness_move: stop` and `color_temp_move: stop` halted a `brightness` + `transition` and a `color_temp`
      + `transition` fade part-way, with the option on and off; the value held at +1, +4 and +9 s.
   c. `color: {hue, saturation}` + `transition` kept the hue (203.6° → 200.8° from xy over the fade), Z2M published
      the end value as `xy` at once, which HA took, and `saturation_move: stop` halted it (held at +6 s). Raw
      `moveToSaturation` also kept the hue but published nothing. **Chosen: `color` + `transition`.**
   d. `brightness` + `transition` 8 s and `color_temp` + `transition` 4 s as two messages: both fades ran to their
      ends on their own timings.
   e. A group `brightness_move: stop`: Z2M published the halt for every member (one stale publish first), and each
      member's HA state matched a live read.
   f. After a soft off (level read 1 while off), `state: ON`, `brightness: 254`, `transition: 6` started at the
      bottom: 20, 62, 128, 254 at 0.5, 1.5, 3, 7 s. A move up from off starts at 0, as predicted.

   a2. (Write-back, unattended part.) After `hue_move: stop` and `saturation_move: stop` from xy, the bulb read
      `colorMode` 0; publishing its own x/y with `transition: 0` made Z2M publish `color_mode: "xy"`, and HA's
      `xy_color` matched a live read (hue 0.1658, 0.3189; saturation 0.4705, 0.3921). The bulb was left in xy mode.
      A later `hue_move` and saturation move started from where it was: 177° → 195.6° at 0.3 s, and 50 % →
      46.5 % at 0.3 s, both at the requested rate. By eye (Jason, after a `hue_move: stop` at 172°): no visible
      change at the write-back.
   c2. After `saturation_move: stop` on a `color` + `transition` fade (native control, so the bulb stays in xy,
      `colorMode` 1), with no read before HA was sampled: Z2M's read-back published `color_mode: "xy"` with the
      **fade's end point** (0.2744, 0.312), its cached x/y, and HA showed that, not the halted color. A
      `{"color": ""}` on the get topic made Z2M read the color and publish the halted x/y (0.1746, 0.2495 against
      a live read of 0.1746, 0.251), which HA took. Twice, same result. **So the write-back helper's skip branch
      (bulb not in hs mode) sends that get instead of writing.**

   **Watched tests (2026-10-28, Jason by eye, Z2M CT bulb unless noted).** Each: a 10 s fade, halted 3 s in, then
   15 s with only a read each second. The attribute held at the predicted halt every time; what he saw:

   | Fade | Halt at 3 s | By eye |
   |---|---|---|
   | `color_temp` 153 → 454 mirek, native control on | `color_temp_move: stop` (`moveColorTemp`, mode stop) | jump |
   | the same, native control off (standard ZCL fade) | `color_temp_move: stop` | jump |
   | the same, native control on | raw `stopMoveStep` | jump |
   | the same, through the **Hue bridge** (`device_side.move`, Hue `light_ct`) | `device_side.stop` | jump |
   | the same, native control on | `color_temp: 191` (where a fade linear in kelvin would be), `transition: 0` | jump, maybe smaller |
   | `brightness` + `color_temp` in one publish | `brightness_move: stop` | brightness froze; color carried on to 454, then a flash toward cold and back to warm |
   | `brightness` 20 → 254 | `brightness_move: stop` | **clean freeze** |
   | A60: `hue_move: 40` (56.7°/s), 30° → 204° | `hue_move: stop` | froze |
   | A60: `hue_move: 10` (14.2°/s), 30° → 116° | `hue_move: stop` | **super smooth** |
   | A60: `saturation_move: -30` (rate, hs mode) | `saturation_move: stop` | small jump |
   | A60: `color` + `transition` toward white (xy fade) | `saturation_move: stop` | overshoot; the xy kept drifting toward pink for 3 s |
   | A60: the same | raw `stopMoveStep` | slight overshoot; xy held from the first read |
   | A60: `color` + `transition` toward deep color (xy fade) | raw `stopMoveStep` | **dead smooth**; the other way's overshoot is acceptable |

   So a Hue bulb's color temperature output departs from its `colorTemperature` attribute during a fade, and
   every halt snaps it back, the bridge's own included. A color temperature fade that looks warmer also looks
   brighter (at a fixed level 199, 4115 K looked brighter than 6535 K). Brightness stops are clean.
   **Decided:** hue keeps `hue_move` and `hue_move: stop`; saturation keeps the `color` + `transition` xy fade
   but is halted with a raw `stopMoveStep` (Z2M's `saturation_move: stop` halts only the saturation attribute and
   lets the xy drift), followed by the `{"color": ""}` get (finding c2), since a raw command publishes nothing.

2. **Shared Z2M helpers.**
   - `bridge.py`: `has_feature(hass, ieee, name)`, read from the retained `bridge/devices` (same retained-read
     pattern as `group_members`), for the `color_hs` check.
   - `get_attributes.py:_members` moves to a shared spot (`bridge.py` or a small `members.py`) so move and stop
     can use it. get_attributes is otherwise unchanged.
   - `xy_writeback.py`: `async write_back_xy(hass, target)`, the decision above. For a group, each member is
     read and written on its own. It never raises: a failed read or write is logged, HA stays stale, and the
     stop is still `SENT`. Runs in its own task, like `turn_on_for`'s reads. When the read shows the bulb isn't
     in hs mode, it publishes `{"color": ""}` to the get topic instead of writing: Z2M's own read-back after a
     saturation stop keeps its cached x/y, which is the fade's end point (finding c2).

3. **`zigbee2mqtt/move.py`: `Z2MMove(Adapter[MoveRequest])`.**
   - Scope: `AdapterScope(experimental=True, domains={"light"}, native_groups=True, fields=…)`. The fields are
     `brightness`, `brightness_limit`, `saturation`, `saturation_limit` and `hue`, minus any the probe fails.
     Color temperature is left out (decision above), so a call using it is refused. `supports` refuses an unaddressable target (`not_addressable`), as the
     other Z2M adapters do.
   - Per target, mirror `hue/move.py`'s rules and details, so each detail means the same on both integrations:
     - **Brightness:** the start is `cache.value(entity, BRIGHTNESS, HA percent, or 0 while off)`. Limit or
       range end; `at_limit` under one step.
       - Up publishes `{"state": "ON", "brightness": <0–254>, "transition": d}`.
       - Down to a limit publishes `brightness` + `transition`. Down to 0 publishes `{"state": "OFF",
         "transition": d}`.
       - Down on an off light is `unchanged`, `off`.
     - **Saturation:** the start is HA's `hs_color[1]`, and the publish is whichever end-point form probe (c)
       chose.
     - **Hue:** `hue_move` at rate `round(254 / sweep_time)`. Per `docs/action-behavior.md` (amended
       2026-10-28): a sweep_time outside 1–254 s is clamped to that range, and the result carries `clamped_to`
       (the sweep_time used), as duration does (`core/duration.py`). It is not a refusal: `fields_dropped` is for a
       field the light lacks, not a value out of its range. Rounding inside the range isn't reported. A unit test
       named after the rule pins both ends and both in-range edges. Slower cycles, if users ask, switch this
       adapter to raw `enhancedMoveHue` with no API change.
     - **Dropped fields:** saturation and hue are dropped (`fields_dropped`) on a light without `color_hs`, as
       Hue drops what the bridge says a light can't do.
   - Record each attribute's move in the core cache (the `recording` / `moving` pattern from `hue/move.py`),
     per member light for a group. A group's start is the mean of its lit members, as on Hue. A group gets one
     publish to its group topic, so the members fade together.
   - **Hue moves:** record that one is running, so a stop knows to send `hue_move: stop`.
   - At the end of a saturation move, schedule `write_back_xy` (with the end read-back).
   - **End read-back:** schedule a `/get` of the moved attributes at the end of the move + 1 s. Use
     `get_runtime(hass).schedule`, keyed per target, so a new move or a stop replaces it. This keeps HA right
     when a live `get_attributes` read mid-fade overwrote Z2M's published end value. Hue moves get none.
   - Return `SENT`, `fields_dropped` where fields were dropped.

4. **`zigbee2mqtt/stop.py`: `Z2MStop(Adapter[Request])`.**
   - Scope: `experimental=True`, `domains={"light"}`, `native_groups=True`.
   - Send `brightness_move: stop` to every lit target, and to a target the cache shows fading to off (HA already
     shows it off).
   - Send `hue_move: stop` where a move of ours is tracking hue, and a raw `stopMoveStep` (`{"command":
     {"cluster": "lightingColorCtrl", "command": "stopMoveStep", ...}}`) where one is tracking saturation,
     followed by the `{"color": ""}` get (watched tests). No
     color temperature stop: our moves never fade it. If probe (b) or (c) shows a native stop
     doesn't halt our fades, use the raw `stopMoveStep` plus a `/get`.
   - Record each halt at its predicted value (`cache.stopped`), which covers the gap until Z2M's read-back.
     Cancel the move's scheduled end read-back. Start `write_back_xy` after a hue or saturation stop.
   - A target that is off with nothing fading is `unchanged`, `off`. Otherwise it is `SENT`.

5. **Register** both adapters in `integrations/zigbee2mqtt/__init__.py` `ADAPTERS`.

6. **Unit tests** (`tests/integrations/zigbee2mqtt/test_move.py`, `test_stop.py`, `test_xy_writeback.py`), using the
   existing Z2M MQTT mocks:
   - each payload: up, down to a limit, down to off, saturation, the hue rate clamp;
   - `at_limit`, `off`, `fields_dropped` without `color_hs`, and a refusal for `color_temp`;
   - the start taken from a prediction after a stop;
   - one group publish with per-member predictions;
   - end read-back scheduled, then replaced by a stop;
   - the stops sent per tracked attribute;
   - the write-back: a light HA lists with `hs` gets no read and no write; an xy-only light not in hs mode gets
     the read and a `{"color": ""}` get but no write; an xy-only light in hs mode gets the read and the write; a failed read or write is
     logged, never raised, and the stop is still `SENT`.

   Freeze the clock. New modules need ≥95% coverage.

7. **Docs.**
   - `docs/integrations.md`, Z2M section: a `move` and `stop` subsection covering:
     - the end-point writes and soft off;
     - native `hue_move` and its 1–254 s cycle bounds;
     - the xy write-back, as a sharp edge citing Koenkk/zigbee2mqtt#28757: one extra read and write after a
       color stop on an xy-only light, and the bulb left in xy mode;
     - group behavior.
   - README feature table: the Z2M move/stop cells.
   - `TODO.md`: tick 13i in the PR.

8. **Rig steps.**
   - In `tests/rig/steps/move.yaml` and `stop.yaml`, mark the Hue-only cases `only: [hue]`. These are the ones
     about the bridge's late reports, the soft-off cut and prediction drops (`late_stop_report`,
     `ha_change_mid_move`, `halts_a_move_to_off`'s cut comment, and others found on reading).
   - Keep the shared ones (`raise`, `lower_to_off`, `raise_stop_raise`, `halts_a_move`,
     `stop_when_idle`) for Z2M; `warmer_stop_warmer` and the combined brightness and color temperature move
     become `only: [hue]` while the Hue adapter still moves color temperature. `source: device_side` there is a live read.
   - Add `only: [zigbee2mqtt]` cases on `light_color`:
     - `saturation_down_stop` — after the stop, HA's `xy_color` matches a live read within tolerance;
     - `hue_cycle_stop` — the same;
     - `saturation_to_a_limit`.
   - Brief the visual checks for Jason as `observe` blocks.

9. **Rig run** (in the background, after checking the lock and the deployed tree).
   - Run `scripts/rig.py --action move` and `--action stop`; they run the Hue cases too.
   - Write `docs/bench/zigbee2mqtt/move.md` and `stop.md` from the run. They feed the 13k step 1 flag clearance.

10. **Land it.**
    - Run `.venv/bin/pytest` and `pre-commit run --all-files`, then `/audit-code` on the diff and fix its
      findings.
    - Open a PR into `release/v0.0.2`, then run `merge-green <n> --squash --delete-branch` in the background.
    - Remove the worktree and fast-forward the main checkout.

## Critical files

- **New:** `integrations/zigbee2mqtt/{move,stop,xy_writeback}.py`, their tests, `docs/bench/zigbee2mqtt/{move,stop}.md`.
- **Edited:**
  - `integrations/zigbee2mqtt/{__init__,bridge,get_attributes}.py`;
  - `tests/rig/steps/{move,stop}.yaml`;
  - `docs/integrations.md`, `README.md`, `TODO.md`;
  - the slice plan.
- **Reused:**
  - core `Transition` cache (after the refactor);
  - `hue/move.py` for the rules, details and group start;
  - `addressing.py` (`topic`, `state_topic`, `group_id`);
  - `bridge.py` (`group_members`, the retained-read pattern);
  - `read.py:Reader` only if a live start is needed;
  - `get_runtime(hass).schedule` as `turn_on_for.py:_schedule_reads` uses it.

## Verification

- Unit: `.venv/bin/pytest tests/integrations/zigbee2mqtt tests/core`, then `scripts/check_release.py --coverage`.
  `--release` should list both adapters as experimental.
- Rig: move and stop pass on Z2M `light_ct` and `group` with no regressions in the Hue cases. On `light_color`, HA
  shows the halted color (from the write-back) after hue and saturation stops, with no `light_color` skip.
- By eye (briefed, gated on Jason's go): a stop holds with no jump, and a move up after a soft off starts where
  the probe said.
