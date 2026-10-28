# Slice 13c: Shelly `get_attributes`

## Context

Slice 13 (`docs/plans/2026-10-27-zigbee-parity-timer-state.md`) closes the v0.1.0 gaps. 13b widened
`get_attributes` to the `switch` domain and added the shared timer row (`core/timer.py:timer_row`). 13c is the
first adapter on that contract. Shelly reads on/off, the running timer, and the bulb's brightness, color temperature and
color from `<Component>.GetStatus`, using the same capabilities `turn_on_for` covers (`Switch`, `RGBCCT`).

Decided in the interview:
- **No `experimental` flag.** The bench record lands in this PR, as in the Shelly bulb PR. The rig reaches the
  whole scope: the plug, the relay shown as a light, and the RGBCCT bulb.
- **The color row matches Hue's.** In RGB mode the row carries `rgb_color` plus `hs_color` and `xy_color` derived from it.

## Steps

0. **Set up.** Use worktree `wt/shelly-get-attributes` off `release/v0.0.2`. Save this plan as
   `docs/plans/2026-10-27-shelly-get-attributes.md` in the first commit.

1. **Probe GetStatus (read-only, before any code).** While a timer runs, read `Switch.GetStatus` on the plug and
   `RGBCCT.GetStatus` on the bulb, with the bulb once in cct mode and once in rgb mode. Then read both again with
   the bulb off. Use a short script against the devices' LAN addresses (memory: Shelly rig LAN addresses), the way
   the earlier spikes were run. Confirm these points:
   - The field names: `output`, `timer_started_at`, `timer_duration`, `brightness`, `ct`, `rgb` and `mode`.
   - Whether `timer_started_at` is fractional.
   - Whether brightness, ct and rgb stay in the status while the bulb is off.

   If a finding contradicts the steps below, take it to Jason before writing the adapter.

2. **Adapter: `integrations/shelly/get_attributes.py`** `ShellyGetAttributes(Adapter[Request])`:
   - Scope: `AdapterScope(domains={"light","switch"}, capabilities={"Switch","RGBCCT"}, confirmable=True)`. Copy
     the comment that `turn_on_for` uses for the out-of-scope components.
   - `supports` follows `turn_on_for`: `super().supports(...) or unsupported_reason(target, self.scope.capabilities)`.
   - `execute`: send one `GetStatus` per target through `self.gather`, and let errors propagate (9f: a device error
     raises). Data goes in a `CONFIRMED` result.
   - Put the call in `rpc.py` as `get_status(target)`. `set_with_timer`'s read-back reuses it.
   - Row shaping is a pure function `status_row(component, status, now)`:
     - **Timer:** when `timer_started_at` and `timer_duration` are present, call
       `timer_row("off" if output else "on", remaining)`. `remaining = started_at + duration - now`, clamped to
       `[0, duration]`. `now` comes from HA's clock (`dt_util.utcnow().timestamp()`). Both clocks are
       SNTP-synced, and the clamp bounds any skew. A status with no timer fields gives no `timer` key.
     - **RGBCCT:** `brightness` is the device's percent, as Hue reports it. `mode == "cct"` gives
       `color_temp_kelvin`. `mode == "rgb"` gives `rgb_color`, plus `hs_color` and `xy_color` from
       `homeassistant.util.color` (`color_RGB_to_hs`, `color_RGB_to_xy`). Only the active mode is reported, as
       core and Hue do.
     - **Switch** (a plug, or a relay shown as a light): the timer only. The row is `{}` when no timer runs.
   - Register it in `integrations/shelly/__init__.py` `ADAPTERS`.

3. **Unit tests: `tests/integrations/shelly/test_get_attributes.py`.** Teach the fixture
   `tests/fixtures/shelly.py:timer_running` to report `timer_started_at`, and RGBCCT status when asked. Cover:
   - the switch with a timer (turns off, and turns on after `turn_off_for`) and without one;
   - the bulb in cct mode, in rgb mode, and off;
   - the remaining-time clamp;
   - refusals (Gen1, not addressable, and `Light`/`CCT`/`RGB`/`RGBW` as `capability_not_tested`);
   - a GetStatus error, which raises;
   - mixed targets in one call.

   Freeze `now` and assert whole rows. The module needs ≥95% coverage.

4. **Docs.**
   - `docs/integrations.md` Shelly section: what get_attributes reads, and that the timer's time left comes from
     the device's `timer_started_at` against HA's clock.
   - The README feature table: the Shelly `get_attributes` cells.

5. **Rig engine: nested response keys.** `tests/rig/engine.py` `_expect_response` resolves a dotted attribute
   name (`timer.turns`, `timer.remaining_s`) in a query response. `timer: null` already asserts the key is absent.
   Add tests in `tests/scripts/test_rig_engine.py`.

6. **Step files: `tests/rig/steps/get_attributes.yaml`.**
   - `predicts_mid_move` gets `only: [hue]`, since Shelly has no `move`.
   - `reads_while_off` [light_ct] already covers the Shelly bulb. 102/255 sends 40 %, inside 39–41.
   - New `reads_rgb_while_off` [light_color], `only: [shelly]`: set red, then off. Expect `rgb_color` near red,
     with `hs_color` present.
   - New `reads_a_running_timer` [switch_plug, light_onoff, light_dimmable]: call `turn_on_for` for 20 s, then
     `get_attributes`. Expect `timer.turns: off` and `timer.remaining_s` between 15 and 20. Wait for the timer to
     end, then expect `timer: null`.
   - New `reads_a_turn_off_for_timer` [switch_plug]: the timer turns it `on`.

   All of these run unattended.

7. **Rig run.** Pre-authorized for 2026-10-27/28. Check the rig lock and the deployed tree first, then run
   `scripts/rig.py --action get_attributes` in the background. It runs the Hue cases too, which shows the
   `only: [hue]` change didn't break them. Write `docs/bench/shelly/get_attributes.md` from the run, covering
   the domains, `Switch` and `RGBCCT`.

8. **Land it.**
   - Run `.venv/bin/pytest`, then `pre-commit run --all-files`, then `/audit-code` on the diff.
   - Open a PR into `release/v0.0.2`. Wait for `ci-green`, then squash-merge it.
   - Mark 13c done in the slice 13 plan.

## Critical files

- New: `custom_components/device_side/integrations/shelly/get_attributes.py`,
  `tests/integrations/shelly/test_get_attributes.py`, `docs/bench/shelly/get_attributes.md`
- Edited: `integrations/shelly/{__init__,rpc}.py`, `tests/fixtures/shelly.py`, `tests/rig/engine.py`,
  `tests/rig/steps/get_attributes.yaml`, `docs/integrations.md`, `README.md`
- Reused: `core/timer.py:timer_row`, `shelly/addressing.py` (`unsupported_reason`, `address`, `rpc_device`), and
  `hue/get_attributes.py` as the pattern for the row shape.

## Verification

- Unit: run `.venv/bin/pytest tests/integrations/shelly tests/actions tests/scripts`, then confirm
  `scripts/check_release.py --release` reports the Shelly adapter as covered by its record.
- Rig: a passing `get_attributes` run where the plug, the relay light and the bulb each read a live timer, the
  bulb reads its color while off, and the Hue cases still pass.
