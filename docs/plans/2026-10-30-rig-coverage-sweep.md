# 9d: rig coverage sweep, non-color scope

Saved in the repo as `docs/plans/2026-10-30-rig-coverage-sweep.md`.

## Context

Repo plan slice 9d: audit every adapter's scope against the rig hardware, add roles and step files for what the rig
can reach, leave a record for each, and list what it can't reach for 9b. 13k covers color on the A60 visits. v0.1.0
(slice 12) needs `scripts/check_release.py --release` green, so every adapter still `experimental` needs a record
covering its whole scope, or a narrower scope.

The audit (this session, from the code, step files, records and inventory) found:

- **Fingerprints are gone** (release-flag plan). The 9d row's "current-fingerprint bench record" now means a record
  from a rig run on the code that ships.
- **Most records are stale**: every Hue and Z2M raise/lower/stop record predates #128 (`move*.md`, old test names);
  the rest predate later commits. The closing full-suite run rewrites them all.
- **Non-color gaps the rig can reach**: Z2M `light_raised_mid_room_lower[group]` is skipped because the Z2M
  `light_ct` bulb isn't in the Z2M group.
- **Color gaps no plan owns**: no step sends `hs_color` or `xy_color` to `set_attributes`; no Hue gamut-clamp case;
  Hue `get_attributes` has no color read; Z2M `transition` has no Z2M case; Z2M hue/saturation ramps and `stop`
  declare `native_groups` but no rig group has a color bulb.
- **Observed twins**: most raise/lower/stop and some turn_on_for twins are `not observed`, so they don't count yet.

## Decisions (interview, 2026-10-30)

- **Hue `set_scene` stays at §5.1-5.3.** §5.4-5.8 (scene kinds, large room, second bridge) go on the 9b list. Scope
  has no notion of scene kind, so nothing is refused.
- **The E27 joins the Z2M group.** Claude adds it (Z2M request, not rewiring) and lists it in the group's `members`
  in the household `inventory.yaml`. Jason authorized this change.
- **Color gaps fold into 13k.** 9d's first PR writes their step cases now, before the Z2M A60 run.
- **Color group ramps get a one-light color group on the A60's Z2M visit, removed before it moves.** Jason approved
  adding the A60 to the Z2M group. But `has_feature` (`zigbee2mqtt/bridge.py:26`) needs every member to expose
  `color_hs`, so a group that also holds the Sengleds and the E27 always returns `fields_dropped` and proves no color
  groupcast. So the A60 goes into a temporary Z2M group of its own, under a new `group_color` role. This changes
  what Jason approved, so it is confirmed again at plan approval.
- **Observed tests cost Jason's time.** Keep an observed run only for behavior never seen on hardware whose miss
  would hurt CX. A behavior already watched once, or one the unattended checks prove with high confidence, loses its
  `observe` block. Jason approves the remaining list before any attended run.
- **Closing run**: one unattended full suite on every integration, then one attended session for the approved
  observed list only. Together they serve as the pre-RC full-suite run for v0.1.0.
- **Out of scope, stays refused, goes on the 9b list**:
  - Shelly `Light`/`CCT`/`RGB`/`RGBW` components.
  - Matter lights.
  - Zigbee plugs and switches (memory: the TS011F ignores the timer).
  - Hue `set_scene` §5.4-5.8.
  - Shelly `light_onoff` stays skipped. Proof follows the call: `Switch.Set` is proven through `switch_plug` and
    `light_wrapped`.
  - The `z2m_color_modes` opt-out is unit-tested only: the probe found the override can't be cleanly removed.

## Steps

### PR 1: step files for the color gaps, and the plan (no rig)

Worktree `wt/rig-coverage-sweep` (this one), into `release/v0.0.2`. It must merge before the Z2M A60 run.

1. Save this plan as `docs/plans/2026-10-30-rig-coverage-sweep.md`.
2. **`group_color` role**: add it to `ROLES` in `tests/rig/inventory.py`, with a line in
   `tests/rig/inventory.example.yaml` and the role table in `docs/contributing/testing.md`. It means "a native group
   whose members all take color".
