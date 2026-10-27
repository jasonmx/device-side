# Hue fades: hide the bridge's misleading reports, show predictions in HA

## Context

The end-value spike (`docs/plans/2026-10-26-hue-echo-spike.md`, Result; `docs/integrations.md` Hue, Tested
behavior) found:
- A Hue transition reports its end value at once, then nothing when it finishes.
- After a stop, the light's halt value is reported late (0.1–27 s, 4 of 6 after 15 s) or never.
- Bulbs sometimes report mid-ramp (about 2 in 20 ramps).

HA copies whatever the bridge reports (`homeassistant/components/hue/v2/light.py:127`), so dashboards and automations
see the end value. 7b's `TransitionCache` (`integrations/hue/transition_cache.py`) predicts brightness on a timer
(duration + `API_SETTLE_SECONDS` = 15 s) for device_side's own `move`/`stop`/`get_attributes`. It misses any real
change made inside that window, so the next `move` starts from the wrong brightness.

A second look at the spike logs (session transcript, run c1.2) showed that the mid-ramp report wasn't a late report
of the earlier stop. It was the *current* ramp's value about 1 s stale (35.18, between the first stop's predicted 38.36
and the then-current 32.52). All six stop reports landed within 0.37 of the prediction. That gives the rule below.

Outcome, designed with Jason 2026-10-26/27:
- **Everyone:** device_side tells the bulb's own reports apart from real changes and drops its prediction on a real
  change.
- **Opt-out option, on by default:** device_side also hides the misleading reports from HA and sends its predictions
  in their place. Its UX beats the fallback when it works. If it looks flaky when v0.1.0 is ready to cut, the
  default flips to off (Jason, 2026-10-27).

## Design

**Classifier (both modes).** For each light with a live cache entry (the existing window: duration + 15 s), a brightness
or `on` event from the bridge is one of:
1. **Our end value**: the first event within ±0.5 of an end value we armed for that light. Arm *before* the PUT,
   disarm if the bridge rejects it. A soft off's echo is `on: false` + brightness 0. A move up from off also gets an
   `on: true`.
2. **A bulb report**: value within ±0.5 of the path travelled so far (between the transition's start and its current
   prediction). This covers late stop reports, the 1-s-stale mid-ramp report, and the 17% `on: true` during a soft off.
3. **A real change**: anything else. Drop the cache entry (`forget`), cancel its pending end event, stop hiding events
   for that light.

A `grouped_light` event for a room with any live member entry is never a real change on its own: a real change to a
room also changes its lights, and their events decide. Once the window has closed, every event is real, so late
reports pass through (truth wins).

**Changes made from HA win at once (both modes).** A `hass.bus` listener on `EVENT_CALL_SERVICE` for the
`light` and `scene` domains resolves the call's targets:
- `homeassistant.helpers.service.async_extract_referenced_entity_ids`, referenced and indirectly referenced
- Hue entity registry `unique_id` gives the resource id
- a room's lights through `grouped_light.get_lights`
- a Hue scene's lights through its group

It then `forget`s each tracked light, whatever the value. Not covered (documented gap): changes from outside HA that
land on the travelled path, and the legacy `hue.activate_scene`.

**Own clears (both modes).** `set_attributes` and `set_scene` `forget` the lights they write.

