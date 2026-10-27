# ZHA groups probe (slice 9e, step 1)

Bench data for choosing between expanding a ZHA group (one unicast per member) and a groupcast (one frame to
the group address). Plan: `docs/plans/2026-10-27-native-groups-decision.md`. Run unattended on 2026-10-27,
HA 2026.10.2, under the rig lock.

## Setup

A ZHA group (`zha/group/add`) of three members, which stays for the rig's `group` role:

| Member | Model, firmware | Zigbee role | Unicast `OnWithTimedOff` |
|---|---|---|---|
| CT bulb | LTA004, `0x01001416` | router | accepted |
| Dimmable bulb | Sengled E11-G13, `0x00000009` | end device | **rejected**, `UNSUP_CLUSTER_COMMAND` |
| Plug | Tuya TS011F, `0x0000004d` | router | accepted, ignored (stores `OnTime`, stays off) |

ZHA creates a group entity per member domain, even for one member: the group got a `light` entity (the two
bulbs) and a `switch` entity (the plug alone). The light group entity lists its
members in `group_entities`, not `entity_id`, so the rig inventory needs `members:`, as for Z2M.

Only the LTA004 runs the timer, so the probe could not measure on/off spread *between* two timer-capable
members under groupcast. Lockstep under groupcast follows from the single frame, and move/stop (below) shows
both bulbs acting on one frame together.

## Results

Times are medians of 6 runs unless noted; spreads in seconds.

### 1. Unicast cost per member (the current adapter path)

| Stage (LTA004) | Median | Range |
|---|---|---|
| `light.turn_on` with brightness | 0.13 | 0.10–0.18 |
| `issue_zigbee_cluster_command` `OnWithTimedOff` | 0.10 | 0.09–0.14 |
| Read-back, OnOff then OnTime (two websocket reads; the adapter makes one request) | 0.20 | 0.19–0.25 |
| `device_side.turn_on_for` end to end, both bulbs, bare | 0.23 | 0.20–0.24 |
| `device_side.turn_on_for` end to end, both bulbs, brightness | 0.34 | 0.33–0.37 |

The Sengled refuses in 0.07–0.09 s. End to end, `device_side` reports the LTA004 `confirmed` and the Sengled
`rejected` with detail `error`. With brightness, the `light.turn_on` lands before the refused timer, so the
Sengled is left **on with no timer**. Its result says `rejected`, but the detail doesn't say why.

Extrapolated start spread (first member to last) under `max_concurrency=2`, taking one member slot as the
end-to-end time above: last start ≈ (⌈n/2⌉ − 1) × slot. Each member runs its own timer, so the off spread
equals the start spread.

| Lights | Bare (slot 0.23) | With brightness (slot 0.34) |
|---|---|---|
| 4 | 0.23 | 0.34 |
| 8 | 0.70 | 1.02 |
| 12 | 1.15 | 1.70 |

### 2. Groupcast `turn_on_for` (10 s), all members off first

- `issue_zigbee_group_command` returns in 0.02 s (0.02–0.06): zigpy's synthesized success, no delivery feedback.
- LTA004: on 0.12 s after the call (0.11–0.15), off after 10.05 s on (9.97–10.09). Exact, every run.
- Sengled: **never turned on**, in all 6 runs. OnOff reads false; no error anywhere. The silent miss the research
  predicted from ZCL §2.5.12.2, now seen on real firmware.
- Plug: never turned on. `OnTime` read 0 straight after (100 in one run), 78 twenty seconds later.
- Group light entity: on 0.03–0.10 s after the LTA004's report, off within 0.05 s of it.

### 3. Groupcast, then a unicast read on each member

Works. Read straight after the groupcast (0.13–0.25 s per member, sequential):

| Member | OnOff | OnTime | What the adapter would report |
|---|---|---|---|
| LTA004 | on | 98 (of 100) | `confirmed` |
| Sengled | off | none (no such attribute) | `sent`, `not_on` |
| Plug | off | 0 or 100 | `sent`, `not_on` |