3. **Step cases** (`tests/rig/steps/`). Match each case's expectations to the integration's documented behavior in
   `docs/integrations.md` and `docs/action-behavior.md`:
   - `set_attributes.yaml`:
     - `sets_hs_while_off[light_color]` and `sets_xy_while_off[light_color]`, modeled on `sets_color_while_off`,
       automated only.
     - A Hue gamut-clamp case (`only: [hue]`): an xy outside the A60's gamut, expecting the clamped point Hue
       reports.
   - `get_attributes.yaml`: run `reads_color_while_off[light_color]` on Hue too. Check its `only:` list.
   - `turn_on_for.yaml`: make `bulb_transition_then_off` reach Z2M on `light_dimmable` (13k step 1's "missing
     `transition`").
   - `raise_saturation`, `lower_saturation`, `raise_hue`, `lower_hue`, `stop.yaml`: add `group_color` to the roles
     of the color cases. Automated only.
4. **Engine**: check that `group_color` resolves like `group` (`members`, `target: group` handling in
   `tests/rig/engine.py`). Extend the role-to-group logic where it keys on the literal `"group"`. Add unit tests in
   `tests/rig/` for any engine change.
5. **TODO.md**:
   - 13k step 1: add the `group_color` cases, and the temporary A60 group created and removed.
   - 13k step 2: add hs/xy, gamut clamp, and the `get_attributes` color read.
   - 13k step 3: add hs/xy.
   - 9d: link this plan.
6. **Repo plan**:
   - In the 9d row, replace "current-fingerprint" with "from the closing run".
   - Rewrite the "Hardware the rig still lacks" paragraph to match the 9b list above.
7. `.venv/bin/pytest`, `pre-commit run --all-files`, `scripts/rig.py --dry-run` (prints the plan only, no
   gate), `/audit-code`, then the PR and `merge-green`.

### PR 2: observed-test ledger and pruning (no rig)

8. **Ledger**:
   - For every test with an `observe` block, find in the bench records' git history (`git log -p -- docs/bench`) if
     its observed twin ever passed, and in which record and commit.
   - Note which behavior each one watches (`watch`/`ask`), and whether the unattended checks (`sample`,
     `expect_state`) already measure it.
   - Classify each: **seen**, **deducible**, or **needs eyes** (never seen, and a miss would hurt CX).
   - The memory's deferred list starts in **needs eyes**, until the ledger shows otherwise: Z2M `hue_cycle_stop`,
     `saturation_down_stop`, `halts_a_lower_to_off`, and the two-call stops `halts_brightness_and_saturation` and
     `halts_brightness_and_hue`.
9. Append the ledger to this plan doc as a table: test, behavior, class, evidence.
10. Send Jason the **needs eyes** list as a short message and wait for his yes. Then delete the `observe` block from
    every **seen** or **deducible** test, and turn their `see`/`watch` into a comment where the reason isn't obvious.
    Observed-only tests (`raise_after_soft_off`, `no_stale_snapshot`) need automated checks to replace their `do`,
    or a decision to keep them.
11. Update `docs/contributing/testing.md` "Observed tests" in one sentence: observe only what hardware has never
    shown and a check can't measure.
12. Tests, pre-commit, audit, PR, merge.

### Rig phase A0: moving the A60 by script (when the rig is back, before its first move)

Jason, 2026-10-31: the A60 exists only for the rig, so the rig should move it between networks itself. Each move
removes the bulb from its current network, which sends a Leave, then opens joining on the target network only. Hue
calls are CLIP v2 only: Device Side's Hue integration doesn't support v1.

| Move | Remove | Join | Fallback |
|---|---|---|---|
| Z2M → Hue | Z2M `bridge/request/device/remove` | CLIP v2 `zigbee_device_discovery` `action: search` | none |
| Hue → ZHA | CLIP v2 `DELETE device/<id>` | `zha.permit` | Z2M `bridge/request/touchlink/factory_reset`, with only ZHA open |
| ZHA → Z2M | `zha.remove` | Z2M `bridge/request/permit_join` | Same Z2M touchlink |

- **Probe**: run each move once from a scratch script, after the Z2M A60 run, in place of the manual moves 13k
  plans. Record which call worked, the time to join, and whether a fallback was needed. Write the findings to
  `docs/plans/2026-10-31-a60-move-probe.md`, with no serials, IEEEs or names.
- **Auto-close check**, before the first move (Jason, 2026-10-31): does each network close joining by itself, so a
  script crash can't leave it open? With no device trying to join (the A60 on another network or not pairing):
  - Open joining for 60 s, and never close it from the script: Z2M `bridge/request/permit_join` with `time`,
    `zha.permit` with `duration`, a Hue v2 `zigbee_device_discovery` search.
  - Poll that network's own join state until it reads closed (Z2M `bridge/info` `permit_join` and
    `permit_join_end`; the Hue search status leaving `searching`), and record how long it took.
  - After the window plus a margin, close joining explicitly and record "did not auto-close".
  - If ZHA shows its join state nowhere readable, record that, and use the coordinator's permit response or logs.
  - Expected, unverified: Z2M 1-254 s and ZHA up to 254 s close on their timers; a Hue v2 search times out.
