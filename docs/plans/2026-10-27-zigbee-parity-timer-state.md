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
- **Order is by integration**, so each integration's code freezes before the A60 visits it: probe, shared
  contract, Shelly, Matter, ZHA, Z2M.
- **One colour bulb, 3 moves.** The Hue A60 moves Z2M → Hue bridge → ZHA → Z2M. It visits each network once,
  after that integration's code is frozen.
- **Timer shape:** `timer: {turns: "on"|"off", ends_at: <ISO>, remaining_s: <float>}`. The key is absent when
  no timer is running.
- **get_attributes takes the `switch` domain too**, so the Shelly relays and the Matter plug report a timer.
- **Z2M timer:** reported only if Z2M's generic `read` payload can read `OnTime`. Otherwise it is left out and
  documented. We never track timers ourselves.
- **Set while off:** sent with the ZCL `ExecuteIfOff` options override. A bulb the probe shows dropping it is
  refused `unsupported`, detail `execute_if_off_unsupported`. We never write the persistent option, and the
  light never flashes on.
- **Move attributes on Zigbee:** brightness, color temp, saturation, and **hue via EnhancedMoveHue**, only on
  bulbs whose `ColorCapabilities` report enhanced hue. The Hue bridge drops the `hue` field (9f rule).
- **No overlay on HA state on Zigbee; read-back where HA would be stale.** From a code read on 2026-10-27
  (zha 2.3.1, the version HA pins; Z2M `344b6e0` and zhc `c18c32d`):
  - **Z2M** publishes the target at the start of a `brightness`+`transition` write, the same model as the Hue
    bridge. Its own `…_move: stop` reads the halt back (500 ms after a brightness stop, 100 ms after a colour
    stop). Nothing to add.
  - **ZHA** applies no optimistic state for a raw `issue_zigbee_cluster_command`. Its transition window only
    covers moves HA itself starts, Hue bulbs don't report, and colour reports are never applied, so HA stays
    stale until ZHA's poll (3–5 min for Hue bulbs, 45–75 min for others). ZHA move, stop and
    set_attributes therefore call `homeassistant.update_entity` on each target after a stop, when a move
    reaches its limit (on a timer), and after a write while off.
  - **`get_attributes` predicts mid-move on both integrations**, from a `Transition` helper moved from
    `hue/transition_cache.py` into `core/`. Hue's report filter stays Hue-only.
- **New adapters start with `experimental=True`.** The sweep at the end removes it, with a rig record.

## Dependencies

- **7c** (Hue `move` for color temp and saturation): being built in another session. It has to land before the
  Hue A60 visit.
- **9f** (core-aligned failure behavior): lands before 13b. Every new adapter is written against the new raise
  rule, and its field-dropping rule is what drops `hue` on the Hue bridge.

## Sub-slices

