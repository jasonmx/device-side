# Slice 13e: ZHA `get_attributes`

## Context

Slice 13 (`docs/plans/2026-10-27-zigbee-parity-timer-state.md`) brings `get_attributes` to every integration
before v0.1.0. 13b set the contract (light and switch domains, `core/timer.py:timer_row`), and 13c (Shelly) was the
first adapter on it. 13e adds ZHA: on/off timer, brightness, color temperature and color for ZHA lights, including
lights that are off.

Decided in the 2026-10-28 interview, changing the slice plan's 13e row:
- **Always live-read the bulb**, never zigpy's attribute cache (the last value zigpy saw per attribute). Per 13a,
  ZHA never applies color-temperature reports, so the cache goes stale after a raw command or a bound remote.
  A live read during a transition returns the bulb's actual value (13a, finding 2), so the row is right mid-move
  without a core `Transition` prediction. 13e therefore doesn't depend on 13i, and 13f no longer has to feed it.
- **`light` only**, matching ZHA `turn_on_for`. Zigbee plugs don't honor OnTime, so a switch row would always be
  `{}`.
- **Build it now, out of TODO order.** It needs neither the A60 nor 13i. It ships `experimental=True` until the
  ZHA A60 run (13k step 3) proves the color path.

## Steps

0. **Set up.** Use worktree `wt/zha-get-attributes` off `release/v0.0.2`. Save this plan as
   `docs/plans/2026-10-28-zha-get-attributes.md` in the first commit.

1. **`zha/zcl.py`.** Add the cluster and attribute IDs: Level `0x0008`/CurrentLevel `0x0000`; Color `0x0300` with
   CurrentHue `0x0000`, CurrentSaturation `0x0001`, CurrentX `0x0003`, CurrentY `0x0004`, ColorTemperatureMireds
   `0x0007`, ColorMode `0x0008`, EnhancedCurrentHue `0x4000` and EnhancedColorMode `0x4001`.
   **Fix the `read_attributes` docstring.** It says callers read only after an admin-checked command. That stops
   being true, because get_attributes reads without one. The new justification: the only attributes read are
   OnOff, Level and Color values that HA already shows any user in the light's state.

2. **Adapter: `integrations/zha/get_attributes.py`** `ZHAGetAttributes(Adapter[Request])`:
   - Scope: `AdapterScope(experimental=True, domains={"light"}, max_concurrency=2, confirmable=True)`. No
     `native_groups`: the dispatcher expands a ZHA group to its members (`groups.expand_group`, 9e), one row each.
   - `supports`: as in `turn_on_for`, `not_addressable` when `addressing.address()` is None.
   - `execute`: `self.gather` over the targets. Per light, run reads one after another, so one light never has
     more than one request on the air:
     - OnOff: `(ON_OFF,)`, with `ON_TIME` optional.
     - Level: only if the entity's `supported_color_modes` (a state attribute, present while off) goes beyond
       `onoff`.
     - Color: only if those modes include `color_temp`, `hs` or `xy`. Read `ColorMode` required, plus the rest
       optional, in one request.

     A read error propagates, so `gather` rejects that light and core raises `targets_failed` (9f, as Shelly
     does).
   - Row shaping is a pure function `light_row(on_off, level, color)`, keyed by attribute ID:
     - `brightness`: `round(level / 254 * 100, 1)`. This is a percent, like Hue's and Shelly's, so a read can be
       written back.
     - Color, active mode only, as core and Hue report it. Use `EnhancedColorMode` when present, else `ColorMode`:
       - 2 (CT): `color_temp_kelvin` from the mireds.
       - 1 (xy): `xy_color` = X/65535, Y/65535, rounded to 4 places, plus `rgb_color` and `hs_color` from
         `homeassistant.util.color`, as Hue does.
       - 0 (hs): `hs_color` = hue·360/254, sat·100/254, plus `rgb_color` and `xy_color`.
       - 3 (enhanced hue): as 0, but with hue = EnhancedCurrentHue·360/65535.
     - `timer`: `timer_row("off", on_time / 10)` when OnOff is on and OnTime > 0. Otherwise there's no key. Requiring
       OnOff on guards against devices like the TS011F, which counts OnTime down while off. OffWaitTime is not read:
       it is a guard period after the light turns off, not a timer that turns anything on.
   - Register it in `integrations/zha/__init__.py` `ADAPTERS`.

