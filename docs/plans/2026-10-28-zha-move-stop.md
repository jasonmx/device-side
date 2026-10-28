# Slice 13f: ZHA `move` and `stop`

## Context

Slice 13 (`docs/plans/2026-10-27-zigbee-parity-timer-state.md`) brings the Hue-only actions to Zigbee before
v0.1.0. 13f is ZHA's `move` (hold-to-dim: brightness, saturation and hue ramp on the bulb) and `stop` (the
release). It is the last ZHA code before the freeze and the ZHA A60 run (13k step 3).

13i's watched tests (`docs/plans/2026-10-28-z2m-move-stop.md`) showed that no halt of a color temperature fade on a
Hue bulb avoids a visible jump, so color temperature moves are dropped on every integration
(`docs/plans/2026-10-28-drop-color-temp-move.md`). 13f moves brightness, saturation and hue.

Facts this builds on:
- 13a (`docs/plans/2026-10-27-zigbee-probe.md`), on the LTA004 (ZHA `light_ct`):
  - Level `Stop` and `StopMoveStep` halt a `MoveTo…` fade part-way, and the halt holds.
  - The bulb reports brightness mid-fade, and ZHA applies it. Color is never applied without `update_entity`.
  - ExecuteIfOff (`options_mask: 1, options_override: 1`) stores a level while off; the E11-G13 drops it
    (`zha/zcl.py:DROPS_WHILE_OFF`).
- zha 2.3.1, the version HA pins (`zha/application/platforms/light/__init__.py`):
  - HA's ZHA lights are xy-only. `async_update` reads `current_x`/`current_y` in any non-CT color mode, so an
    hs-mode bulb still reads back as xy. No write-back like 13i's is needed, as long as the bulb keeps x/y current
    in hs mode (checked in the ZHA A60 run).
  - ZHA's transitioning flag is set only by HA-started `turn_on`/`turn_off`, so raw commands leave
    `update_entity` working. That is why the soft off below is raw, not `light.turn_off` + `transition`.

## Decisions (interview, 2026-10-28)

- **Color temperature:** out of scope everywhere.
- **Soft off on ZHA (down to 0 %):** a raw `MoveToLevelWithOnOff` to 0, which leaves the bulb at level 1. When
  the fade ends, if OnOff reads off, `MoveToLevel` back to the move's start level with ExecuteIfOff and no
  transition. The bulb stays off and comes back at its old level from any source (HA, a bound remote), as on Hue
  and Z2M. A stop or a new move cancels the restore. It's skipped on `DROPS_WHILE_OFF` models, which come on dim.
  An HA restart mid-fade loses the restore, so the bulb comes on dim (a documented sharp edge).
- **Saturation:** `MoveToColor`, an xy fade to the current hue at the end saturation, with a transition. It's
  halted by `StopMoveStep`, which in 13i looked dead smooth toward deep color and overshot slightly toward white.
- **Hue:** `EnhancedMoveHue`, only on bulbs whose `ColorCapabilities` report enhanced hue.

## 0. Probe findings (2026-10-28)

A scratchpad script on the LTA004 and the ZHA group, raw commands through `zha.issue_zigbee_cluster_command` and
`zha.issue_zigbee_group_command`, live reads through ZHA's admin attribute read.

