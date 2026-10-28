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
| 7c1 | Hue `move`/`stop` for color temp | #95 |
| 9e | Native groups: decision, ZHA groupcast `turn_on_for`, core `resolve_members` | #97, #104, #106 |
| 9f | Core-aligned failure behavior | #99 |
| 13a | Zigbee probe findings | #98, #100 |
| 13b | `get_attributes` contract: switches and timer row | #101 |
| 13c | Shelly `get_attributes` | #105 |
| 13d | Matter `get_attributes` | #112 |
| 13e | ZHA `get_attributes` (experimental until the ZHA A60 run) | #114 |
| 13h | Z2M `get_attributes` | #117 |
| 13g | ZHA `set_attributes` (experimental until the ZHA A60 run) | #120 |

## To go, in order

Slice 13 detail lives in [`2026-10-27-zigbee-parity-timer-state.md`](docs/plans/2026-10-27-zigbee-parity-timer-state.md).
The A60 (the rig's only color bulb) starts on Z2M and moves twice: to the Hue bridge, then to ZHA. Each
integration's code freezes before its A60 run.

Three lanes run in parallel, each in order: Z2M (`Transition` PR, 13i, 13j, 14, its A60 run), ZHA (13f),
and Hue (from the A60 move on). The rig lock and the bulb moves are shared.

- [x] **`Transition` to core**: refactor PR moving `hue/transition_cache.py` into `core/`. Unblocks 13i and 13f.
- [ ] **13i** Z2M `move`/`stop`, with the hue/saturation stop probe on the A60.
- [ ] **13j** Z2M `set_attributes` while off. Z2M code freezes.
- [ ] **14** Z2M color modes fixed for HA, on by default, and 13i's xy write-back backed out
  ([`2026-10-28-z2m-color-modes.md`](docs/plans/2026-10-28-z2m-color-modes.md)). Counts toward the Z2M freeze.
- [ ] **Z2M A60 run** (13k step 1): full Z2M suite, bulb in place. Clears `experimental` on the Z2M adapters it
  proves.
- [ ] **Move the A60 to the Hue bridge.**
- [ ] **7c2** Hue `move`/`stop` for saturation, built against the A60
  ([`2026-10-27-hue-move-color.md`](docs/plans/2026-10-27-hue-move-color.md)).
- [ ] **Hue A60 run** (13k step 2): `set_attributes` color and gamut clamp, 7c saturation, with no `light_color`
  skips. Hue code freezes. Clears `experimental` on the Hue adapters it proves.
- [ ] **13f** ZHA `move`/`stop`, after the `Transition` PR. ZHA code freezes.
- [ ] **Move the A60 to ZHA.**
- [ ] **ZHA A60 run** (13k step 3): ZHA color suites. Clears `experimental` on the ZHA adapters it proves.
- [ ] **9d** Rig coverage sweep for the non-color scope (plan in /plan first). 13k covers the color part.
- [ ] **12** v0.1.0: no adapter left `experimental` (`scripts/check_release.py --release`); README feature table
  current; release checklist adapted from hue_dimmer; `predicted_state` default reviewed against the rig runs and
  regression issues since #77.

## After v0.1.0

- **9b** Remote tester flow, once an adapter needs hardware the rig lacks.
