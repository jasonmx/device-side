# Align code terminology with the docs glossary

## Context

The code and docs use overlapping, overloaded words: "feature" for what HA calls an action, "platform" for both
the integration and the entity domain, "backing" (not an HA term) for the device-side unit, and "claims" for an
adapter's tested list, which reads as unproven. Jason settled a glossary over this session; this change makes the
code, rig, docs and CLAUDE.md use it. Do it **before the v0.0.1 rig run**: renaming the class and imports changes
the adapter AST, so both Shelly adapters reset to `untested` and need that run anyway.

## Glossary (goes in the repo plan; CLAUDE.md points to it)

- **Action**: what the user calls, e.g. `device_side.turn_on_for`.
- **Feature**: the user experience one or more actions deliver (a timed flip, smooth dimming). Prose only.
- **Integration**: the HA integration that is the first hop to the device (Shelly, ZHA, MQTT, Hue).
- **Bridge**: a separate system between the integration and the device, named only when the integration
  alone doesn't say how the device is reached (Zigbee2MQTT behind MQTT). The Hue Bridge is not counted.
- **Adapter**: one action on one integration (or bridge). Carries the tier.
- **Capability**: the device-side functional unit the adapter's call reaches, in vendor terms (Shelly
  component, Zigbee/Matter cluster, Z-Wave command class).
- **Field**: an action parameter, e.g. brightness.
- **Entity domain**: light, switch. "Domain" alone is fine where unambiguous.
- **Scope**: the entity domains, capabilities and fields an adapter is known to work with, on hardware someone
  has tested. Outside it, calls are refused as not yet tested.

"Platform" and "backing" are retired everywhere. `services.yaml` keeps its name (HA requires it).

## Renames

Work in worktree `wt/terminology` off `release/v0.0.1`. Pure rename plus the reason-key change; no behavior change.

| From | To |
|---|---|
| `features/` package, `core/feature.py` | `actions/`, `core/action.py` |
| `Adapter.feature` | `Adapter.action` |
| `platforms/` package | `integrations/` |
| `PlatformInfo`, `registry.platforms` | `IntegrationInfo`, `registry.integrations` |
| `PlatformInfo.ha_integration` | `IntegrationInfo.ha_domain` (the HA integration domain it matches) |
| `Adapter.platform`, `EntityResult.platform`, `Target.platform` | `.integration` |
| `core/capabilities.py`, `AdapterCapabilities` | `core/scope.py`, `AdapterScope` |
| `Adapter.capabilities` | `Adapter.scope` |
| `.components` / `.supports_fields` | `.capabilities` / `.fields` |
| `core/services.py` | `core/actions.py` |
| "backing", "claims", "claimed" in comments/docs | "capability", "scope", "in scope" |
| rig `--platform`, `inventory.platforms` | `--integration`, `inventory.integrations` |
| `docs/platforms.md`, `docs/bench/<platform>/<feature>.md` | `docs/integrations.md`, `docs/bench/<integration>/<action>.md` |

The settings (experimental, duration, confirmable, native_groups, max_concurrency, notes, bench) stay in
`AdapterScope`; no split. Known gap, not a task: editing them doesn't reset the fingerprint.

`IntegrationInfo.detect` (Z2M over plain MQTT) stays where it is; a `BridgeInfo` waits for the Z2M adapter.

**Response key change:** `EntityResult.platform` → `integration` changes the action response. Fine pre-release;
note it in the PR.

**Rig inventory:** ~~accept the old `platforms:` key with a deprecation warning~~. Dropped in implementation: the
inventory is keyed by integration at the top level (`shelly:`), with no `platforms:` key to migrate. Never copy or
edit the household `inventory.yaml`.

**Resolver reason:** `no_platform` became `integration_not_supported`.

**Left as historical:** the dated plans `2026-10-23-switch-as-x-wrappers.md` and `2026-10-24-parallel-sessions.md`,
and the bench records' fingerprint paths and test names, which record the run as it happened.

## Refusal reasons

Only refusals that mean "nobody has tested this yet" change; permanent ones keep `*_not_supported`.

- `core/adapter.py` `supports()`: domain outside scope → `domain_not_tested`; fields outside scope →
  `fields_not_tested`.
- `integrations/shelly/addressing.py` `unsupported_reason()`: capability outside scope → `capability_not_tested`.
  Fields the component can't take (`COMPONENT_FIELDS`) stay `fields_not_supported`.
- `core/dispatcher.py`: `domain_not_supported` (action never serves the domain) and the wrapper
  `fields_not_supported` stay.
- Update `docs/integrations.md` and the repo plan where they name these keys.

## Docs

- Repo plan `docs/plans/2026-10-23-device-side-repo-plan.md`: add the glossary; sweep terms; fix line ~487,
  which calls a capability "Shelly dimmer" (a device model).
- `CLAUDE.md`: tier section ("adapter (action × integration)", scope wording), Releases, Layout paths, one line
  pointing at the glossary. Deletion pass while there.
- `README.md` ("Supported platforms" → "Supported integrations"), `docs/contributing/testing.md`,
  `docs/plans/2026-10-23-hacs-early-release.md`, bench records (the "Backings" row → "Capabilities").
- Leave dated handoff docs (`docs/device_side_handoff-2026-10-23.md`) as historical.
- Save this plan as `docs/plans/2026-10-24-terminology.md`.

## Verification

1. `rg -n -i 'platform|backing|claim|feature'` across `custom_components/ tests/ scripts/ docs/ CLAUDE.md
   README.md`; each remaining hit is HA's own term (`supported_features`, `LightEntityFeature`), "feature" in the
   user-experience sense, or a historical doc.
2. `.venv/bin/pytest` and `pre-commit run --all-files`.
3. `scripts/rig.py --dry-run` against the household inventory (run planned).
4. PR into `release/v0.0.1`, `ci-green`, self-merge, remove the worktree.
5. Point Jason at a rig run: both Shelly adapters are now `untested` until it passes.
