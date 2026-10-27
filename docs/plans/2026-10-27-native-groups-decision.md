# Slice 9e: native groups decision, ZHA probe first

## Context

Slice 9e decides whether each integration has `native_groups` on or off for v0.1.0 and records the decision in the repo
plan (`docs/plans/2026-10-23-device-side-repo-plan.md`, row 9e), with bench records for whatever is turned on. The
research (`docs/plans/2026-10-26-native-groups-research.md`) settled everything except ZHA:

- **Z2M:** `turn_on_for` already has `native_groups=True`, fixed in #59 and rig-proved (`group_on_then_off` in
  `docs/bench/zigbee2mqtt/turn_on_for.md`). It stays on. No hook in 9e; slice 13h decides whether its own Z2M
  adapters need one.
- **Matter, Shelly:** HA exposes no native group, so there's nothing to do. Recorded as "n/a".
- **ZHA:** groups are flagged (`is_zha_group`) but there's no `expand_group`, so they return `group_not_supported`.
  Slice 13's ZHA adapters (get_attributes, move, stop, set_attributes) inherit whatever is chosen. The choice is
  between expansion (one unicast per member: keeps `confirmed`, and exposes members that can't run the timer)
  and groupcast (one frame, members in lockstep, `sent` only, silent misses). The data to choose between them
  is missing, so 9e runs a probe first and decides from its findings.

Agreed in the interview: a probe group of both ZHA bulbs plus the TS011F plug; per-command timing extrapolated
to a large group; move/stop included; the probe runs unattended, then the maintainer watches the leading candidate.

## Step 1: probe spike (unattended)

Script in the scratchpad, run against the live HA the way earlier spikes did
(`docs/plans/2026-10-26-zha-ontime-cancel-spike.md`, `2026-10-26-hue-timer-spike.md`: same connection
and `.env.rig` from the main checkout). Check the rig lock and the deployed tree first (another session may own the rig).

Setup: create a ZHA group of the dimmable bulb, the CT bulb and the TS011F plug through ZHA's websocket
(`zha/group/add`). Keep it afterwards for the rig `group` role. Its entity ID goes only into the gitignored
`tests/rig/inventory.yaml`.

Measurements, each repeated 5–10 times, and every command return and HA state change timestamped:

1. **Unicast cost per member**: the existing per-device path (`zha/turn_on_for.py`: optional `light.turn_on`,
   `issue_zigbee_cluster_command`, `zcl.read_attributes` read-back), timed for each stage. Extrapolate the start
   spread to 4, 8 and 12 lights at `max_concurrency=2`, with and without fields.
2. **Groupcast `turn_on_for`**: `zha.issue_zigbee_group_command` with `cluster_id 6, command 0x42, args [0, tenths, 0]`
   for 10 s. Measure each member's on and off times (HA state and the bulb's own report) and the group entity's state lag.
3. **Groupcast, then a unicast `OnTime` read on each member**: does that recover a per-member `confirmed` while
   the start stays one frame? (A hybrid the research didn't consider.)
4. **TS011F under groupcast**: does it ignore the frame, turn on with no timer, or store `OnTime` as it does by unicast?
5. **Fields**: `light.turn_on` with brightness on the group entity, then the groupcast. Is the level applied before the timer?
6. **Guards**: groupcast with a non-admin context is refused (`Unauthorized`); a group ID that doesn't exist is silently
   ignored (confirms the adapter must check `gateway.get_group` itself).
7. **Move/stop drift**: Level `Move` then `Stop` after about 2 s, (a) groupcast and (b) unicast per member through the
   gather. Read `CurrentLevel` on each member afterwards: how far apart the members end up, and how start offset
   becomes level difference.

Output: `docs/plans/2026-10-27-zha-groups-probe.md`, with findings and raw timings in the shape of earlier spike docs.

## Step 2: decide with the maintainer, from the data

Present the findings as a table (spread vs group size, confirmation per option, silent-member behavior, move drift)
with a recommendation. Proposed rule, for the maintainer to accept or change:

- `turn_on_for`: **expand** unless the extrapolated spread at 8 lights is perceptible (about 0.5 s or more). If
  it is, use **groupcast**, adding the per-member read-back of step 1.3 if that works.
- move/stop: **groupcast** if unicast drift between members is visible in step 1.7. Otherwise expand, like
  everything else.
- get_attributes, set_attributes: expand (a read has no lockstep need).
- Open questions 3 and 4 from the research (is `sent` with silent misses acceptable, and the result shape)
  get answered with the same data. Default is per-member results, as HA-group expansion already does.

## Step 3: observed check of the leading candidate

A watched session: each step briefed first, run on the maintainer's go. `turn_on_for` on the
ZHA group (bare, then with brightness) and one move/stop. Lockstep and drift are judged by eye.

## Step 4: implement and record (same worktree, one PR)

Depending on the decision:

- **Expand:** `expand_group` in `integrations/zha/` (new `groups.py`, or alongside `addressing.py`), mapping
  `gateway.get_group(id).members` (`device.ieee`, `endpoint_id`) back to member light entities through the entity
  registry. Model it on Hue's `bridge.expand_group` (sorted by entity_id, members without an entity dropped) and reuse
  `zcl.py`'s `get_zha_gateway` and `addressing.py`'s `_GROUP_MARKER` for the group ID. Register it in
  `zha/__init__.py`. A group that doesn't exist yields `empty_group` through the dispatcher's existing path
  (`core/dispatcher.py` `_expand_native_groups`).
- **Groupcast (if chosen for any action):** a group command helper in `zcl.py`, a group-exists check, the caller's
  context passed through, and `native_groups=True` on that adapter.
- Unit tests under `tests/integrations/zha/` using the fake gateway fixtures already there. ≥95% coverage.
- Rig: add the ZHA group to the private inventory with role `group` (plus `members:` if the group entity
  lacks `entity_id`, as with Z2M). The existing `group_on_then_off` step in `tests/rig/steps/turn_on_for.yaml`
  then runs on ZHA. Add a step with brightness if that one lacks one.
- Rig run filtered to `turn_on_for`, then regenerate `docs/bench/zha/turn_on_for.md` so
  it includes the group rows. `experimental` stays set (the adapter is still experimental for other reasons).
- Repo plan, row 9e: mark it done and record the per-integration decision (Z2M on, ZHA <decision>,
  Matter/Shelly n/a). Add a line to slice 13's plan saying which group path its ZHA adapters take, so
  13e–13g follow it without re-deciding.

## Verification

- `.venv/bin/pytest` and `pre-commit run --all-files` green, ZHA module coverage ≥95%.
- Rig `turn_on_for` run: the ZHA group passes, and the TS011F member reports as the decision predicts (not as a silent `sent` if expanded).
- `/audit-code` on the diff, then the PR into the release branch, `ci-green`, and a self-merge per the maintainer rules.