| # | Sub-slice | Bulb on | Done when |
|---|---|---|---|
| 13a | **Zigbee probe spike** | Z2M | Findings in `docs/plans/<date>-zigbee-probe.md`, measured on the A60 and a CT bulb on Z2M plus the LTA004 on ZHA. Questions: (1) does `MoveToLevel` / `MoveToColorTemperature` / `MoveToHueAndSaturation` with the `ExecuteIfOff` override store the value while off, then light at it; (2) does Level `Stop` / `StopMoveStep` halt a `MoveTo…` with a transition, and `EnhancedMoveHue` + stop; (3) confirm the code read: the LTA004 on ZHA sends no level reports, `update_entity` fixes ZHA's state after a raw stop, and Z2M's stop read-back lands within ~0.5 s; (4) do Z2M's generic `{"command": …}` and `{"read": …}` payloads work (including reading `OnTime`); (5) `ColorCapabilities` on each bulb. Run as a script like the earlier spikes (`2026-10-26-hue-timer-spike.md`). If a finding contradicts a decision above, it goes back to the maintainer before 13e. |
| 13b | **get_attributes contract** | — | `actions/get_attributes.py` takes `light` and `switch`. The timer row shape (above) is a shared helper in `core/` (ends_at from a remaining time). `docs/action-behavior.md` and `services.yaml` updated. Hue unchanged (its scope stays `light`). |
| 13c | **Shelly get_attributes** (#1) | — | New `integrations/shelly/get_attributes.py`. On/off and timer come from `<Component>.GetStatus` (`timer_started_at`, `timer_duration`) through `shelly/rpc.py`. Bulb rows add brightness/CT/RGB from the same status. Same capability scope as `turn_on_for` (`Switch`, `RGBCCT`). Rig step for reads while a timer runs. |
| 13d | **Matter get_attributes** (#4) | — | New `integrations/matter/get_attributes.py`, switch (plug) scope only, matching #91. Reads OnOff and `OnTime` from the matter client's node cache. If `OnTime` isn't subscribed, the first PR checks for a live read and reports back. Rig step on the plug. |
| 13e | **ZHA get_attributes** (#2, #3) | Z2M | New `integrations/zha/get_attributes.py`. Brightness, CT, colour and on/off come from the cluster attribute cache, live-read where the cache is empty. Timer from `OnTime` (and `OffWaitTime`) via `zha/zcl.py:read_attributes`. Brightness in percent, matching Hue. A ZHA group expands to its members (9e). |
| 13f | **ZHA move/stop** (#6) | Z2M | New `zha/move.py`, `zha/stop.py`. A limit is a `MoveTo…` with the transition worked out from the rate. Hue is `EnhancedMoveHue`. Stop is Level `Stop` plus `StopMoveStep`. Commands go through the same `issue_zigbee_cluster_command` path as `zha/turn_on_for.py`, and `zcl.py` gains the command helpers. Members expanded from one ZHA group get one `issue_zigbee_group_command` for move and one for stop, as `zha/turn_on_for.py` batches them by `via_group` (9e: unicast members ramp visibly apart). `update_entity` after a stop and at the limit. The first PR moves `Transition` into `core/` and records each move there, and 13e's get_attributes reads its prediction. |
| 13g | **ZHA set_attributes while off** (#8) | Z2M | New `zha/set_attributes.py`: `MoveTo…` (not `WithOnOff`) with the `ExecuteIfOff` override, and the same fields as Hue's (`brightness`, `color_temp_kelvin`, `hs/rgb/xy_color`, `min/max_brightness`). Bulbs refused per the probe's support rule. A ZHA group expands to its members (9e). **ZHA code freeze.** |
| 13h | **Z2M get_attributes** (#3, #5) | Z2M | New `zigbee2mqtt/get_attributes.py`. Attributes come from Z2M's device state (the retained state or a `/get`). Timer only if 13a showed the generic `read` works. Groups follow `native_groups` like `turn_on_for`. |
| 13i | **Z2M move/stop** (#7) | Z2M | New `zigbee2mqtt/move.py`, `stop.py`. Native `brightness_move`/`color_temp_move`/`saturation_move`/`hue_move` and `…: stop`; a limit is the target value plus `transition`. If 13a shows a gap, use the raw `command` payload. Reuse `addressing.py` and the `native_control.py` pattern for Hue bulbs. Moves are recorded in the core `Transition` cache, and 13h's get_attributes reads its prediction. Z2M's own target publish and stop read-back keep HA state right. |
| 13j | **Z2M set_attributes while off** (#8) | Z2M | New `zigbee2mqtt/set_attributes.py`, via the raw `command` payload with the override (or the Hue native cluster path only if 13a shows it holds values while off and the raw path fails). **Z2M code freeze.** |
| 13k | **Sweep and A60 visits** (closes 9d's colour part) | see steps | (1) Once 7c and 9f have landed and Hue is frozen: move the A60 **Z2M → Hue bridge**, then rig-run the Hue colour steps (`set_attributes` colour and gamut clamp, 7c saturation) with no `light_color` skips. (2) After 13g: **Hue → ZHA**, then the ZHA colour suites (`turn_on_for` colour fields, `move` sat/hue, `set_attributes` colour). (3) After 13j: **ZHA → Z2M**, then the full Z2M suite (including the missing `transition` field). Each visit also drops `experimental` from the adapters it proves, in the same PR as their records. The inventory is updated privately after each move. |

Between visits the A60 is away from Z2M from step (1) until step (3). The Z2M work (13h–j) relies on unit tests
plus the Z2M CT bulb for non-colour rig steps.

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