3. **Unit tests: `tests/integrations/zha/test_get_attributes.py`.** Fake `zcl.read_attributes` by
   `(cluster, attributes)`, alongside `tests/fixtures/zha.py` and the `zha_groups` fixture in `conftest.py`.
   Assert whole rows. Cover:
   - an on/off-only light (no Level or Color read);
   - a dimmable light, on and off;
   - CT mode;
   - xy, hs and enhanced-hue modes;
   - a running timer, OnTime > 0 while off (no timer), and no OnTime attribute;
   - `not_addressable`;
   - a read error, which raises `targets_failed`;
   - a ZHA group expanding to one row per member.

   The module needs ≥95% coverage. Extend `test_zcl.py` if the IDs move.

4. **Rig steps: `tests/rig/steps/get_attributes.yaml`.** The existing steps already reach ZHA:
   - `reads_while_off` runs on [light_ct, group]. 102 gives 40.2 %, and 2700 K round-trips through 370 mireds.
   - `reads_a_running_timer` runs on [light_dimmable]. The ZHA bulb has OnTime.

   Add `reads_color_while_off` [light_color] `only: [zha]`. It sets a color, turns the light off and expects
   `hs_color` near it with `color_temp_kelvin: null`. Since `_matches` compares lists exactly, assert on
   `hs_color.0`/`.1` ranges, adding list indexing to `_lookup` (with an engine test) if it lacks it. The step skips
   until the A60 is on ZHA (13k step 3).

5. **Rig run.** The rig is pre-authorized for 2026-10-28 only, so on any other day ask Jason first. Check the rig
   lock and the deployed tree (memory: rig shared with other sessions). Then run
   `scripts/rig.py --action get_attributes` in the background. Write `docs/bench/zha/get_attributes.md` from the
   run, covering brightness, CT, the timer and the group. Color is pending 13k step 3, so `experimental` stays.

6. **Docs.**
   - `docs/integrations.md`: add a ZHA `### get_attributes` section, between `turn_on_for` and `Cancelling`. Cover
     the live reads (one request per cluster per light, so slower than HA state but right mid-move and after raw
     commands), a percent brightness, and the timer from OnTime.
   - `README.md`: the ZHA `get_attributes` cell, marked the way other experimental cells are.
   - Slice plan: update the 13e row to live reads, `light` only, with no `Transition` dependency. In the 13f row,
     drop "13e's get_attributes reads its prediction".
   - `TODO.md`: move 13e into Done in this PR.

7. **Land it.** Run `.venv/bin/pytest`, `pre-commit run --all-files` and `scripts/check_release.py --coverage`.
   Then run `/audit-code` on the diff and fix what it finds. Open a PR into `release/v0.0.2`, then
   `merge-green <n> --squash --delete-branch` in the background. Remove the worktree and its branch.

## Critical files

- New: `custom_components/device_side/integrations/zha/get_attributes.py`,
  `tests/integrations/zha/test_get_attributes.py`, `docs/bench/zha/get_attributes.md`
- Edited: `integrations/zha/{__init__,zcl}.py`, `tests/rig/steps/get_attributes.yaml` (maybe
  `tests/rig/engine.py`), `docs/integrations.md`, `README.md`, the slice 13 plan, `TODO.md`
- Reused: `zha/zcl.py:read_attributes`, `zha/addressing.py:address`, `zha/groups.py:expand_group`,
  `core/timer.py:timer_row`; `shelly/get_attributes.py` and `hue/get_attributes.py:attributes` as the patterns
  for the row shape

## Verification

- Unit: `.venv/bin/pytest tests/integrations/zha tests/actions tests/scripts`, then
  `scripts/check_release.py --coverage`.
- Rig: in a passing `get_attributes` run, the ZHA bulb reads its brightness and CT while off and reads a live
  `turn_on_for` timer that is gone once the timer ends. The group's members each read back, the Shelly and Hue
  cases still pass, and `reads_color_while_off` skips for lack of a ZHA `light_color`.
