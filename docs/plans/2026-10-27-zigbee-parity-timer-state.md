# Slice 13: Zigbee parity and timer state (before v0.1.0)

## Context

After the v0.1.0 gap review on 2026-10-27, the Hue-only actions (`move`, `stop`, `set_attributes` while off,
`get_attributes`) are being brought to ZHA and Z2M, and `get_attributes` is gaining on/off timer state. The aim
is the smoothest visual experience: the device runs its own ramp, cycle or timer, and Home Assistant never
steps it. Out of the nine items surveyed, eight go before v0.1.0. Set-scene-while-off on Zigbee (#9) is dropped
for now.

Slice 13 in the repo plan's delivery table sits after 9f and before 12 (`v0.1.0`). Implementation happens in fresh
sessions, one worktree per sub-slice (`wt/<topic>` off `release/v0.0.2`, or whichever release branch is
current then).

## Decisions (agreed in the 2026-10-27 interview)

- **v0.1.0 waits for items #1–8.** #9 (set scene while off, Z2M/ZHA) goes to the repo plan's "Not planned"
  list, to reopen when users ask.
- **Order is by integration**, so each integration's code freezes before its A60 rig run: probe, shared
  contract, Shelly, Matter, Z2M, ZHA (Matter needs no bulb and can land any time).
- **One colour bulb, 2 moves** (re-ordered 2026-10-28). The A60 starts on Z2M, so Z2M is built and frozen
  first with the bulb in place. Then it moves Z2M → Hue bridge (7c2 and the Hue colour run, while ZHA is built)
  → ZHA. Each network gets one A60 run, after its code is frozen.
- **Timer shape:** `timer: {turns: "on"|"off", ends_at: <ISO>, remaining_s: <float>}`. The key is absent when
  no timer is running.
- **get_attributes takes the `switch` domain too**, so the Shelly relays and the Matter plug report a timer.
- **Z2M timer:** reported only if Z2M's generic `read` payload can read `OnTime`. Otherwise it is left out and
  documented. We never track timers ourselves.
- **Set while off:** sent with the ZCL `ExecuteIfOff` options override. A bulb the probe shows dropping it is
  refused `unsupported`, detail `execute_if_off_unsupported`. We never write the persistent option, and the
  light never flashes on.
- **Move attributes on Zigbee:** brightness, saturation, and hue. Color temperature isn't moved on any
  integration: every halt of its fade on a Hue bulb jumps visibly (13i;
  `docs/plans/2026-10-28-drop-color-temp-move.md`). On ZHA, hue is **EnhancedMoveHue**, only on bulbs whose
  `ColorCapabilities` report enhanced hue. On Z2M, hue is the native `hue_move`, only on lights whose device
  definition lists `color_hs` (13i plan). The Hue bridge drops the `hue` field (9f rule).
- **No overlay on HA state on Zigbee; read-back where HA would be stale.** From a code read on 2026-10-27
  (zha 2.3.1, the version HA pins; Z2M `344b6e0` and zhc `c18c32d`):
  - **Z2M** publishes the target at the start of a `brightness`+`transition` write, the same model as the Hue
    bridge. Its own `…_move: stop` reads the halt back (500 ms after a brightness stop, 100 ms after a colour
    stop). Nothing to add for brightness and colour temperature. A hue or saturation stop is read back in `hs`
    mode, which HA drops for a bulb exposing only `xy` (13a, finding 2); 13i handles it.
  - **ZHA** applies no optimistic state for a raw `issue_zigbee_cluster_command`. Its transition window only
    covers moves HA itself starts, Hue bulbs don't report, and colour reports are never applied, so HA stays
    stale until ZHA's poll (3–5 min for Hue bulbs, 45–75 min for others). ZHA move, stop and
    set_attributes therefore call `homeassistant.update_entity` on each target after a stop, when a move
    reaches its limit (on a timer), and after a write while off.
  - **`get_attributes` stays a live read on both integrations** (13h's reads see mid-fade values). The `Transition`
    helper, moved from `hue/transition_cache.py` into `core/` by its own refactor PR before 13i and 13f, gives a
    move only its start. Hue's report filter stays Hue-only.
- **New adapters start with `experimental=True`.** The sweep at the end removes it, with a rig record.

## Dependencies

- **7c** (Hue `move`): 7c1 (color temp) landed in #95 and was removed when color temperature moves were dropped.
  7c2 (saturation) needs a color bulb on the bridge, so the A60 moves there first and 7c2 is built against it; Hue
  freezes after 7c2's rig run.
- **9f** (core-aligned failure behavior): lands before 13b. Every new adapter is written against the new raise
  rule, and its field-dropping rule is what drops `hue` on the Hue bridge.

## Sub-slices

Progress is tracked in [`TODO.md`](../../TODO.md).

| # | Sub-slice | Bulb on | Done when |
|---|---|---|---|
| 13a | **Zigbee probe spike** | Z2M | Findings in `docs/plans/<date>-zigbee-probe.md`, measured on the A60 and a CT bulb on Z2M plus the LTA004 on ZHA. Questions: (1) does `MoveToLevel` / `MoveToColorTemperature` / `MoveToHueAndSaturation` with the `ExecuteIfOff` override store the value while off, then light at it; (2) does Level `Stop` / `StopMoveStep` halt a `MoveTo…` with a transition, and `EnhancedMoveHue` + stop; (3) confirm the code read: the LTA004 on ZHA sends no level reports, `update_entity` fixes ZHA's state after a raw stop, and Z2M's stop read-back lands within ~0.5 s; (4) do Z2M's generic `{"command": …}` and `{"read": …}` payloads work (including reading `OnTime`); (5) `ColorCapabilities` on each bulb. Run as a script like the earlier spikes (`2026-10-26-hue-timer-spike.md`). If a finding contradicts a decision above, it goes back to the maintainer before 13e. |
| 13b | **get_attributes contract** | — | `actions/get_attributes.py` takes `light` and `switch`. The timer row shape (above) is a shared helper in `core/` (ends_at from a remaining time). `docs/action-behavior.md` and `services.yaml` updated. Hue unchanged (its scope stays `light`). |
| 13c | **Shelly get_attributes** (#1) | — | New `integrations/shelly/get_attributes.py`. On/off and timer come from `<Component>.GetStatus` (`timer_started_at`, `timer_duration`) through `shelly/rpc.py`. Bulb rows add brightness/CT/RGB from the same status. Same capability scope as `turn_on_for` (`Switch`, `RGBCCT`). Rig step for reads while a timer runs. |
| 13d | **Matter get_attributes** (#4) | — | **Done (PR #112).** New `integrations/matter/get_attributes.py`, switch (plug) scope only, matching #91. Reads OnOff and `OnTime` from the matter client's node cache. If `OnTime` isn't subscribed, the first PR checks for a live read and reports back. Rig step on the plug. |
| 13h | **Z2M get_attributes** (#3, #5) | Z2M | New `zigbee2mqtt/get_attributes.py`. Attributes come from Z2M's device state (the retained state or a `/get`). Timer only if 13a showed the generic `read` works. Groups follow `native_groups` like `turn_on_for`. |
| — | **`Transition` to core** | — | Refactor, no behavior| 13i | **Z2M move/stop** (#7) | Z2M | New `zigbee2mqtt/move.py`, `stop.py`. Brightness, colour temperature and saturation write their limit plus a `transition` (down to 0 is Z2M's soft off); hue is the native `hue_move` at a clamped rate, on lights listing `color_hs`. Stops are the native `…_move: stop`. Moves record their start in the core `Transition` cache; `get_attributes` stays a live read. Z2M's own target publish and stop read-back keep HA state right for brightness and colour temperature. **Hue/saturation stop:** when Z2M publishes an `hs` colour for a light HA lists without `hs` (Koenkk/zigbee2mqtt#28757), device_side republishes that state on the state topic as `xy`; the bulb is untouched. Read-and-write-back of xy is the fallback if the probe fails. Detail: `docs/plans/2026-10-28-z2m-move-stop.md`. |tion move still works from xy mode. If any of those fails, HA stays stale after a hue/saturation stop: `get_attributes` predicts, and `docs/integrations.md` lists it as a sharp edge. |
| 13j | **Z2M set_attributes while off** (#8) | Z2M | New `zigbee2mqtt/set_attributes.py`, via the raw `command` payload with the override (or the Hue native cluster path only if 13a shows it holds values while off and the raw path fails). **Read-back (decided after 13a):** a raw `command` publishes no state, so the write is followed by a `/get` of the written attributes. The rig step checks HA shows the stored values after a plain `light.turn_on`, with the light off in HA when written. **Z2M code freeze.** |
| 13e | **ZHA get_attributes** (#2, #3) | Hue bridge | New `integrations/zha/get_attributes.py`, `light` only (as ZHA `turn_on_for`). Brightness, CT, colour and on/off are always live-read through `zha/zcl.py:read_attributes`, never zigpy's cache, which goes stale after a raw command (13a); a live read mid-transition is the bulb's actual value, so there is no `Transition` dependency. Timer from `OnTime` while on. Brightness in percent, matching Hue. A ZHA group expands to its members (9e). Plan: `docs/plans/2026-10-28-zha-get-attributes.md`. |
| 13g | **ZHA set_attributes while off** (#8) | — | New `zha/set_attributes.py`: `MoveTo…` (not `WithOnOff`) with the `ExecuteIfOff` override, and the same fields as Hue's (`brightness`, `color_temp_kelvin`, `hs/rgb/xy_color`, `min/max_brightness`). Bulbs refused per the probe's support rule: the Sengled E11-G13 is (it jumps to full level on a `MoveToLevel` while off). A ZHA group expands to its members (9e). **Decided at build:** built before 13f, since it needs no `Transition`; no read-back, so a unicast that returns is `sent`, as on Hue; a 0.4 s transition, the Hue bridge's default. Plan: `docs/plans/2026-10-28-zha-set-attributes.md`. |
| 13f | **ZHA move/stop** (#6) | — | New `zha/move.py`, `zha/stop.py`, for brightness, saturation and hue (no color temperature). A limit is a `MoveTo…` with the transition worked out from the rate. Hue is `EnhancedMoveHue`. Stop is Level `Stop` plus `StopMoveStep`. Commands go through the same `issue_zigbee_cluster_command` path as `zha/turn_on_for.py`, and `zcl.py` gains the command helpers. Members expanded from one ZHA group get one `issue_zigbee_group_command` for move and one for stop, as `zha/turn_on_for.py` batches them by `via_group` (9e: unicast members ramp visibly apart). `update_entity` after a stop and at the limit. Moves are recorded in the core `Transition` cache (moved there by the refactor PR). **ZHA code freeze.** |
| 13k | **Sweep and A60 visits** (closes 9d's colour part) | see steps | (1) After 13j, with the A60 still on **Z2M**: the full Z2M suite (including the missing `transition` field). (2) Move the A60 **Z2M → Hue bridge**, build 7c2 against it, then rig-run the Hue colour steps (`set_attributes` colour and gamut clamp, 7c saturation) with no `light_color` skips. Hue freezes after this run. (3) After 13f: **Hue → ZHA**, then the ZHA colour suites (`turn_on_for` colour fields, `move` sat/hue, `set_attributes` colour). Each visit also drops `experimental` from the adapters it proves, in the same PR as their records. The inventory is updated privately after each move. |

The ZHA work (13e–g) is built while the A60 is on the Hue bridge, on unit tests and the ZHA bulbs for
non-colour rig steps. The A60 stays on ZHA after step (3) unless the inventory says otherwise.

## Freeze rule (to write into the plan doc)

Once an integration's A60 visit has passed, any change to that integration's package has one of two outcomes:

- the bulb goes back for a re-run, or
- the colour fields leave that adapter's scope for the release.

## Critical files

- Core: `actions/get_attributes.py`, a new timer-row helper in `core/`, `services.yaml`, `strings.json`,
  `translations/en.json`, `docs/action-behavior.md`
- Patterns to reuse:
  - `zha/zcl.py:read_attributes` and the command path in `zha/turn_on_for.py`
  - `zigbee2mqtt/addressing.py`, `detect.py` and `native_control.py`
  - `shelly/rpc.py` and `shelly/addressing.py`
  - `matter/addressing.py`
  - `hue/get_attributes.py:attributes` for the row shape and the percent brightness convention
- Rig: new step files `tests/rig/steps/get_attributes-timer.yaml`; extend `move.yaml`, `stop.yaml`,
  `set_attributes.yaml` with ZHA/Z2M roles and a `hue` step on `light_color`
- Docs: `docs/integrations.md` sections per integration; README feature table rows; the repo plan's delivery
  table and "Not planned" list (#9)

## Verification

- Every PR: `.venv/bin/pytest`, `pre-commit run --all-files`, `scripts/check_release.py --coverage`. New adapters
  are experimental, and meet the 95% coverage bar like every other adapter.
- 13a: the probe script's output tables are the evidence. No adapter is written before them.
- Each adapter: a rig run (`scripts/rig.py`, in the background, one at a time) writes a bench record. Attended
  steps are briefed and gated on the maintainer's go.
- 13k end state: `scripts/check_release.py --release` passes (no adapter experimental), each flag cleared by a PR
  citing its records, and no `light_color` skips in any record. That's the v0.1.0 entry condition this slice adds.
