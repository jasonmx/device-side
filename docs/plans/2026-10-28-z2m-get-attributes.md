# Slice 13h: Zigbee2MQTT `get_attributes`

## Context

Slice 13 (`docs/plans/2026-10-27-zigbee-parity-timer-state.md`) brings `get_attributes` to every integration
before v0.1.0. #109 put Z2M first, because the A60 color bulb is on Z2M now. 13h is the first Z2M sub-slice.
The adapter reads each light's on/off state, brightness, color temperature, color and running `on_time` timer
from the bulb itself. Hue bulbs on Z2M send no reports and Z2M doesn't retain device state, so the reads have
to be live.

Findings 13h builds on (`docs/plans/2026-10-27-zigbee-probe.md` §4): Z2M's generic `read` payload works,
including for `OnTime`, which counts down in tenths during an `on_time` timer and drops to 0 after
`turn_off`. The result reaches MQTT only through `state_property`, which publishes it in the device's state
under that key. Replies took 0.04–0.24 s.

Decided in the interview (2026-10-28):
- **Live ZCL reads.** Send one generic `read` per cluster, one after another. Each reply arrives on the state
  topic under a single key, `device_side_read`. Values are in raw ZCL units, so the row shaping can be shared
  with 13e (ZHA). The key stays in Z2M's state cache (and `state.json`), and this is documented.
- **A group returns one averaged row.** `native_groups=True`. Each member is read and the results are
  averaged the way Hue's room row is: the lit members, or all of them when every member is off. The row has a
  timer only when every lit member has one, and it reports the longest.
- **Out of scope here.** Mid-move prediction arrives with 13i, which moves `Transition` into `core/`.
  Switches stay out of scope, as in `turn_on_for`.
- `experimental=True`. Per the slice plan, the flag is cleared by the Z2M A60 run (13k step 1).

## Steps

0. **Set up.** Create worktree `wt/z2m-get-attributes` off `release/v0.0.2`. Save this plan as
   `docs/plans/2026-10-28-z2m-get-attributes.md` in the first commit.

1. **Probe the reads (before writing any code).** Write a scratchpad script modeled on the 13a probe, using the
   same connection and the `.env.rig` from the main checkout. Check the rig lock first. Run it on the A60 and
   the Z2M CT bulb, with each bulb on, then off, and once during a 30 s `turn_on_for`. Confirm these points:
   - The reply shape for `{"read": {"cluster", "attributes", "state_property"}}` for each cluster:
     - `genOnOff`: `onOff`, `onTime`
     - `genLevelCtrl`: `currentLevel`
     - `lightingColorCtrl`: `colorMode`, `enhancedColorMode`, `colorTemperature`, `currentX`, `currentY`,
       `currentHue`, `enhancedCurrentHue`, `currentSaturation`
   - Each read produces exactly one publish carrying the key, and that publish comes even when the value is
     unchanged.
   - A bulb that is off still answers all three clusters.
   - `colorMode` and `enhancedColorMode` on the A60 in CT, xy and hs (and enhanced hue) mode.
   - A read that fails (an unsupported attribute, or a bulb that is unplugged if one is to hand) shows up on
     `bridge/logging`, or it doesn't.

   If a finding contradicts the steps below, take it to Jason before writing the adapter.

2. **Shared row shaping: `core/zcl_row.py`.** This is a pure function from ZCL attribute dicts to a row, so
   13e (ZHA) can reuse it:
   - **brightness:** `round(currentLevel * 100 / 254, 1)`, the percent Hue reports.
   - **Color, by `colorMode`:**
     - CT mode gives `color_temp_kelvin`, converted from mireds.
     - xy mode gives `xy_color` (/65535) plus the `rgb_color` and `hs_color` derived from it, as
       `hue/get_attributes.py:attributes` does.
     - hs mode (enhanced hue when `enhancedColorMode` says so) gives `hs_color` plus the derived `rgb_color`
       and `xy_color`.

     Only the active mode is reported, as core and Hue do.
   - **timer:** if `onOff` and `onTime > 0`, call `core/timer.py:timer_row("off", onTime / 10, now)`.
   - **average(rows):** used for the group row. Brightness and color temperature are averaged, xy is averaged
     and the other color fields are derived from it again, and the timer is the longest when every row has one.
     Factor the averaging out of `hue/get_attributes.py:attributes` only if that is a clean lift. Don't bend
     Hue for it.

3. **The read: `integrations/zigbee2mqtt/read.py`.** The function is
   `async read_clusters(hass, target, clusters) -> dict[cluster, dict]`:
   - It subscribes to `addressing.state_topic(target)`, then for each cluster in turn publishes
     `{"read": {..., "state_property": "device_side_read"}}` to `topic(target, "set")`.
   - It accepts the first non-retained message whose `device_side_read` keys equal that cluster's attribute
     set. Because each cluster has its own attribute set, a stray publish carrying the previous read's value
     can't be taken for a reply. Note in a comment that an on/off-only light, which reads one cluster, keeps
     that small risk.
   - The timeout is 5 s per cluster, the same as `_STATE_TIMEOUT_S`. A timeout raises, so per 9f the call
     raises `targets_failed`.
   - Which clusters to read follows the entity's `supported_color_modes`: onoff reads genOnOff; brightness adds
     Level; any color mode adds Color.
   - The subscribe and wait pattern comes from `turn_on_for.py:_turn_on` and `native_control.py:_wait`.

