# ZHA timer cancel without a flicker: bench spike

## Context

On ZHA, a plain `light.turn_on` leaves a running `turn_on_for` timer in place, so the bulb still turns off on
time (`docs/integrations.md`, ZHA, Tested behavior). The only tested cancel is `light.turn_off`; keeping the
light on means off then on, which blinks. The repo plan's cancel contract promises a plain on/off cancels on
every integration, so ZHA only half keeps it.

The question is whether a running timer can be stopped while the light stays on. Two candidates:

- **A. Write `OnTime` = 0** through `zha.set_zigbee_cluster_attribute`. The ZCL spec makes the attribute
  writable; whether the LTA004 accepts it and stops the timer is untested.
- **B. Send `OnWithTimedOff` with `on_time: 0`**, the command `turn_on_for` already sends. If it works,
  cancelling needs no new kind of call. Note that `turn_on_for` with `duration: 0.05` (`MIN_DURATION_S`)
  already sends `on_time: 0` (`round(0.5)` is 0 in Python), so the spike checks both routes.

What this can't do: make a plain `light.turn_on` cancel. Device Side never sees that call, and the repo plan
rules out an HA-side hook. So a working candidate gives a flicker-free cancel *someone has to call*. What
to do with it is **decided after the results** (Jason, 2026-10-26): a documented user workaround, a Device
Side cancel action, or the contract text left as is. No adapter code in this spike.

## Steps

1. **Worktree** `wt/zha-ontime-cancel-spike` off `release/v0.0.2`. Commit this plan as
   `docs/plans/2026-10-26-zha-ontime-cancel-spike.md` (the only commit besides step 4's docs).
2. **Script** in the scratchpad (`uv run`, PEP 723, aiohttp + pyyaml). It runs from the main checkout's
   household files, read at run time and never printed: `.env.rig` (`HA_URL`, `HA_ADMIN_TOKEN`) and
   `tests/rig/inventory.yaml`'s ZHA `light_dimmable` (the LTA004, firmware `0x01001416`). Reuse
   `tests/rig/client.py` `HAClient` (websocket `command`, `call_service`, `get_state`) and
   `integrations/zha/addressing.py` `address()` on the entity registry `unique_id`
   (`config/entity_registry/get`). Every second it logs elapsed time, the entity's on/off and `OnTime` from
   websocket `zha/devices/clusters/attributes/value` (cluster 6, `in`, attribute `0x4001`). The log has no IDs
   or names. A `finally` puts the bulb back in its prior on/off state with no timer running (off, then the
   prior state, if a timer is left).
3. **Experiments**, each starting with `device_side.turn_on_for` for 20 s on the bulb, then waiting 2 s
   (ZHA ignores "on" reports for 1.5 s after a `turn_off`):
   - a. **Write `OnTime` = 0** at 5 s (`zha.set_zigbee_cluster_attribute`, `value: 0`). Record the call's
     result and any ZCL write status. Does `OnTime` read 0, does the bulb stay on past 22 s, any blink in the
     on/off log?
   - b. **`OnWithTimedOff` `on_time: 0`** at 5 s through `zha.issue_zigbee_cluster_command` (same params as
     `integrations/zha/turn_on_for.py`). Same checks.
   - c. **`turn_on_for` `duration: 0.05`** at 5 s, the same command through Device Side. Same checks, plus the
     returned result (status and detail; a `timer_not_reported` from the read-back is expected and fine).
   - d. **Write `OnTime` = 0 with no timer running** (bulb on, then bulb off): nothing changes, and the bulb
     doesn't turn on.
   - e. **Write `OnTime` = 100** mid-timer: does it reset the remaining time to 10 s? Worth knowing, but only
     informative.
   Whichever of a, b, c works gets one repeat to rule out a fluke.
4. **Record**: add the results under ZHA "Tested behavior" in `docs/integrations.md`, and update the
   "Cancelling" paragraph with any call that works, stated as tested on one bulb. Note the spike in the repo
   plan's open item 3 (ZHA) with date, firmware and HA version. Public repo: no IDs, names or hosts. Raw logs
   stay in the scratchpad.
5. **Decide with Jason**: user workaround in docs / Device Side cancel action / leave as is. The decision goes
   into the repo plan's cancel-contract bullet; anything that needs code gets its own plan in a fresh session.
6. `.venv/bin/pytest`, `pre-commit run --all-files` (run against the worktree), `/audit-code` on the diff. PR
   into `release/v0.0.2`, `ci-green wt/zha-ontime-cancel-spike` in the background, squash-merge, then remove
   the worktree and branch.

## Verification

- Each of a to e has a recorded result, or is marked open with the reason.
- The bulb ends in its prior on/off state with `OnTime` 0 (read it once at the end).
- `git diff` holds no household identifiers; the household check passes.

## Result (2026-10-26)

No candidate works: a, b and c each ended the timer by turning the bulb off within 0.3 s, so none got a
repeat. Candidate c never sent `on_time: 0`: the ZHA adapter's 0.1 s minimum clamps 0.05 s to `on_time: 1`.
d changed nothing; e reset the remaining time to 10 s. The bulb ended off with `OnTime` 0, as before.
Details: `docs/integrations.md`, ZHA, Tested behavior.

**Decision (Jason, 2026-10-26):** narrow the contract. On ZHA only `turn_off` cancels; the repo plan's
cancel-contract bullet, the `turn_on_for` description and the README say so. No code.