**Option on: what HA sees.**
- *Ramp start:* remove `dimming` (and a soft off's `on: false`) from our end-value event, in the raw dict, inside a
  synchronous `bridge.events` subscriber. aiohue's controller handler is async (`create_task`), so it applies the
  event after our subscriber returns. HA keeps the start value.
- *Moving up from off:* rewrite the event so HA sees `on: true` at the light's `dimming.min_dim_level`. A room gets
  its lights' average.
- *Bulb reports* (2) inside the window are hidden too. *Real changes* (3) pass through untouched.
- *Stop:* send each light's predicted value, plus the room's `grouped_light` as the mean of its lit lights.
- *Ramp end:* send the target. For a soft off, send `on: false` and leave `dimming` alone (the bridge keeps the old
  brightness).
- *No ticks during the fade.*
- Sending means `api.events.emit(EventType.RESOURCE_UPDATED, {...})`, which is in-process only and never reaches
  the bridge. Our events carry a marker key that aiohue ignores (`update_dataclass` only reads dataclass fields), so the
  classifier skips them.

**Robustness.**
- When the subscriber attaches in "on" mode, check that `lights._handle_event` and `grouped_light._handle_event`
  are coroutine functions. If not, run as "off" and log one warning.
- A unit test pins the shared-dict ordering against the pinned aiohue.
- Reconnects (aiohue's `__handle_reconnect` skips `emit`) and HA restarts fall back to the bridge's value. Accepted,
  and stated in the docs.

**Attach lazily.** The first `move` on a bridge attaches the subscriber and the HA listener, once per `HueBridgeV2`
object, stored in `integration_state`. A reload of HA's `hue` entry makes a new object, so the next move attaches
again. device_side's unload detaches everything. End events go through `DeviceSideData.schedule`
(`core/runtime.py`), keyed per light, so a new move or a stop replaces them and `cancel_pending` clears them.

**Option.** A new `OptionsFlow` in `config_flow.py` with one boolean, `predicted_state` ("Show predicted brightness
during Hue fades"), **on by default**. An entry with no saved options counts as on, so existing installs get it
too. An update listener reloads the entry. `async_setup_entry` copies the value into `DeviceSideData`. The default is
one constant in `const.py`, so flipping it before v0.1.0 is a one-line change.

**Tiers.**
- `AdapterScope` gains `options: frozenset[str]`. Hue `move` and `stop` declare `{"predicted_state"}`.
- Bench records gain an optional `Options` row (absent means none).
- `check_tiers.uncovered()` requires, for each scope option, a current-fingerprint record with it on, and one with
  it off.
- `scripts/fingerprint.py` also hashes the modules an adapter imports from its own integration package (relative
  `from .x import`). The layer and the cache then reset `move`/`stop` records when they change.

## PRs (each: worktree `wt/<topic>` off `release/v0.0.2`, per CLAUDE.local.md)

1. **`wt/fingerprint-siblings`, tooling.**
   - `scripts/fingerprint.py` sibling-import hashing.
   - `AdapterScope.options`, the `Options` row in `check_tiers.py` `parse_record`/`uncovered`, and their tests
     (`tests/scripts/test_check_tiers.py`).
   - **Consequence:** every adapter that imports a sibling (all Hue adapters, any ZHA/Shelly helper users) drops to
     `untested` until a rig run writes new records. Run `scripts/fingerprint.py` before and after to list them, and
     point Jason at a full rig run before the next RC.
2. **`wt/hue-classifier`, both modes, no option yet.**
   - `TransitionCache`: `arm`/`disarm`, `on_path`, `forget`, and the `on` echo for soft off and up-from-off.
   - A new `integrations/hue/report_filter.py`: the per-bridge subscriber in observe-only mode, plus the HA
     `call_service` listener.
   - `move.py`/`stop.py` arm, attach and schedule. `set_attributes.py`/`set_scene.py` forget.
   - Tests: `tests/integrations/hue/test_transition_cache.py`, a new `test_report_filter.py` driving a real aiohue
     `EventStream`, and the `move`/`stop` tests.
   - Docs: add the c1.2 finding to the spike plan's Result and to `docs/integrations.md` Tested behavior; update the
     `move`/`stop` section (a real change made elsewhere now resets the prediction).
   - Rig: new `move.yaml` tests for "HA `light.turn_on` inside the window, then move", and "stop, then a late
     report, then move".
3. **`wt/hue-predicted-state`, the option.**
   - The options flow, `strings.json`/`translations/en.json`, and `tests/test_config_flow.py`.
   - `report_filter.py` hide/rewrite/emit, plus the robustness check.
   - Scope `options` on Hue `move`/`stop`.
   - Rig: a step-file key that sets the option for a suite through the websocket options flow and restores it, with
     the engine writing the `Options` row. "On" mode tests check HA state directly:
     - start value during the fade
     - the predicted value right after a stop
     - the target at the end
     - a soft off stays on until the end
     - up from off shows the minimum
     - a change from HA mid-fade shows at once
   - Docs: the option in `docs/integrations.md` Hue and the README Hue notes, described as on by default and how
     to turn it off. Update the 7b note in `docs/plans/2026-10-25-hue-port.md` ("off by default") to on by default,
     with the v0.1.0 review.
   - Release gate: no v0.1.0 checklist exists yet, so add "review the `predicted_state` default (flip to off if
     flaky)" to slice 12's row in the delivery table of `docs/plans/2026-10-23-device-side-repo-plan.md`. Base the
     review on regression issues and rig runs since this PR.

Each PR: `.venv/bin/pytest`, `pre-commit run --all-files`, `scripts/check_tiers.py`, `/audit-code` on the diff, a rig
run on the bridge (records written), PR into `release/v0.0.2`, `ci-green`, `pr-merge <n> --squash`, then remove the
worktree. One PR per fresh session.

## Verification

- Unit: the classifier table, with ±0.5 path edges, armed end values (79.84 vs 80), soft-off and up-from-off `on`
  echoes, grouped_light handling and window expiry.
- Unit: the HA listener resolving area, device, room and scene targets.
- Unit: the option's hide/rewrite/emit against a real aiohue `EventStream`, and the async-handler check falling back.
- Unit: `uncovered()` with and without an `Options` row.
- `scripts/fingerprint.py` shows `move`/`stop` changing when `transition_cache.py` changes.
- Rig, both modes, on the `light_ct` and `group` roles: the PR 2 and PR 3 tests above, plus the existing `move.yaml`/
  `stop.yaml` unchanged in "off" mode. Records exist for `move`/`stop` with and without `predicted_state`, so
  `check_tiers` shows both as covered.
- Watched rig check in "on" mode: a dashboard slider holds the start value during a fade, jumps to the stop value at
  release, and never flashes to the end value.
