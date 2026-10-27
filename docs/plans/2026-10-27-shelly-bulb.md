# Shelly bulb: timed on/off for a color light

## Context

Both Shelly adapters cover only the `Switch` capability with no light fields. The plan's slice 3 left `Light`/`CCT`/`RGB*`
out of scope until hardware covered one. The rig now has a Shelly Multicolor Bulb Gen3, so this
work brings its component and light fields into scope for `turn_on_for` and `turn_off_for`, proved by rig records.
It's the Shelly part of slice 9d.

Decisions made in the interview:
- **No `experimental` flag.** The scope edit and the record that proves it land in one PR. Until then the adapter
  reads `untested`, which already blocks `cut-release`.
- **Fields:** `brightness`, `color_temp_kelvin`, `rgb_color` and `transition`. `hs_color` and `xy_color` stay refused,
  as `docs/integrations.md` already says.
- **Record capability gap gets an issue, not a fix here.** `render_record` (`tests/rig/engine.py`) lists every scope
  capability once any case reaches a device.
- **The Shelly RGB test is observed.** Brief Jason and wait for his go before running it.

## Steps

0. **Set up.** Use worktree `wt/shelly-bulb` off `release/v0.0.2`. Save this plan as
   `docs/plans/2026-10-27-shelly-bulb.md`.
1. **Confirm the component.** Read the bulb's entity-registry `unique_id` suffix through the rig's HA. I expect
   `rgbcct:0`, since HA's `RpcShellyRgbCctLight` exists for this bulb. If it's `rgbw` or `cct` instead, follow the
   same steps for that component (RGBW: check that `rgb` without `white` behaves as core does before scoping
   `rgb_color`). Also note the entity's `min/max_color_temp_kelvin`.
2. **Widen the scope** in `integrations/shelly/turn_on_for.py` and `turn_off_for.py`:
   - `capabilities={"Switch", "RGBCCT"}`
   - turn_on_for gets `fields={"brightness", "color_temp_kelvin", "rgb_color", "transition"}`
   - Update the "wait for a tester's report" comments to name what's still out (`Light`, `CCT`, `RGB`, `RGBW`).

   `rpc.py` `light_params` and `addressing.py` `COMPONENT_FIELDS` already translate and gate these, so no code
   changes there.
3. **Unit tests** (`tests/integrations/shelly/`). Update the tests that assert the old refusals:
   - `test_relay_lights_run_but_fields_and_capabilities_out_of_scope_are_refused`
   - the `fields_not_tested`/`fields_not_supported` parametrization

   A relay shown as a light with `brightness` now gets `fields_not_supported`, not `fields_not_tested`. Add an
   RGBCCT case for `turn_off_for`. Keep the adapter modules at ≥95% coverage.
4. **Step files** (`tests/rig/steps/`). Steps `z2m_option`/`expect_z2m_option` do nothing on Shelly, so the
   existing tests can be reused where the expectations match:
   - `turn_on_for.yaml`:
     - Add `shelly` to `only` on `bulb_brightness_then_off` and `bulb_color_temp_then_off`.
     - `refuses_brightness_out_of_scope` (light_onoff, Shelly only): the expected summary becomes
       `fields_not_supported`. Rename it to `refuses_brightness_on_a_relay_light`.
     - New `bulb_transition_then_off` [light_dimmable], `only: [shelly]`: `brightness: 128, transition: 2`, then
       expect brightness in range within `tol + 2`, on, then off.
     - New Shelly RGB test [light_color], `only: [shelly]`, under a name that doesn't clash with
       `bulb_rgb_then_off`. Setup is warm white (2700 K), then off. Call `rgb_color: [255, 0, 0]` and expect
       `color_mode: rgb` and `rgb_color` near red, then off. Add an `observe` block shaped like the Z2M one.
   - `turn_off_for.yaml`: replace `refuses_a_dimmer_out_of_scope` with `bulb_off_then_on` [light_dimmable].
     - Set it on at brightness 128.
     - Call it off for 6 s.
     - Expect off, then on again with brightness back in range. This proves the bulb returns at its level.
5. **Inventory.** Add this to the main checkout's gitignored `tests/rig/inventory.yaml` under `shelly:`:
   the color bulb with roles `[light_dimmable, light_ct, light_color]`. It's a household file, so don't
   copy it into the worktree.
6. **Rig run** (pre-authorized for 2026-10-27/28): `scripts/rig.py --integration shelly` in the background.
   - Check the rig lock and the deployed tree first, since other sessions share the rig.
   - Run unattended first. Then brief Jason on the observed RGB case and run it on his go.
   - A full pass rewrites `docs/bench/shelly/turn_on_for.md` and `turn_off_for.md`. Review the diff: Capabilities
     should list `RGBCCT` and `Switch`, and Fields should list all four.
7. **Docs.**
   - `docs/integrations.md` Shelly:
     - Replace "Only relays are in scope" in the `turn_on_for` text and Sharp edges with relays plus `RGBCCT`.
     - Remove "Light fields are not accepted" only if it's wrong (it isn't for `turn_off_for`, so keep it).
     - Add the bulb to the tested-on line.
   - README Shelly cells: `✅ switches, color bulbs<br>🙋 other lights` on both rows (the README describes the next
     release).
8. **Issue** for the record capability gap, with a comment recommending the fix shape (per-case reached capability
   from the unique_id suffix, rendered in place of the scope's list) and a Sonnet agent.
9. **Before the PR:** run `.venv/bin/pytest`, `pre-commit run --all-files`, `scripts/check_tiers.py` (both Shelly
   adapters `beta`), then `/audit-code` on the diff. Open the PR into `release/v0.0.2`, wait for `ci-green`,
   squash-merge, and remove the worktree.

## Verification

- pytest green with coverage met. `check_tiers.py` prints both Shelly adapters as `beta`, with RGBCCT and the four
  fields covered.
- On the rig run, every Shelly case passes or is skipped for a role that isn't in inventory (`light_onoff`).
- In the observed case, Jason confirms red from the start, then off at about 6 s.