- **(a) Stop halts a soft off.** `MoveToLevelWithOnOff` 200 → 0 over 6 s, level `Stop` at 3 s: CurrentLevel 100,
  OnOff on, held at +0.3, +3 and +8 s. HA showed 100 with no refresh (the bulb's report), and `update_entity` kept it.
- **(d) Groupcast.** `MoveToLevelWithOnOff` with positional args `[level, transition_time]`, and level `Stop` with
  `[]`, both work: 254 → 30 over 6 s, stopped at 3 s, the member read 144 (142 expected) and held at +4 s. Run on the
  LTA004 alone; the E11-G13 had stopped answering (last seen two hours before), so two members halting together is
  untested.
- **(e) End timing.** A 4 s `MoveToLevel` read its end level at t+3.9 s; a 4 s soft off read OnOff off, level 1, at
  t+4.3 s. An `update_entity` at fade + 0.5 s already showed the end. So the end refresh and the restore run at
  fade + 1 s (`END_REFRESH_S`).
- **(b) Restore after a soft off** and **(c) a move up from off starts at the bottom**: watched; results below.

## Rig finding and decision (2026-10-28)

The first rig run showed the core cache going stale on ZHA: a brightness change from HA during a move, or within
2 s of its end, left the next move starting from the prediction. A soft off then restored the predicted level (the
bulb came back at 94 % rather than 60 %). Hue's report filter ends a prediction on a change made elsewhere; ZHA has
no such hook, as the bulb's own reports mid-fade look the same. Decided with Jason: hold-to-dim latency comes first,
so a move is sent first and each light's CurrentLevel read after; the ramp's real start is fitted to the read at the
point the ramp had reached (timed at the middle of the read's round trip), and re-recorded. A move the prediction
says has nothing to do is planned again from HA's state. A live read before every move (about 0.2 s) was rejected
for its latency.

## 1. `zha/zcl.py` helpers

Add the constants: `MOVE_TO_LEVEL_WITH_ON_OFF = 0x04`, `STOP = 0x03`, `ENHANCED_MOVE_HUE = 0x41`,
`STOP_MOVE_STEP = 0x47`, `COLOR_CAPABILITIES = 0x400A` (`ENHANCED_HUE` bit 1). Add one
`group_command(hass, gid, cluster_id, command_id, args, context)` helper. Move the groupcast call out of
`turn_on_for.py:_groupcast` into it, as a refactor. Move `_EXECUTE_IF_OFF`/`_DROPS_WHILE_OFF` from
`set_attributes.py` to `zcl.py`, parameterizing the transition.

## 2. `zha/move.py`: `ZHAMove(Adapter[MoveRequest])`

- Scope: `experimental=True`, `domains={"light"}`, `fields={"brightness", "brightness_limit", "saturation",
  "saturation_limit", "hue"}`, `max_concurrency=2`. `supports` refuses `not_addressable` (`addressing.py`).
- Cache: `transition.transition_cache(hass, "zha", lambda: TransitionCache(SETTLE_SECONDS))`, keyed by
  entity_id. The settle window is short, about 2 s, since a refresh is right.
- Mirror `zigbee2mqtt/move.py`'s structure and rules (`plan`, `Fade`, `lit`, `at_limit`/`off`/`fields_dropped`,
  the group mean start, recording before each send), so each detail means the same on both integrations.
- **Brightness:**
  - Up sends `MoveToLevelWithOnOff(limit, t)`. Before it, each member that is off gets `MoveToLevel(1)` with
    ExecuteIfOff and t 0, unicast, so the move starts at the bottom. This is skipped on `DROPS_WHILE_OFF`, which
    is documented.
  - Down to a limit is `MoveToLevel(limit, t)`, on lit lights only.
  - Down to 0 is `MoveToLevelWithOnOff(0, t)`, then a scheduled restore per light at `t + 1 s`: read OnOff, and if
    it's off, `MoveToLevel(start level)` with ExecuteIfOff and t 0. Skipped on `DROPS_WHILE_OFF`.
  - Down on a light that's off is `unchanged`, `off`.
- **Saturation:** lit lights in a color mode. The start is `cache.value(entity, SATURATION, hs_color[1])`, and
  the end xy is `color_hs_to_xy(current hue, limit)`, sent as `MoveToColor` with t. Dropped on lights whose
  `supported_color_modes` lack xy/hs.
- **Hue:** `EnhancedMoveHue`, mode up or down, rate `round(65535 / sweep_time)`, clamped to 1–65535 steps a
  second, so a cycle is 1–65535 s. A clamped value gives `clamped_to`, per `docs/action-behavior.md`. Offered only
  where `ColorCapabilities` has enhanced hue: read from zigpy's attribute cache (it never changes), falling back
  to one live read. Otherwise the field is dropped. Record running hue moves in a `zha_hue_moves` set, as on Z2M.
- **Groups:** members expanded from one ZHA group (`turn_on_for.py:_via_zha_group`) get one groupcast per fade.
  The pre-set and the restore stay unicast, since each concerns one member's own state. Other targets are unicast.
- **End refresh:** `update_entity` per light at `t + END_REFRESH_S`, through `get_runtime(hass).schedule` keyed per
  target, so a new move or a stop replaces it. The restore rides the same job. Hue moves get none (they run until
  a stop).
- `Unauthorized` gives `REJECTED`, `admin_required`, as in the other ZHA adapters.

## 3. `zha/stop.py`: `ZHAStop(Adapter[Request])`

- Scope: `experimental=True`, `domains={"light"}`, `max_concurrency=2`.
- Lit targets, and those the cache shows fading to off, get level `Stop`. `StopMoveStep` goes where the cache
  tracks saturation or `zha_hue_moves` holds the light, and is skipped on lights with no color cluster.
  Groupcast per ZHA group, as in move.
- Record halts (`cache.stopped`). Replace the target's scheduled job, which cancels the restore: a halted soft off
  leaves the light on at the halted level, as on Hue. Then `update_entity` each light at once (raw commands leave
  ZHA's transitioning flag down).
- A light that is off with nothing fading is `unchanged`, `off`. Otherwise `SENT`.

## 4. Register both in `integrations/zha/__init__.py` `ADAPTERS`.

## 5. Unit tests

`tests/integrations/zha/test_move.py` and `test_stop.py`, with the existing ZHA service mocks and a frozen clock.
≥95% coverage.
- Each command and its params: up from on, up from off (pre-set, not on the E11-G13), down to a limit, down to 0.
- The restore: sent when OnOff reads off, skipped when on, cancelled by a stop or a new move, skipped on the
  E11-G13.
- Saturation xy end point, and the hue rate clamp edges (a test named after the rule).
- `fields_dropped` without enhanced hue or color, `at_limit`, `off`.
- One groupcast for a ZHA group's members, with per-member starts, and the unicast pre-set for off members only.
- The stop's commands per tracked attribute, the immediate refresh, and `admin_required`.
- The refactored `turn_on_for` groupcast still passes its tests.

## 6. Docs

- `docs/integrations.md`, ZHA section, a `move`/`stop` subsection: commands, the soft off restore, the
  `EnhancedMoveHue` cycle bounds; sharp edges (E11-G13: a move up from off starts at its stored level, a soft off
  leaves it at level 1; an HA restart mid-fade loses the restore); groups.
- README feature table: the ZHA move/stop cells. `TODO.md`: tick 13f, and say "ZHA code freezes".

## 7. Rig steps

- Add ZHA to the shared brightness cases in `move.yaml`/`stop.yaml` on `light_ct` and `group`: `raise`,
  `lower_to_off`, `raise_from_off`, `raise_after_soft_off`, `lower_to_a_limit`, `raise_stop_raise`,
  `halts_a_move`, `halts_a_move_to_off`, `stop_when_idle`.
- New `only: [zha]` case `soft_off_keeps_level`: fade to off, then a plain `light.turn_on` comes on at the start
  level.
- Widen 13i's `light_color` cases (`saturation_down_stop`, `hue_cycle_stop`, `saturation_to_a_limit`) to include
  ZHA. They run in the ZHA A60 run, with an added check that after a hue stop HA's `xy_color` matches a live read.
  If that fails, add an xy write-back as on Z2M.
- Brief the by-eye checks as `observe` blocks.

## 8. Rig run, then land it

`scripts/rig.py --action move --action stop` in the background. The color cases skip until the A60 is on ZHA.
Write `docs/bench/zha/move.md` and `stop.md` for the non-color scope. Then pytest, pre-commit, `/audit-code`, a PR,
and `merge-green`.

## Verification

- Unit: `.venv/bin/pytest tests/integrations/zha`, then `scripts/check_release.py --coverage`. `--release` lists the
  ZHA move/stop adapters as experimental.
- Rig: move and stop pass on ZHA `light_ct` and `group` with no Hue or Z2M regressions. `soft_off_keeps_level`
  passes.
- By eye (briefed, gated): the stop holds with no jump, a move up from off starts at the bottom, and a soft off
  comes back on at the old level.
- The color scope is proved later, in the ZHA A60 run (13k step 3), which clears `experimental`.
