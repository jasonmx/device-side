# Slice 9f: core-aligned failure behavior

## Context

The dispatcher raises only when *every* target ends `unsupported` or `rejected`
(`core/dispatcher.py`, `all_targets_failed`), and it refuses a whole target over a single field. Core raises
when the call itself is wrong or a device failed, and never because some targets couldn't take part.
`docs/action-behavior.md` already has the target table, and slice 13's new Zigbee adapters must be written
against it. Slice 13 also needs its field-dropping rule (the Hue bridge drops `hue` on `move`). The facts below
are from a read of HA 2026.10.2: `helpers/service.py` (`_resolve_entity_service_call_entities`,
`_async_handle_entity_calls`), `helpers/target.py` (`async_extract_referenced_entity_ids`) and
`components/light/helper.py` (`filter_turn_on_params`).

The plan doc lands in the repo as `docs/plans/2026-10-27-core-failure-behavior.md`. The build runs in a fresh
session, in worktree `wt/core-failure-behavior` off the current release branch. Adapters are edited wherever
that's the logical place for a change. Fingerprints may change freely, because everything is re-tested at the
end of slice 13.

## Decisions (agreed 2026-10-27)

- **Named or indirect.** A target is *named* when it is in core's `SelectedEntities.referenced`, i.e. the
  caller listed its `entity_id`. Everything else is indirect: an area, device or label, a member of an HA
  group (`group.*` or a light group helper), or a member of a native group the dispatcher expanded. We depart
  from core's `group.*` rule on purpose, because a group is a deliberately mixed set.
- **Can never support** (`unsupported` with a target-level reason). A named target raises
  `TargetNotSupported` **before anything is sent**. An indirect target is skipped, with one warning log per call
  that lists the skipped targets and their reasons. Reasons in this class:
  - `not_in_registry`
  - `integration_not_supported`
  - `domain_not_supported`
  - `domain_not_tested`
  - `no_adapter`
  - `not_addressable`
  - `capability_not_tested`
  - `no_lt_feature`
  - `inverted_wrapper`
  - `bridge_v1`
  - `not_dimmable`
  - `smart_scene`
  - `group_not_supported`
  - `fields_not_tested`, which keeps the scope rule: an untested field is refused, never dropped.
- **Lacks a field.** A field the light can't take at all is dropped, and the rest of the call goes ahead, as
  `filter_turn_on_params` does. Only fields that are left can be `fields_not_tested`. The result carries
  `detail: fields_dropped`. "Lacks" comes from two places:
  - **The target's state, in the dispatcher.**
    - Brightness is lacked when `brightness_supported(supported_color_modes)` is false.
    - A colour field is lacked only when the light has no colour mode, and color temp only when the light has
      neither a CT mode nor a colour mode, because core converts between colour forms before it filters.
    - Transition is lacked without `LightEntityFeature.TRANSITION`.
  - **The adapter**, for what only it knows:
    - `AdapterScope.drops`, for fields its integration can never send (Hue `move` uses it for `hue` once slice
      13 adds that field).
    - The adapter's own per-device checks, such as Hue `set_attributes`' gamut and Shelly's component fields,
      which return `fields_dropped` and apply the rest instead of refusing.

  A `switch_as_x` light given brightness is a lack-and-drop, so the timer still runs.
- **Unavailable or missing** (no state, `unavailable`, or `integration_not_loaded`): skipped. A named one is
  logged with core's own `SelectedEntities.log_missing`.
- **No targets left:** return `None`. If the caller asked for a response, raise `no_entities_matched`, as core
  does. This always applies to `get_attributes` (`SupportsResponse.ONLY`). `empty_group` falls into this case.
- **Device failure** (`rejected`: `error`, `timeout`, `no_result`, `not_on_bridge`, `scene_not_found`,
  `admin_required`): every target still runs, then the call raises `HomeAssistantError` (`targets_failed`),
  listing each failed entity with its detail. That matches core's `gather(return_exceptions=True)` followed by
  a raise.
- **Commands keep their optional status response**, with one entry per target that ran: `confirmed`, `sent`
  or `unchanged`, plus `detail`/`clamped_to`/`integration`. Skipped targets are left out, as core leaves them out.
  `unsupported` and `rejected` never reach a response.
- **No-op calls succeed quietly** (`unchanged` plus detail, nothing logged).

## Changes

1. **`core/dispatcher.py`**
   - Replace `async_extract_entity_ids` with `target_helpers.async_extract_referenced_entity_ids(hass,
     TargetSelection(call.data), expand_group=False)`. That gives the named set and keeps core's
     primary-entities-only filter for indirect targets.
   - Thread `named: bool` onto `Target` (`core/models.py`). Members expanded from HA groups and native groups
     are never named.
   - Split `run_adapters` into **plan** (resolve, availability, state lack-drop, `supports()`) and
     **execute**, so a named refusal raises before any adapter sends.
   - Partition each adapter's bucket by the request left after dropping (`dataclasses.replace` on the
     request). Run one `execute` per distinct request, concurrently.
   - Replace the `FAILED` all-or-nothing raise with the rules above. Response: entries for targets that ran,
     for commands; for queries, the data of the targets that were read (unchanged from today).
   - Remove the early `via_wrapper` + fields refusal (it is now lack-and-drop) and the `light_fields_ignored`
     reconcile step, which a dropped field replaces.
