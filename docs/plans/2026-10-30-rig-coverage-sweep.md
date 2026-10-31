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
removes the bulb from its current network, which sends a Leave, then opens joining on the target network only.

| Move | Remove | Join | Fallback |
|---|---|---|---|
| Z2M → Hue | Z2M `bridge/request/device/remove` | CLIP v2 `zigbee_device_discovery` `action: search` (or v1 `POST /lights`) | Bridge touchlink by serial: v1 `POST /lights` `{"deviceid": [...]}` |
| Hue → ZHA | v1 `DELETE /lights/<id>` | `zha.permit` | Z2M `bridge/request/touchlink/factory_reset`, with only ZHA open |
| ZHA → Z2M | `zha.remove` | Z2M `bridge/request/permit_join` | Same Z2M touchlink |

- **Probe**: run each move once from a scratch script, after the Z2M A60 run, in place of the manual moves 13k
  plans. Record which call worked, the time to join, and whether a fallback was needed. Write the findings to
  `docs/plans/2026-10-31-a60-move-probe.md`, with no serials, IEEEs or names.
- **Auto-close check**, before the first move (Jason, 2026-10-31): does each network close joining by itself, so a
  script crash can't leave it open? With no device trying to join (the A60 on another network or not pairing):
  - Open joining for 60 s, and never close it from the script: Z2M `bridge/request/permit_join` with `time`,
    `zha.permit` with `duration`, Hue v1 `POST /lights` or a v2 `zigbee_device_discovery` search.
  - Poll that network's own join state until it reads closed (Z2M `bridge/info` `permit_join` and
    `permit_join_end`; the Hue search status leaving `searching`), and record how long it took.
  - After the window plus a margin, close joining explicitly and record "did not auto-close".
  - If ZHA shows its join state nowhere readable, record that, and use the coordinator's permit response or logs.
  - Expected, unverified: Z2M 1-254 s and ZHA up to 254 s close on their timers; a Hue v1 search stops after about
    40 s and a v2 search times out.
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
