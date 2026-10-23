# See through `switch_as_x` wrappers

Agreed 2026-10-23. Implement in a fresh session; end with `/audit-code` by a fresh-context subagent
(P0/P1 fixed before commit), one commit on `release/v0.0.1`, `ci-green` before the next slice.

## Why

The first rig run (2026-10-23) found both of Jason's `light_onoff` entities are `switch_as_x` helpers
over Shelly switches, so `core/resolver.py` returns `no_platform`. Wrapping a relay as a light this way
is common. The wrapper forwards plain on/off to the wrapped switch, so the call that reaches the device
is the switch's call: by **proof follows the call**, the wrapped target rides the switch unit's proof.

## Decisions

- **Core, not per platform.** `resolve()` handles `entry.platform == "switch_as_x"` once, for every
  platform. It reads the wrapped entity from `entry.options["switch_as_x"]["entity_id"]` (seen on the
  live registry), resolves that entity with the normal path, and returns its Target. Each adapter
  still decides support for the wrapped switch through `supports()`.
- **Inverted wrappers are refused.** `options["switch_as_x"]["invert"]` true returns
  `"inverted_wrapper"` (a new reason key, with a translation).
- **Reported under the name the user used.** Target gains `via_wrapper: str | None` (the light's
  entity_id), like `via_group`. Responses and summaries key on the wrapper's entity_id, so a caller
  that targeted `light.x` gets `light.x` back.
- **Class is `switch`.** The adapter sees the wrapped `switch.*` target. Light fields sent to a wrapper
  are refused with `fields_not_supported` (the user addressed a light, so dropping them silently as
  `light_fields_ignored` would mislead). The UI already hides them: a wrapper light is `onoff`.
- **No chains.** A wrapper whose wrapped entity is itself a wrapper returns `"not_addressable"`.
- **Missing option.** No `switch_as_x` options, or the wrapped entity not in the registry, returns
  `"not_in_registry"` for the wrapped id.

## Tier

New capability, so the rig role and docs land with it. The adapters' `CellCapabilities` are
unchanged (no fingerprint reset): the call sent is the switch's. Note in `docs/platforms.md` and the
README that wrapped lights are served as their switch.

## Rig

- New role `light_wrapped` (a `switch_as_x` light over a supported switch); keep `light_onoff` for a
  device-native relay-as-light (Shelly: consumption type Light).
- `test_on_then_off_after_duration` adds `light_wrapped`, asserting on the wrapper's state.
- Tighten `test_unclaimed_brightness_on_a_light_raises`: assert the summary names
  `fields_not_supported`, not just `all_targets_failed`. It passed on 2026-10-23 for the wrong reason
  (`no_platform`).
- Jason's inventory: move both current `light_onoff` entries to `light_wrapped`.

## Tests

`tests/core/test_resolver.py`: wrapper resolves to the wrapped Shelly target with `via_wrapper` set;
inverted → `inverted_wrapper`; chain → `not_addressable`; missing options → `not_in_registry`.
A service-level test that the response keys on the wrapper id and light fields are refused.