- **Safety**:
  - Always open joining with a finite, short duration, never "until closed", so a crash is bounded by the network's
    own timer.
  - Before opening joining, check the other two networks are closed, and close the target network once the bulb is
    in.
  - Abort with a clear message if the bulb hasn't joined in 120 s. A person can then reset it with the Hue app's
    Bluetooth reset.
- **Command**, if every move works: `scripts/rig.py --move light_color --to <integration>`.
  - It finds the bulb by IEEE, which is kept in the gitignored `inventory.yaml` or `.env.rig`, and the Hue serial
    goes there too.
  - It waits for the device in HA's registry and gives the entity a stable entity ID.
  - It rewrites that integration's `light_color` in `inventory.yaml`, and re-creates `group_color` where the target
    declares `native_groups`.
  - It takes the rig lock.
  - Unit tests mock the three integrations' calls.
  - A move that failed in the probe stays manual and is documented.
- TODO: the "Move the A60" lines point at the command once it lands.

### Rig phase A: setup for the Z2M A60 run (when the rig is back)

13. Queue behind the rig lock (`scripts/rig.py --wait-free`).
    - Add the E27 to the Z2M group (Z2M `bridge/request/group/members/add`).
    - Create a temporary Z2M group holding only the A60.
    - Edit the main checkout's `tests/rig/inventory.yaml`: add the E27 to `group.members`, and add `group_color`
      under `zigbee2mqtt`. Never commit or copy it.
    - Then the 13k step 1 run takes over (its own session or this one, per TODO).
14. After that run, before the A60 moves:
    - Remove the temporary group.
    - Remove `group_color` from `inventory.yaml`.
    - Keep the E27 in the group.

On the Hue and ZHA visits (13k steps 2 and 3), add a `group_color` only where that integration's color adapter
declares `native_groups`, in the same way, and remove it before the next move.

### Rig phase B: closing sweep (after 13k step 3 and 13f)

15. Unattended full suite: `DEVICE_SIDE_RIG_APPROVED=1 scripts/rig.py --unattended`, in the background.
    - Fix any failures on a `wt/` branch, then rerun the affected actions.
    - Commit the records it writes. The old `move*.md` records are deleted in that commit.
16. Brief Jason on the approved **needs eyes** cases, using exact values (memory: watched briefs) and a `say` cue
    when each starts. On his go, run attended, filtered by `--action` to the step files that hold them.
17. **Records PR**:
    - Records from 15 and 16.
    - Clear `experimental` from every adapter whose record now covers `domains`, `capabilities`, `fields`, and each
      option on and off (CLAUDE.md rule). Cite the record.
    - Any adapter still not covered: narrow its scope to what is proven (refused, never borrowed), or ask Jason.
    - README feature table cells to ✅.
    - TODO: tick 9d and add a "Done since" row.

## Verification

- PRs 1 and 2:
  - pytest green, with ≥95% coverage per adapter module.
  - `scripts/rig.py --dry-run` lists the new cases on the right integrations with the inventory roles filled in:
    for example, `group_color` cases appear only where the inventory names one.
- Phase A: the 13k step 1 record shows `light_raised_mid_room_lower[group]` and the `group_color` cases passed,
  with no skips.
- Phase B:
  - Every `docs/bench/**` record comes from the closing run, with no `move*.md` left.
  - No skips beyond the accepted 9b list.
  - No `not observed` outside the pruned set.
  - `scripts/check_release.py --release` passes.

## Observed-test ledger (PR 2, 2026-10-31)

From `git log -p -- docs/bench`: every `observed` row that ever read `pass`, its record and the commit that added it.
Only three runs were ever watched: Hue at #48 (record commit `3533b73`, rig run on `b7f2228`), Z2M `turn_on_for` at
#80 (`de2f6f5`) and Shelly `turn_on_for` at #87 (`c62a0fb`). Every other observed row is `not observed` or
`skipped`. Old names: `move.md` held the raise/lower tests, `light_moved_mid_room_move` is now
`light_raised_mid_room_lower`, and `halts_a_move_to_off` is now `halts_a_lower_to_off`.

A "live read" is `source: device_side` on Z2M and ZHA, which read the bulb; on Hue the same read returns Device Side's
prediction, so it proves nothing about the light there.