So the start stays one frame, and each member still gets its own result. It needs the member list, which is
the same lookup `expand_group` would do.

### 4. TS011F, already on, under groupcast

Stays on: no off within 18 s; `OnTime` 0 straight after, 82 later. It neither runs nor honors the timer. Read
alone it reports `on` with no timer reported: `sent`, `timer_not_reported`.

### 5. Fields: `light.turn_on` with brightness on the group entity, then the groupcast

- The group `light.turn_on` returns in 0.03–0.08 s, and both bulbs report the requested brightness on their
  first report (60, 200, 120). A live `CurrentLevel` read after a request for 90 gives 90 on both.
- The LTA004 then runs the timer (off at 10.1–10.2 s). The Sengled is **left on**, as by unicast, with nothing
  to say so unless the member is read back (OnOff on, no `OnTime`: `timer_not_reported`).

### 6. Guards

- A non-admin token: `Unauthorized` (`home_assistant_error`), nothing turns on. The caller's context must be
  passed, as on the per-device path.
- A group ID that doesn't exist: the call **succeeds** in 0.007 s and nothing happens. The adapter must check
  `gateway.get_group` itself.

### 7. Move/stop drift (Level `Move` up at 50/s from 50, `Stop` after 2 s, 5 runs each)

| Path | Level rise LTA004 | Level rise Sengled | Difference between bulbs |
|---|---|---|---|
| Groupcast | 103 | 95–97 | 6–8 (median 6) |
| Unicast, both at once | 108–111 | 100–104 | 6–8 (median 7) |

The 6–8 levels are the bulbs' own rate difference: the same under both paths. The unicast move and stop each
left the two bulbs 0.005–0.07 s apart. Unicast rises about 5 levels further because its `Stop` takes 0.1 s
longer to return than the groupcast's. A later member's move and stop are both delayed by the same slot, so
start offset becomes a lag *during* the move, not a different end level.

## Raw data

Scratchpad only (`zha_groups_probe.json`: every state event timestamped, every read, every command return).
Household identifiers stay out of the repo.

## Observed check (step 3)

Watched by the maintainer, each test briefed and started on his go.

1. Groupcast `turn_on_for` 6 s, bare, from off: the LTA004 came on at once and went off after about 6 s; the
   Sengled stayed off throughout. As measured.
2. Group `light.turn_on` at brightness 120, then the groupcast: the LTA004 faded on; the Sengled came on
   **later and instantly** (it seems to skip the group frame's transition). The LTA004 went off after about
   6 s; the Sengled stayed on, at 120.
3. Groupcast `Move` up at 50/s for 3 s, then `Stop`: both started, rose and stopped in lockstep (ended at 184
   and 176).
4. The same move by unicast, with the Sengled's `Move` 0.50 s and `Stop` 0.42 s after the LTA004's (about
   what expansion gives a 9–10-light group at `max_concurrency=2`): **the lag was visible** at the start and the
   stop. Test 3 looked better; test 4 was "not terrible", fine for all but the fastest fades.

## Decision (maintainer, 2026-10-27)

- **`turn_on_for`: groupcast, then a unicast read-back of each member.** One `OnWithTimedOff` frame to the
  group (fields first, through the group entity's `light.turn_on`), then each member's OnOff and OnTime, so the
  result stays per member: `confirmed`, or `sent` with `not_on` or `timer_not_reported`.
- **move/stop (slice 13): groupcast.** Expansion leaves no end-level drift, but the members ramp visibly
  apart during the move, which is what a group fade is meant to avoid. The cost: no APS retries, so a lost
  `Stop` leaves a member ramping. Slice 13 checks it on the rig and can add a `CurrentLevel` read-back.
- **get_attributes, set_attributes: expand.**

How it's built: not with `native_groups=True`, the step 4 plan's sketch. A native-group adapter's results are
keyed on the group entity, so per-member results would need a core change. Instead ZHA gets an `expand_group`
hook, and `turn_on_for` batches the expanded members by `via_group`: one groupcast per ZHA group, then the
per-member read-back.