2. **New `core/fields.py`**: `lacking(target, request) -> frozenset[str]`, from state attributes, mirroring
   `filter_turn_on_params` at the family level as above. Each action's request implements a
   `without(fields)` that returns the reduced request, next to its `fields_present`
   (`actions/turn_on_for.py`, `set_attributes.py`, `move.py`).
3. **`core/scope.py`**: `drops: frozenset[str] = frozenset()`, which the default `Adapter.supports` subtracts
   before its scope check. **`core/models.py`**: `named` on `Target`. A
   `TargetNotSupported(ServiceNotSupported)` subclass in a new `core/errors.py` calls
   `ServiceValidationError.__init__` with our translation key and `{entity_id}`/`{reason}`, so it is still a
   core `ServiceNotSupported` for `isinstance` checks.
4. **Adapters**, wherever a refusal is really a lacked field:
   - `shelly/addressing.py:unsupported_reason`: a light field on a relay or component that can't take it
     becomes a drop, not `fields_not_supported`. A field outside the scope stays `fields_not_tested`.
   - `hue/set_attributes.py`: its `fields_not_supported` outcome (every field dropped) becomes `unchanged` with
     `fields_dropped`. Partial drops already return `sent` with `fields_dropped`.
   - Check each `unsupported`/`rejected` detail against the classes above, so every target-level reason comes
     from `supports()` (before anything is sent) and every device error comes from `execute`. Move any check
     that is in the wrong place.
5. **`strings.json`, `translations/en.json`**: add `target_not_supported`, `targets_failed`,
   `no_entities_matched`; remove `all_targets_failed`. Keep `no_targets` for an empty selection at the schema
   level.
6. **Docs**:
   - `docs/action-behavior.md`: the table becomes fact, the "slice 9f replaces" paragraph goes, the
     command-response bullet records that it stays, and add `fields_dropped` and the named/indirect rule.
   - `README.md` Results: drop "the action fails if every entity…" and say when it raises.
   - `docs/integrations.md`: Shelly's wrapper and relay-light notes now drop brightness rather than refusing it.
   - The repo plan's 9f row is marked done.
7. **Tests**
   - `tests/core/test_dispatcher.py`, covering:
     - named versus area and group;
     - raise before send;
     - partial device failure: everything runs, then the call raises;
     - state lack-drop and the request partitioning;
     - `drops`;
     - an untested field still refused;
     - unavailable skipped;
     - no targets returning or raising by response mode;
     - the command response leaving skipped targets out.
   - Adapter tests follow the changes in item 4, and tests that assert `all_targets_failed` are updated.
   - Rig steps:
     - `turn_on_for.yaml`'s two `expect_error: all_targets_failed` steps (`refuses_brightness_on_a_wrapper`,
       `refuses_brightness_on_a_relay_light`) become `drops_brightness_on_…`, with `expect_response`
       `status: expected` and `detail: fields_dropped`.
     - Any `expect_error` key that names an old translation is updated.
     - `tests/rig/engine.py` is checked for anything that reads `unsupported` entries out of a response.

## Critical files

- `custom_components/device_side/core/dispatcher.py`, `models.py`, `scope.py`, `adapter.py`; new
  `core/fields.py`, `core/errors.py`
- `custom_components/device_side/actions/{turn_on_for,set_attributes,move}.py` (`without`)
- `integrations/shelly/addressing.py`, `integrations/hue/set_attributes.py`, and any adapter item 4's review
  touches
- `strings.json`, `translations/en.json`, `docs/action-behavior.md`, `README.md`, `docs/integrations.md`
- `tests/core/test_dispatcher.py`, `tests/rig/steps/turn_on_for.yaml`
- Reuse: `core/groups.py:expand_ha_groups` (members become indirect), `core/resolver.py:resolve`,
  `Adapter.result`/`gather`; core's `async_extract_referenced_entity_ids`, `log_missing`,
  `brightness_supported`

## Verification

- `.venv/bin/pytest`, `pre-commit run --all-files`, and the coverage check CI runs.
- A rig run of the changed actions only, in the background. The Shelly wrapper and relay-light drop steps are
  the new hardware cases. Then call by hand on the live HA:
  - a named unsupported entity, which should raise `target_not_supported`;
  - an area holding one unsupported light, which should skip it and act on the rest;
  - `get_attributes` on an unavailable light alone, which should raise `no_entities_matched`.
- `/audit-code` on the diff before the PR, per CLAUDE.md.