| Test | Integration | Watches | Class | Evidence |
|---|---|---|---|---|
| `raise_brightness: raise` | Hue | smooth climb, no steps or flashes | seen | `hue/move.md`, #48 |
| | Z2M | | deducible | one end-point publish the bulb fades itself; live reads check rising, then steady at ≥99 % |
| `raise_brightness: raise_after_soft_off` | Hue | climbs from the bottom, not from the kept 60 % | seen | `hue/move.md`, #48 |
| | Z2M | | deducible, with a new check | observed-only today; a live `sample` after the stop (steady, 15-50 %) measures where it held: from the bottom it holds near 30 %, from 60 % near 90 % |
| `raise_brightness: raise_stop_raise` | Hue | no drift while held, no jump on resume | seen | `hue/move.md`, #48 |
| | Z2M | | deducible | live reads check steady for 4 s, then rising with max 78 % |
| `lower_brightness: lower_to_off` | Hue | smooth fade, ends off | seen | `hue/move.md`, #48 |
| | Z2M | | deducible | one soft-off publish the bulb fades itself; `expect_state` checks off within 10 s |
| `lower_brightness: light_raised_mid_room_lower[group]` | Hue | the lamp turns back up without a jump | seen | `hue/move.md` (`light_moved_mid_room_move`), #48 |
| | Z2M | | deducible, with a new check | never run (light_ct joins the group in phase A); Z2M publishes only an end point, so the bulb fades from its own level; a live `sample` on light_ct (rising, min 40 %) catches a jump to the bottom or top |
| `stop: halts_a_lower_to_off` | Hue | holds part way, no flash, jump or blink off | seen | `hue/stop.md` (`halts_a_move_to_off`), #48 |
| | Z2M | | **needs eyes** (light_ct) | checks see HA on and a steady live level, not a blink off at the stop; Z2M's soft off and its stop differ from Hue's |
| `stop: hue_cycle_stop` | Z2M | no jump at the stop or a second later | **needs eyes** | reads catch drift after the stop, not a jump in output: a Hue bulb's output departs from what it reports mid-fade (every CT stop jumps) |
| `stop: saturation_down_stop` | Z2M | holds, no drift toward white, no jump | **needs eyes** | as `hue_cycle_stop` |
| `stop: halts_brightness_and_saturation` | Z2M | both freeze at once | deducible from the two above | the single stops in sequence, one publish each; checks prove both froze in range and held for 3 s |
| `stop: halts_brightness_and_hue` | Z2M | both freeze at once | deducible from the two above | as above |
| `raise_hue: cycles_up_the_wheel` | Z2M | direction: orange toward yellow | deducible | `expect_state` hue 72-96° after 3 s at 18°/s is reachable only turning that way |
| `lower_hue: cycles_down_the_wheel` | Z2M | direction: blue toward green | deducible | as above |
| `raise_saturation: saturation_to_a_limit` | Z2M | stays the same blue | deducible | the bulb fades in xy along a straight line between two points of one hue, which stays near it; end checked in range and against a live read |
| `lower_saturation: saturation_to_a_limit` | Z2M | stays the same blue | deducible | as above |
| `set_attributes: sets_color_while_off` | Z2M, Hue, ZHA | lights red from the start, no flash of the old color | **needs eyes** (each A60 visit) | never watched: Hue and ZHA records skipped it (no color bulb), Z2M has no record; a flash is a transient no read sees, and this bulb on Z2M flashes its last color when on and color are sent apart (watched probe, 2026-10-27) |
| `set_scene: sets_while_off` | Hue | every light comes on in the scene | seen | `hue/set_scene.md`, #48 |
| `set_scene: applies_while_on` | Hue | straight to the scene, no light off | seen | `hue/set_scene.md`, #48 |
| `set_scene: no_stale_snapshot` | Hue | an app edit applies | seen | `hue/set_scene.md`, #48; re-read on each call is unit-tested (`test_scene_is_reread_on_each_call`) |
| `raise_brightness-predicted_state: bridge_scene_recall_mid_fade_shows_at_once` | Hue | lights jump to the scene; HA shows it | deducible | the jump is the bridge's own (Device Side sends nothing then); Device Side's part, HA at the scene's level and not the fade's full, is the `expect_state` |
| `turn_on_for: rgbcct_bulb_rgb_then_off` | Shelly | red from the start, off at 6 s | seen | `shelly/turn_on_for.md`, #87 |
| `turn_on_for: bulb_rgb_then_off` | Z2M | red from the start, off at 6 s | seen | `zigbee2mqtt/turn_on_for.md`, #80 |
| `turn_on_for: group_on_then_off` | Z2M | both off at once | seen | `zigbee2mqtt/turn_on_for.md`, #80 |
| | ZHA | | deducible | one group command, as on Z2M; HA's group reads off only once every member is, checked within 2 × tol |

Needs eyes, approved by Jason on 2026-10-31: Z2M `halts_a_lower_to_off[light_ct]`, `hue_cycle_stop[light_color]`,
`saturation_down_stop[light_color]`, and `sets_color_while_off[light_color]` on each of the A60's three visits (it
moves on, so each is watched during its own visit, not in the closing session). Every other `observe` block is
gone, `no_stale_snapshot` with it, and `observe:` takes `only:` as a test does, so the Z2M stop is watched without
Hue's.
