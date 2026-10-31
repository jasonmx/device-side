# TODO: road to v0.1.0

Progress against the delivery sequence in
[`docs/plans/2026-10-23-device-side-repo-plan.md`](docs/plans/2026-10-23-device-side-repo-plan.md). The plans
hold the design; this file only tracks what is done and what is left. Tick items off in the PR that finishes them.
Delete this file in the v0.1.0 release PR.

## Releases

`v0.0.1` is out, and the HACS submission ([hacs/default#12611](https://github.com/hacs/default/pull/12611)) is
waiting for review. Until it is accepted, no release or RC is cut. Everything lands on `release/v0.0.2`, and
v0.1.0 is the next release.

## Done since v0.0.1

| Slice | What | PRs |
|---|---|---|
| 9a | Rig step files | #26, #27 |
| 6 | Z2M `turn_on_for` | #22, #23, #25 |
| 11 | Matter `turn_on_for` (plugs out of experimental) | #24, #90, #91 |
| 10 | ZHA `turn_on_for` | #31, #32, #34, #39 |
| 9c | Release gates (tiers later replaced by the release flag) | #33, #35, #36, #37, #94 |
| 7a | Hue `set_attributes`, `get_attributes`, `set_scene` | #45 |
| 7b | Hue `move`/`stop` for brightness | #48, #55 |
| 7c1 | Hue `move`/`stop` for color temp (removed in #125) | #95 |
| 9e | Native groups: decision, ZHA groupcast `turn_on_for`, core `resolve_members` | #97, #104, #106 |
| 9f | Core-aligned failure behavior | #99 |
| 13a | Zigbee probe findings | #98, #100 |
| 13b | `get_attributes` contract: switches and timer row | #101 |
| 13c | Shelly `get_attributes` | #105 |
| 13d | Matter `get_attributes` | #112 |
| 13e | ZHA `get_attributes` (experimental until the ZHA A60 run) | #114 |
| 13h | Z2M `get_attributes` | #117 |
| 13g | ZHA `set_attributes` (experimental until the ZHA A60 run) | #120 |
| — | `Transition` cache moved to core, kept per integration | #118, #119 |
| 13i | Z2M `move`/`stop` | #124 |
| 14 | Z2M color modes fixed for HA, on by default | #126 |
| — | Color temperature moves dropped on every integration: no halt of a Hue bulb's fade is clean | #125 |
| — | Six raise and lower actions replace `move` | #128 |
| 13j | Z2M `set_attributes` (experimental; rig run and bench record still to do) | #130 |
| 9d (PR 1 of 3) | Rig coverage sweep: `group_color` role, `observe: roles`, color step cases for 13k | #132 |
| 9d (PR 2 of 3) | Observed-test ledger: observe only the four never-seen cases, `observe: only` | #134 |
| 9d (rig fix) | Rig waits up to 60 s for unavailable targets, then stops before changing anything | #136 |
| 13k (step 1, part) | Z2M hue and saturation bench records on the A60 (`light_color`; `group_color` still to do) | #138 |
| 9d (A0) | A60 move probe: join windows self-close on Z2M and Hue; all three moves scripted (Hue by CLIP v2 only) | #142, #144 |

## To go, in order

Slice 13 detail lives in [`2026-10-27-zigbee-parity-timer-state.md`](docs/plans/2026-10-27-zigbee-parity-timer-state.md).
The A60 (the rig's only color bulb) starts on Z2M and moves twice: to the Hue bridge, then to ZHA. Each
integration's code freezes before its A60 run.

Three lanes run in parallel, each in order: Z2M (`Transition` PR, 13i, 13j, 14, its A60 run), ZHA (13f),
and Hue (from the A60 move on). The rig lock and the bulb moves are shared.

- [x] **`Transition` to core**: refactor PR moving `hue/transition_cache.py` into `core/`. Unblocks 13i and 13f.
- [x] **13i** Z2M `move`/`stop`, with the hue/saturation stop probe on the A60.
- [x] **Raise and lower**: six actions, one per attribute and direction, replace `move`
  ([`2026-10-30-raise-lower.md`](docs/plans/2026-10-30-raise-lower.md)). Lands before 13j's freeze and the Z2M A60
  run.
- [ ] **Raise/lower rig run**: unattended, the six actions and `stop` on Hue and Z2M. Its records replace
  `docs/bench/{hue,zigbee2mqtt}/move*.md` and rewrite `stop*.md`; it measures the new hue, saturation and two-call
  stop ranges for the first time.
- [ ] **13j** Z2M `set_attributes` while off. Z2M code freezes.
  Code, tests and docs merged in #130, experimental. Still to do: its rig run
  (`scripts/rig.py --action set_attributes`, with the new `sets_after_a_soft_off` case, which also runs on Hue and
  ZHA) and `docs/bench/zigbee2mqtt/set_attributes.md`, both in the pre-release full rig run. Tick when the
  record is in.
- [x] **14** Z2M color modes fixed for HA, on by default, and 13i's xy write-back backed out
  ([`2026-10-28-z2m-color-modes.md`](docs/plans/2026-10-28-z2m-color-modes.md)). Counts toward the Z2M freeze.
- [ ] **Z2M A60 run** (13k step 1): full Z2M suite, bulb in place, with the `group_color` cases on a temporary Z2M
  group holding only the A60, created before the run and removed before the bulb moves. Attended for its four
  observed cases (9d ledger in the [plan](docs/plans/2026-10-30-rig-coverage-sweep.md)). Clears `experimental` on the
  Z2M adapters it proves.
- [ ] **Move the A60 to the Hue bridge.**
- [ ] **7c2** Hue `raise_saturation`/`lower_saturation`, built against the A60
  ([`2026-10-27-hue-move-color.md`](docs/plans/2026-10-27-hue-move-color.md)).
- [ ] **Hue A60 run** (13k step 2): `set_attributes` color (rgb, hs and xy) and gamut clamp, the `get_attributes`
  color read, 7c saturation, with no `light_color` skips. Attended for `sets_color_while_off`. Hue code freezes. Clears `experimental` on the Hue adapters it proves.
- [ ] **13f** ZHA raise, lower and `stop`, after the `Transition` PR. ZHA code freezes. Paused on
  `wt/zha-move-stop`: its move adapter splits into the raise and lower actions when it resumes, and its edit to
  `_CaseRun.reading` (group means) is kept alongside this branch's when it merges.
- [ ] **Move the A60 to ZHA.**
- [ ] **ZHA A60 run** (13k step 3): ZHA color suites, `set_attributes` hs and xy included. Attended for
  `sets_color_while_off`. Clears `experimental` on the ZHA adapters it proves.
- [ ] **9d** Rig coverage sweep for the non-color scope
  ([`2026-10-30-rig-coverage-sweep.md`](docs/plans/2026-10-30-rig-coverage-sweep.md)). 13k covers the color part.
- [ ] **12** v0.1.0: no adapter left `experimental` (`scripts/check_release.py --release`); README feature table
  current; release checklist adapted from hue_dimmer; `predicted_state` default reviewed against the rig runs and
  regression issues since #77.

## After v0.1.0

- **9b** Remote tester flow, once an adapter needs hardware the rig lacks.

## Candidates

- **15** Test bench, if the 9d A0 probe shows scripted A60 moves and self-closing join windows are reliable
  ([plan](docs/plans/2026-10-30-rig-coverage-sweep.md)). [Probe](docs/plans/2026-10-31-a60-move-probe.md): all
  three moves scripted and join windows bounded. The bench is three lamps in the maintainer's own room,
  which no one else uses, near the bridge and the coordinators. They hold a Hue white ambiance bulb, a Hue color
  bulb and a Hue White bulb. The rig moves them between Z2M, ZHA and Hue. Rig-made groups, zones and scenes are
  named `ds-rig-*` and removed after each suite, and `--recover` removes them after a crash. Tests can then run
  while the rest of the house is in use, with no test fixtures left in it.
  - **Home network is Hue.** Before a bulb's first move, save its room membership and its scene actions. After the
    suite, move it back and restore both against the bulb's new light ID.
  - **Fixed HA entity IDs**: rename after every join, so automations and dashboards survive.
  - **The room's automations** go in `RIG_PAUSE`. Optionally, an empty-room check runs before an unattended run.
  - **A Zigbee plug (TS011F or similar) on each lamp**, plain on/off, set to power on after an outage. It brings a
    lamp back on if it was switched off, and runs power-loss cases. The lamps' inline switches stay on. Probe first:
    the plug's relay latency, and whether its power metering is fast enough to confirm on and off.
  - The house run before each release adds the mesh, a second brand (the Sengleds) and mixed groups. Records say
    bench or house.
  - Hue `set_scene` §5.4-5.8 scene kinds come within reach.
  - Plan in /plan first.