4. **Group members.** Move the `bridge/groups` fetch out of `native_control.py:_has_hue_member` into a shared
   helper, `group_members(hass, group_id) -> list[DeviceEntry]` (in `addressing.py` or a small `bridge.py`).
   `native_control` then calls that helper. To get each member's light entity, resolve it through the entity
   registry the way `core/resolver.py:resolve_members` does (domain `light`, platform `mqtt`).

5. **Adapter: `integrations/zigbee2mqtt/get_attributes.py`.** `Z2MGetAttributes(Adapter[Request])`:
   - Scope: `AdapterScope(experimental=True, domains={"light"}, confirmable=True, native_groups=True)`.
   - `supports` refuses targets it can't address (`state_topic` is None, or a group on a custom base topic) as
     `not_addressable`. An empty group is skipped silently, per `docs/action-behavior.md`.
   - `execute` runs `self.gather` per target. A device target gets `read_clusters` → `zcl_row`. A group target
     reads its members one after another inside its own task (gathering them would nest the semaphores) and
     then averages them.
   - Register the adapter in `integrations/zigbee2mqtt/__init__.py` `ADAPTERS`.

6. **Unit tests.**
   - `tests/core/test_zcl_row.py`: each color mode, brightness rounding, a timer and no timer, and `average`.
   - `tests/integrations/zigbee2mqtt/test_get_attributes.py`, using the MQTT mocks the existing Z2M tests use:
     - the read sequence and payloads;
     - a stray publish carrying the previous cluster's value, which must be ignored;
     - a retained message, which must be ignored;
     - a timeout, which raises;
     - a group averaged over its lit members, and a group with every member off;
     - a group timer;
     - `not_addressable`;
     - `native_control` still passing after the extraction.

   Freeze `now` and assert whole rows. The new modules need ≥95% coverage.

7. **Docs.**
   - `docs/integrations.md`, Z2M section:
     - what `get_attributes` reads, and that it reads live;
     - its cost (one round trip per cluster per bulb);
     - the `device_side_read` key it leaves in Z2M's state;
     - the group rule.
   - The README feature table: the Z2M `get_attributes` cell.
   - `TODO.md`: tick 13h.

8. **Rig steps: `tests/rig/steps/get_attributes.yaml`.**
   - `reads_while_off` [light_ct, group] and `reads_a_running_timer` [light_dimmable] already run on Z2M with
     no change. Check that the Z2M inventory roles match.
   - New `reads_xy_while_off` [light_color], `only: [zigbee2mqtt]`. Set an in-gamut `xy_color`, turn it off,
     then expect `xy_color` within a tolerance, `hs_color` present, and `color_temp_kelvin: null`. If list
     tolerances aren't supported yet, extend `tests/rig/engine.py` and its tests.
   - New `reads_a_group_timer` [group], `only: [zigbee2mqtt]`. Run a 20 s `turn_on_for` on the group, then
     expect `timer.turns: "off"` with 15–20 s remaining, and `timer: null` after the timer ends.

9. **Rig run.** Rig runs are pre-authorized for 2026-10-28 only; on any other day, ask Jason first.
   - Check the rig lock and the deployed tree first, since other sessions share the rig.
   - Run `scripts/rig.py --action get_attributes` in the background. It runs the Hue and Shelly cases too.
   - Write `docs/bench/zigbee2mqtt/get_attributes.md` from the run. It feeds the 13k step 1 flag clearance.

10. **Land it.** Run `.venv/bin/pytest` and `pre-commit run --all-files`. Then run `/audit-code` on the diff and
    fix what it finds. Open a PR into `release/v0.0.2`, then run `merge-green <n> --squash --delete-branch`
    in the background. Remove the worktree when it's merged.

## Critical files

- New: `core/zcl_row.py`, `integrations/zigbee2mqtt/{read,get_attributes}.py`, their tests, and
  `docs/bench/zigbee2mqtt/get_attributes.md`.
- Edited: `integrations/zigbee2mqtt/{__init__,native_control,addressing}.py`,
  `tests/rig/steps/get_attributes.yaml`, possibly `tests/rig/engine.py`, `docs/integrations.md`, `README.md`
  and `TODO.md`.
- Reused: `core/timer.py:timer_row`, `addressing.py` (`topic`, `state_topic`, `group_id`, `bridge_topic`), the
  futures pattern in `native_control.py`, `core/resolver.py:resolve_members` (for the lookup approach), and
  `hue/get_attributes.py` for the row shape and the group averaging.

## Verification

- Unit tests: run `.venv/bin/pytest tests/core tests/integrations/zigbee2mqtt tests/scripts`. Then confirm that
  `scripts/check_release.py --coverage` passes, and that `--release` lists the Z2M adapter as experimental.
- Rig: the `get_attributes` run must pass with no `light_color` skip on Z2M:
  - the CT bulb and the group read while off;
  - the A60 reads xy while off;
  - the dimmable bulb and the group each read a live timer, which is gone once it ends;
  - the Hue and Shelly cases still pass.
