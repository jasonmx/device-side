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

## To go, in order

Slice 13 detail lives in [`2026-10-27-zigbee-parity-timer-state.md`](docs/plans/2026-10-27-zigbee-parity-timer-state.md).
The Hue A60 visits each network once, after that integration's code freezes.

- [ ] **13d** Matter `get_attributes` (plug). Needs no bulb, so it can land any time.
- [ ] **A60 to the Hue bridge** (13k step 1), so the rig has a `light_color` on Hue.
- [ ] **7c2** Hue `move`/`stop` for saturation, rig-run on the A60
  ([`2026-10-27-hue-move-color.md`](docs/plans/2026-10-27-hue-move-color.md)).
- [ ] **Hue color rig run and freeze** (13k step 1): `set_attributes` color and gamut clamp, 7c saturation, with no
  `light_color` skips. Clears `experimental` on the Hue adapters it proves.
- [ ] **13e** ZHA `get_attributes`
- [ ] **13f** ZHA `move`/`stop`
- [ ] **13g** ZHA `set_attributes` while off. ZHA code freezes.
- [ ] **A60 to ZHA** (13k step 2): ZHA color suites. Clears `experimental` on the ZHA adapters it proves.
- [ ] **13h** Z2M `get_attributes`
- [ ] **13i** Z2M `move`/`stop`
- [ ] **13j** Z2M `set_attributes` while off. Z2M code freezes.
- [ ] **A60 back to Z2M** (13k step 3): full Z2M suite. Clears `experimental` on the Z2M adapters it proves.
- [ ] **9d** Rig coverage sweep for the non-color scope (plan in /plan first). 13k covers the color part.
- [ ] **12** v0.1.0: no adapter left `experimental` (`scripts/check_release.py --release`); README feature table
  current; release checklist adapted from hue_dimmer; `predicted_state` default reviewed against the rig runs and
  regression issues since #77.

## After v0.1.0

- **9b** Remote tester flow, once an adapter needs hardware the rig lacks.
