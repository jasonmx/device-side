# Z2M turn_on_for: read the state back so HA shows it

## Context

After `{"state":"ON","on_time":<s>}`, Z2M publishes no state: the timed branch of `on_off` in
zigbee-herdsman-converters returns no state, `publish.ts` publishes only on a returned state, and Hue bulbs on
Z2M have reporting turned off on purpose (`src/lib/philips.ts`). The device timer works, but HA shows a light
that is on as off, or one that turned itself off as still on. A watched check on a Hue bulb (2026-10-26)
saw no state publish over 20 s, and a Z2M rig run the same evening failed every case.

**Decided: no attribute reporting.** We don't use or recommend configuring `genOnOff` reporting. Users can't be
relied on to set it up for every bulb, and Z2M's maintainers turned it off for Hue to avoid reports that
conflict with optimistic state, so turning it on risks the instability they avoided. Z2M offers no polling
or `optimistic` setting that helps. The adapter's read-backs are the fix: the timer stays on the device, and
HA only refreshes what it shows.

## Decisions (agreed)

- **Read** = publish `{"state":""}` to `<base>/<address>/get`. Z2M reads OnOff, and its `readResponse`
  converter publishes the state, which HA's MQTT light picks up.
- **"On" read**: only on the publish-only path (no fields), 1 s after the publish. With fields,
  `light.turn_on` already makes Z2M publish "on".
- **End reads**: two reads, at `duration + 1 s` and at `duration + max(5 s, 2% of duration)`, so a slow
  bulb clock on a long timer still ends up "off" in HA. Neither depends on what the other returned.
- **Pending reads**: one set of handles per target (keyed by `entity_id`). A new call on that target cancels
  them and reschedules, and entry unload cancels all of them. A restart loses them, and we accept that.
- **Groups**: one read on the group topic `<base>/<ID>/get`. `publish.ts` runs `convertGet` on the group (a
  groupcast read), and `groups.ts` republishes the group's state from member reports, publishing OFF only
  once every member is off (default `off_state`). The rig decides: if members don't answer, a follow-up
  reads members from `bridge/groups`.
- The result stays `SENT`. Reads are fire-and-forget, and their failures are logged at debug and never
  change the result.

## Changes

1. **`core/runtime.py`**: add `pending: dict[str, list[CALLBACK_TYPE]]` to `DeviceSideData`, plus
   `schedule(key, delays_and_jobs)` (cancels whatever is under `key`, then `async_call_later` for each) and
   `cancel_pending()`. Each handle removes itself when it fires. Keep it generic: the key is the caller's
   own, e.g. `"zigbee2mqtt:turn_on_for:<entity_id>"`.
2. **`__init__.py`**: `async_unload_entry` calls `get_runtime(hass).cancel_pending()`.
3. **`integrations/zigbee2mqtt/addressing.py`**: generalize `command_topic` into `topic(target, suffix)`
   (or add `get_topic`) so `/set` and `/get` share the address logic, including the refusal on a custom base
   topic.
4. **`integrations/zigbee2mqtt/turn_on_for.py`**: after the `/set` publish, schedule the reads above through
   `runtime.schedule`. The read job calls `mqtt.publish` (no `blocking` needed; wrap it in try/except +
   `_LOGGER.debug`). Update the class docstring and the module docstring. The fingerprint changes, so
   `zigbee2mqtt / turn_on_for` drops to untested until a new record; it stays `experimental`.
5. **Tests** (`tests/integrations/zigbee2mqtt/test_turn_on_for.py`, `tests/core/`): use
   `async_fire_time_changed` to check:
   - Without fields: `/set`, then `/get` at +1 s, then at duration+1 and duration+max(5, 2%).
   - With fields: no +1 s read, and both end reads happen.
   - A group reads `<base>/<ID>/get`. A custom-base-topic group publishes nothing.
   - A second call on the same target cancels the first call's pending reads (only the new schedule fires),
     and another target's reads are left alone.
   - Unload cancels all pending reads.
   - A read that raises is logged, and the result is still `SENT`.
   - `runtime.schedule` / `cancel_pending` unit tests. Keep coverage of the adapter module at 95% or above.
6. **`docs/integrations.md`, Zigbee2MQTT**: in `turn_on_for`, describe the read-backs and why (no state
   publish for a timed command, no reporting on Hue), and record the no-reporting decision in one line. In
   Groups, say that a group is read on its own topic. Add these sharp edges: a restart during a timer leaves
   HA stale until the bulb next reports, and a read adds one Zigbee read per target (plus one per member for
   a group). Check the README feature table against this.

## Verification

- `.venv/bin/pytest`, `pre-commit run --all-files`, `/audit-code` on the diff.
- Rig: first check Z2M is up. Then a watched session running `scripts/rig.py --integration zigbee2mqtt`.
  It should show:
  - "on" within the 3 s tolerance without fields. If the +1 s read still lands outside it, widen the
    step's window rather than shorten the read delay.
  - "off" after every timer, on the white bulb, the color bulb and the group.
  - The group goes off only once every member is off. If it never does, open the `bridge/groups` member
    read follow-up.
- A full pass writes `docs/bench/zigbee2mqtt/turn_on_for.md` with the new fingerprint.
