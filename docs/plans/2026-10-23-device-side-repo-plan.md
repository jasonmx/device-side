# device_side: repository plan

Date: 2026-10-23. Working directory `/Users/jason/projects/device_side` (not yet a git repo).
Inputs: `docs/device_side_handoff-2026-10-23.md`, `../light-extras-research/` (demand mining),
`../hue-smooth-dimming/` (hue_dimmer v0.5.0, the code being ported).

## Context

Home Assistant's light and switch entity model leaves out features that the devices themselves
support: turn on then auto-off after N seconds, a default on-level, setting brightness or color
while off, hardware dimming ramps. Core maintainers decline them because they work on some
devices and not others; users then hand-roll `mqtt.publish` payloads and
`zha.issue_zigbee_cluster_command` calls. `device_side` takes the permissive side of that
tension: expose the feature through one action per feature across platforms, execute it on the
device or bridge so it survives HA restarts and outages, and document the sharp edges per
feature x platform adapter so users choose with open eyes.

Demand evidence (light-extras-research, 2023-10 to 2026-10, 248 relevant items): Turn On For
Duration scored 101.8 (12 requests, 2 refused, 11 workaround threads), Every-Turn-On Level 54.1,
Transition Control 41.6, Set Attributes While Off 32.6.

Platform shares, analytics.home-assistant.io 2026-10-22, of 561,214 installs reporting
integrations: mqtt 48.5%, matter 41.3%, zha 25.6%, shelly 25.3%, hue 15.9%. (Not in scope:
tuya 29.5%, esphome 27.3%, tplink 13.8%, zwave_js 8.3%, tasmota 7.6%.)

## Decisions from the interview (2026-10-23)

### Rationale and principles

- The repo exists for all four reasons: one action that works on a mixed room; execution on the
  device so it survives HA outages; filling gaps core will not; a permissive stance with
  documented sharp edges.
- **Inclusion test** (all must hold) for a feature:
  1. Once the command is sent, the behavior completes (or degrades to plain device behavior)
     with HA offline. No HA-side timers, polling or emulation.
  2. Native on platforms covering at least 20% of HA installs (the analytics shares above).
     Overlap between integrations is not published, so count the largest single-platform share
     as the lower bound. Shelly alone (25.3%) passes; a Hue-only (15.9%) or Z-Wave-only (8.3%)
     feature does not.
  3. Not already exposed by core *in a user-friendly way*. Primitives that exist but demand
     protocol knowledge (brightness_step 0 = stop, computing per-call transition times) count as
     unexposed.
  4. Documented user demand (as in light-extras-research). Contributions without evidence are
     accepted but not prioritized.
- **One action per user intent, not per protocol primitive.** Zigbee has move/step/moveto;
  device_side exposes one `move`. Command selection is hidden in the platform adapter.
- **Fallback policy: opt-in "assisted" only.** HA-side help is allowed only where it adds safety
  on top of a native mechanism (example: cancel a Hue bridge timer when the light is toggled
  early). Pure emulation is never shipped; docs show how to build it with `set_attributes` plus
  an automation.
- **Audience:** automation authors and dashboard users from v1. Actions for everything; entities
  only where a feature is a persistent setting, not a command.

### Scope

- **Platforms (v1):** Zigbee2MQTT via `mqtt`, ZHA, Matter, Shelly Gen2+, Hue v2. Hue is v1 for the
  hue_dimmer port only; Hue timed turn-on (bridge `behavior_instance`) and its assisted cancel
  hook are deferred.
- **Features (v1):**
  - `turn_on_for` on Z2M, ZHA, Matter, Shelly.
  - `turn_off_for` on Shelly only: it is Shelly-only natively (Zigbee/Matter `OnWithTimedOff` is
    on-then-off only; `off_wait_time` is a re-on guard). Other platforms return `unsupported`.
  - `toggle_for` dropped (2026-10-23): no use case. HA's `flash` covers a short toggle, and nobody
    needs a long one.
  - `turn_on_for` accepts `light.turn_on` fields (`brightness`, `color_temp_kelvin`, `hs_color`,
    `rgb_color`, `xy_color`, `transition`). Shelly sends one RPC; Zigbee/Matter send a normal
    turn_on then the timed command, and the result records the two-command path. **UI:** the
    frontend hides a field when no selected target matches its `filter`; `services.yaml` field
    filters support `supported_features` and `attribute` only (no domain filter,
    `helpers/service.py:_FIELD_SCHEMA`), so the light fields reuse `light/services.yaml`'s
    `attribute: supported_color_modes` filters verbatim. Switches have no
    `supported_color_modes`, so a switch-only selection shows just `duration`. The schema still
    accepts the fields for any target; adapters ignore fields their domain cannot use and the result
    records that under `detail`.
  - Hue port of hue_dimmer: `set_attributes`, `get_attributes`, `set_scene`, `move`/`stop`.
    `move` replaces raise/lower and grows beyond brightness. **Design principle (applies to
    every feature): fields describe what the light should do in human terms, never how the
    device does it.** No rates, steps, mireds or cluster vocabulary; the adapter converts.
    `move` fields, all optional but at least one direction required:
    - `brightness: brighter | dimmer`, `color_temp: warmer | cooler`,
      `saturation: richer | paler`, `hue: forward | backward` (around the color wheel,
      red → yellow → green …). One field per attribute, each with its own direction, so
      "brighter and cooler" is one call with no ambiguity. Directions use the words a person
      would say for that attribute; `up`/`down` is wrong for color temperature (Kelvin up is
      cooler, mireds up is warmer) and `increase`/`decrease` inherits the same ambiguity.
    - `sweep_time` (seconds; hue_dimmer's existing field): how long a **full-range sweep**
      takes, 0 → 100 % brightness, coolest → warmest of this light's range, 0 → 100 %
      saturation, 360° of hue. Speed is therefore constant whatever the start point, which is
      what hold-to-dim needs, and one number covers every attribute in the call. Default from
      hue_dimmer.
    - Limits in a collapsed "Limits" section (`services.yaml` sections): `brightness_limit`
      (%), `color_temp_limit` (K), `saturation_limit` (%). A limit is "stop here instead of
      the range end"; hue has no limit (it is a cycle).
    `stop` takes no fields and halts every move in flight on the target. A move that is
    already at its range end returns `confirmed` with `detail: at_limit`. (Per-attribute
    direction words and the reserved `hue` field confirmed by Jason, 2026-10-23.)
    Hue implementation: target = limit or range end, `dynamics.duration` = sweep_time ×
    fraction of range still to travel; brightness and color_temp each as one write;
    saturation as one `color.xy` write along the line toward the white point or the gamut
    edge (straight in xy, so native); `hue` is **unsupported on Hue** in v1 because a hue
    rotation is not a straight line in xy and chaining segments from HA would violate the
    offline rule. Zigbee Color Control Move Hue is native, so the field exists in the contract
    for that platform later. `stop` writes the interpolated current value for every attribute
    the transition cache holds for that light. Combined moves on Hue: verify on the rig
    whether per-attribute writes with separate durations run independently; if not, send one
    write with the longest duration and record `detail: shared_duration` (open item 12).
- **Deferred, architecture must accommodate:** `set_turn_on_defaults` (wraps existing ZHA/Matter number
  entities and Z2M `level_config`; no new entities), cross-platform `set_attributes`,
  cross-platform `move`/`stop`, Hue `turn_on_for` + assisted cancel, Shelly Gen1, further
  domains (cover, valve, lock), and one further platform: **Z-Wave JS**.
- **Z-Wave JS (post-v1, decided 2026-10-23):** scope is `move`/`stop` via Multilevel Switch CC
  Start/Stop Level Change (direction + duration), plus `set_turn_on_defaults` and auto-off only where a
  device exposes them as config parameters (Inovelli, Zooz, GE/Jasco). Binary Switch CC has no
  `OnWithTimedOff` equivalent, so `turn_on_for` is not a Z-Wave goal. Jason no longer owns
  Z-Wave hardware, so **reach out to Inovelli** (who showed interest in the timer feature in a
  thread mined by light-extras-research; see `research/timed-on-backends.md` there) to ask
  whether they will be the testers in the RC that carries the Z-Wave adapters.
- **Not planned (2026-10-23 check of local-only, non-Zigbee/Matter candidates):** Tuya (core
  integration is cloud, fails the offline test; its Zigbee devices already arrive via Z2M/ZHA),
  ESPHome (too experimental; auto-off is compiled into device YAML, no runtime primitive),
  Tasmota (small, declining share), TP-Link Kasa (local, has a countdown module, but waits for
  someone to ask). A request with evidence reopens any of these.
- **Naming convention (fixed now; it is a 0-to-1 decision):**
  1. `verb_object`, HA vocabulary only. Objects are the names HA's own services and state
     attributes use (`brightness`, `color_temp`, `attributes`, `scene`); protocol vocabulary
     (`level`, `OnLevel`, `PulseTime`, `toggle_after`) never appears in an action or field name.
  2. Commands (do something now) use HA's command verbs: `turn_on_for`, `turn_off_for`,
     `move`, `stop`, `set_attributes` (write HA light attributes to the device
     without turning it on), `get_attributes`, `set_scene`.
  3. Persistent settings (change how the device behaves from now on) use `set_<behavior>` with
     the trigger named in plain English. The former `set_on_level` becomes
     **`set_turn_on_defaults`**: fields `brightness` and `transition`, exactly the two things
     Zigbee/Matter Level Control let a device remember for a plain turn-on (`OnLevel`,
     `OnTransitionTime`; Z2M `level_config.on_level` / `on_transition_time`). Its future sibling
     for power-restore behavior (Zigbee/Matter `StartUp*`, Hue `powerup`, Shelly
     `initial_state`) is `set_power_on_defaults` with `state` plus the same light fields. Both
     read as "what the light defaults to when X happens", and "defaults" stays correct if more
     attributes are added, where `set_turn_on_brightness` would not. (Confirmed by Jason,
     2026-10-23.)
  4. Field names are the `light.turn_on` field names wherever one exists; a feature-specific
     field gets plain words (`duration`, `sweep_time`, `brightness_limit`).
  5. Field *values* are human terms for the outcome (`brighter`, `warmer`, a full-sweep time,
     a stop point), never device mechanics (a rate per second, a step count, a mired value).
     The adapter owns the conversion and documents it in `docs/platforms.md`.
  Domain `device_side`, UI title "Device Side", is final.
- **Groups: highest aggregation the device accepts.** Two kinds of group reach the dispatcher:
  - *HA group-platform entities* (light group helper, switch group, legacy `group.*`, later
    cover/fan). Nothing downstream can address them, so `core/groups.py` always expands them,
    for every domain, in one place. `Target.via_group` records the wrapper so an adapter can still
    batch members that came from the same group.
  - *Integration-native groups* (Hue `grouped_light`, Z2M group entities, ZHA group entities).
    These pass through to the adapter as a single target. Each adapter declares `native_groups`: when
    true the adapter sends one command to the group (hue_dimmer sends `move`/`stop` to
    `grouped_light`; Z2M `turn_on_for` can publish to the group topic). When false, the
    dispatcher calls the platform's `expand_group(hass, target) -> list[Target]` hook
    (`PlatformInfo.expand_group`; Hue uses `grouped_light.get_lights`, exactly what hue_dimmer
    does for `set_attributes`/`get_attributes` in `bridge.py`) and the adapter sees members. A
    platform with no hook and an adapter without `native_groups` returns `unsupported`
    (`group_not_supported`). Membership knowledge therefore lives in the platform (only it can
    know Hue or Z2M membership), but the call site is single and central.
  - Why central: one implementation and one test module for HA-group expansion instead of
    five; adapters never see a wrapper they cannot address; `via_group` lets an adapter re-batch when
    useful. Cost: the dispatcher must expand before bucketing, so an adapter cannot choose to
    address an HA group natively, which is fine because no device can. Goal throughout:
    minimize radio traffic and popcorning by sending to the largest unit the device accepts.
- **Results:** `SupportsResponse.OPTIONAL`. Response maps entity_id to
  `{status: unsupported|rejected|sent|confirmed, mode: native|assisted, platform, clamped_to?,
  detail?}`. Tier is not in the response: it is a subjective label about the code, not a fact
  about this call. Raise `HomeAssistantError` only on invalid input or when every target
  failed, so mixed rooms do not abort automations.
- **Stability tiers** per adapter (feature x platform): `experimental | untested | beta |
  stable`. Rules live in `CLAUDE.md` (Tiers, Releases); summary: only `experimental` is
  declared (`AdapterCapabilities.experimental`), the rest are computed by `gen_docs.py` from
  coverage and bench records keyed by the adapter's fingerprint; `stable` means on `main`. The
  claims carry the scope, so a tier covers everything the adapter claims: there is no runtime
  tier gate and no options flow for it, and a backing or field nobody has tested is simply not
  claimed in `components`/`supports_fields`, so `supports()` returns `unsupported`. Tier is not
  logged per call and not returned in results. Mode (`native | assisted`) is objective and
  stays in results.
- **Quality bar:** HA quality scale Gold conventions (config flow, translations, tests,
  diagnostics, docs).
- **Config:** single config entry, one confirm step, no options in v1. Services registered in
  `async_setup`, refusing calls until the entry loads (hue_dimmer pattern).
- **Testing, three layers:**
  1. Unit: `pytest-homeassistant-custom-component` for dispatch, group expansion, schemas and
     result shapes against a real `hass` fixture; platform calls mocked at the boundary
     (`mqtt.publish`, ZHA service, aioshelly RPC, `matter_client`, aiohue).
  2. **Rig: scripted integration tests against Jason's real HA instance**, the only way to
     scale verification across many feature x platform adapters. Tests are marked
     `@pytest.mark.rig`, skipped by default, and talk to HA over its WebSocket/REST API with a
     long-lived token: call `device_side.*` actions, assert on service responses and on
     state changes (e.g. the light is off N seconds after `turn_on_for`). A rig inventory file
     (gitignored, `tests/rig/inventory.yaml`) maps each platform to the household entities to
     use; tests restore prior state afterwards. A deploy script installs the pushed branch's
     `custom_components/device_side` through pi-stack's `ha-shim` (`ssh ha ds-sync`; the agent key
     cannot rsync) and restarts HA (`ssh ha restart`) before the run.
     **Human approval gate:** the rig runner (`scripts/rig.py`) prints the inventory, the
     adapters to be exercised, the estimated duration and whether a restart is needed, then
     requires an interactive y/N (and a `DEVICE_SIDE_RIG_APPROVED=1` env var for CI-style
     invocation). Both the deploy+restart and the test run sit behind that gate. The devices
     are in-use household lights, so **Claude must ask before invoking the rig, every time**;
     the gate exists so occupants are not startled by devices changing state.
  3. Bench: a per-adapter record (`docs/bench/<platform>/<feature>.md`) of the rig pass that
     promoted an adapter, with date, HA version, device model and firmware. Rig test results feed
     this record. **There is no dev HA; the live rig is the only HA.** The first time the
     integration loads in a real HA is the first approved rig deploy (slice 3); until then
     correctness rests on unit tests plus hassfest.
- **Docs:** README is the front door (pitch, install, quick start, generated support matrix,
  links). Start with a single `docs/platforms.md`, one section per platform on a fixed template
  (what it talks to, how targets resolve, per-feature notes, sharp edges, generated capability
  block). `docs/features/<feature>.md` per feature. `docs/contributing/add-a-feature.md`,
  `add-a-platform.md`, `rig.md`. MkDocs-ready layout, no site in v1; `platforms.md` splits into
  per-platform pages only if it outgrows one file.
- **Repo:** private until v0.0.1 ships (slice 5), then public with contributor docs. MIT. American English in
  all user-facing text (matches HA).
- **Versions:** minimum HA set to a release within the last six months (2026.x) so no compat
  shims; tests pin current stable; Python 3.14 in CI; copy ruff, pre-commit, codespell,
  gitleaks, hassfest and HACS validate workflows from hue_dimmer. Releases go `v0.0.x` while
  building; `v0.1.0` once this plan is feature complete and third-party testers have validated
  the hardware the rig lacks.
- **hue_dimmer:** deprecated with a migration guide, but only after device_side is
  feature-complete and stable, to spare existing Hue users regressions and churn.

- **GitHub:** `jasonmx/device-side` (kebab-case like `jasonmx/hue-smooth-dimming`; both `device_side`
  and `ha-device-side` were free on 2026-10-23).

## Architecture

Load-bearing facts read from HA core 2026.2.1 (hue_dimmer venv) during planning:

- `helpers/group.py:expand_entity_ids` only expands `group.*` ids. A `light.*` group made by the
  group integration is **not** expanded by `async_extract_entity_ids`; we expand it ourselves via
  `helpers.group.get_entity_ids`, which reads the `entity_id` state attribute (`group/light.py`).
- `zha.issue_zigbee_cluster_command` is registered with `async_register_admin_service`
  (`zha/websocket_api.py`), so the ZHA adapter forwards the original `call.context`.
- `strings.json` `services` block and `icons.json` `services` block formats verified against
  `components/matter/`. `get_matter(hass)` reads `hass.data[matter.DOMAIN]` (one entry).
  `ShellyEntryData.rpc` on `entry.runtime_data` (`shelly/coordinator.py`). `HueBridge` is
  `entry.runtime_data`; `bridge.api` is `HueBridgeV2`.
- Re-read against 2026.10.2 in slice 1: validators are `probatio` (voluptuous fork), so schemas import
  `probatio` and reuse `light.const.LIGHT_TURN_ON_SCHEMA` entries verbatim (`brightness` is 0-255 as in
  `light.turn_on`); `async_extract_entity_ids(call, expand_group)` is a coroutine; `helpers/group.py` gained a
  group-entity registry (`GenericGroup`) that no component uses yet, so group helpers still need our expansion.

### Directory layout

Top level of `custom_components/device_side/` holds only the fixed HA files and three
subpackages: HA auto-imports top-level modules named after entity platforms and after
`group`, `diagnostics`, `repairs`, `trigger`, `device_trigger` etc., so platform adapters live
under `platforms/` and nothing is called `light.py`.

```
custom_components/device_side/
  __init__.py            async_setup: registry discovery in import executor, register services;
                         async_setup_entry/unload no-op; CONFIG_SCHEMA = config_entry_only_config_schema
  manifest.json          domain device_side; config_flow; single_config_entry;
                         after_dependencies [mqtt, zha, matter, shelly, hue]; requirements [];
                         integration_type service; iot_class local_push
  config_flow.py         single-instance empty flow (copy of hue_dimmer/config_flow.py)
  const.py               DOMAIN, NAME, LIGHT_FIELDS
  services.yaml          static: target filters + field selectors only (names/descriptions in strings)
  strings.json           title/config/exceptions + one "services.<feature>" block per feature
  icons.json             "services": {<feature>: {"service": "mdi:..."}}
  translations/en.json   copy of strings.json
  core/
    models.py            Status, Mode, Tier, FeatureKind, Target, EntityResult, LightFields + validators
    capabilities.py      DurationLimits, AdapterCapabilities, PlatformInfo
    feature.py           Feature[RequestT] base class
    adapter.py              Adapter[RequestT] base class + gather() pacing helper
    registry.py          AdapterRegistry: pkgutil discovery, guarded import, lookup, matrix iteration
    resolver.py          entity_id -> Target (platform key via PlatformInfo.ha_integration + detect)
    groups.py            expand HA group-platform entities (any domain) to members; call platform expand_group
                         for native groups when the chosen adapter lacks native_groups
    duration.py          clamp(request, limits) -> (request, clamped_to)
    dispatcher.py        parse, extract, expand, resolve, run adapters, merge, raise rule, response
    services.py          register one service per Feature; _call_if_loaded gate (hue_dimmer pattern)
    runtime.py           DeviceSideData in hass.data[DOMAIN]: registry, dispatcher, semaphores, platform_state
  features/
    __init__.py          discover() -> features sorted by module name
    turn_on_for.py  turn_off_for.py                         (COMMAND)
    set_attributes.py  set_scene.py  move.py  stop.py        (COMMAND, Hue port)
    get_attributes.py                                         (QUERY, SupportsResponse.ONLY)
  platforms/
    __init__.py          discover() -> modules sorted; each exports PLATFORM and ADAPTERS
    zigbee2mqtt/  __init__.py detect.py addressing.py turn_on_for.py
    zha/          __init__.py addressing.py turn_on_for.py
    matter/       __init__.py addressing.py turn_on_for.py
    shelly/       __init__.py addressing.py turn_on_for.py turn_off_for.py
    hue/          __init__.py bridge.py transition_cache.py colors.py
                  set_attributes.py get_attributes.py set_scene.py move.py stop.py
scripts/
  gen_docs.py            matrix + per-page generated blocks from the registry; --check for CI
  deploy.sh              ssh ha ds-sync <branch>, then ssh ha restart homeassistant (rig only)
  rig.py                 approval gate (inventory, adapters, duration, restart?) -> y/N -> deploy -> pytest -m rig
docs/
  device_side_handoff-2026-10-23.md          existing
  plans/2026-10-23-device-side-repo-plan.md  this plan, saved in slice 0
  matrix.md  matrix.yaml                     GENERATED
  _notes.yaml                                note key -> Markdown footnote text
  features/<feature>.md  platforms.md               fixed templates with <!-- generated:start/end --> blocks
                                             (platforms.md: one section + one block per platform)
  contributing/add-a-feature.md  add-a-platform.md  bench-checklist-template.md  rig.md
  bench/<platform>/<feature>.md              per-adapter bench record; gates tier promotion
tests/
  conftest.py            enable_custom_integrations autouse; setup_integration; fake_registry; call()
  fakes/fake_platform/   PLATFORM "fake" + scripted adapters for dispatcher tests
  fixtures/{z2m,zha,matter,shelly,hue,groups}.py   fabricate registry entries + boundary mocks
  core/   features/   platforms/<p>/   docs/        one module per adapter; see Testing
  rig/    conftest.py (HA WS/REST client, inventory loader, snapshot/restore), inventory.yaml (gitignored),
          inventory.example.yaml, test_<feature>_<platform>.py
```

Repo root: README.md (matrix between `<!-- matrix:start/end -->`), hacs.json, pyproject.toml,
.pre-commit-config.yaml, requirements_test.txt, `.github/workflows/{lint,tests,hassfest,validate}.yml`
copied from `/Users/jason/projects/hue-smooth-dimming`, plus `docs.yml` running
`scripts/gen_docs.py --check`.

### Core contract

```python
# core/models.py
class Status(StrEnum): UNSUPPORTED, REJECTED, SENT, CONFIRMED
class Mode(StrEnum): NATIVE, ASSISTED
class Tier(StrEnum): STABLE, BETA, UNTESTED, EXPERIMENTAL   # computed by gen_docs, never stored on an adapter
class FeatureKind(StrEnum): COMMAND, SETTING, QUERY

@dataclass(frozen=True, slots=True)
class LightFields:  # brightness, color_temp_kelvin, hs_color, rgb_color, xy_color, transition
    def present(self) -> frozenset[str]; def as_turn_on_data(self) -> dict

@dataclass(frozen=True, slots=True)
class Target: entity_id, domain, platform, entry: er.RegistryEntry, device, config_entry, state, via_group

@dataclass(slots=True)
class EntityResult: entity_id, status, platform, mode, clamped_to, detail, data
    def as_response(self) -> dict   # drops None; data under "attributes"; no tier

# core/capabilities.py
@dataclass(frozen=True) class DurationLimits: min_s, max_s
@dataclass(frozen=True) class AdapterCapabilities:
    experimental: bool = False; mode = NATIVE; domains = {"light"}; duration: DurationLimits | None
    supports_fields: frozenset[str]; confirmable: bool; native_groups: bool
    max_concurrency: int = 4; notes: tuple[str, ...] = (); bench: str | None = None
@dataclass class PlatformInfo:
    key, title, ha_integration, detect: Callable[[hass, entry, device], bool] | None
    is_group: Callable[[hass, Target], bool] | None             # flags a native group (resolver sets Target.is_group)
    expand_group: Callable[[hass, Target], list[Target]] | None   # native-group members; None = cannot
    max_concurrency: int; available: bool = True; unavailable_reason: str | None

# core/feature.py
class Feature[RequestT](ABC):
    key: ClassVar[str]; kind: ClassVar[FeatureKind]; domains: ClassVar[frozenset[str]]
    supports_response: ClassVar[SupportsResponse] = OPTIONAL
    fields: ClassVar[dict[vol.Marker, Any]]            # merged into cv.make_entity_service_schema
    @classmethod def schema(cls) -> vol.Schema
    @classmethod @abstractmethod def parse(cls, hass, call) -> RequestT   # ServiceValidationError on bad input
    @classmethod async def run(cls, hass, request, targets, dispatcher) -> list[EntityResult]:
        return await dispatcher.run_adapters(cls.key, request, targets)      # overridable

# core/adapter.py
class Adapter[RequestT](ABC):
    feature: ClassVar[str]; platform: ClassVar[str]; capabilities: ClassVar[AdapterCapabilities]
    def supports(self, hass, request, target) -> str | None  # None = ok, else reason key; sync, cheap; request so unclaimed fields refuse
    @abstractmethod async def execute(self, hass, request, targets) -> list[EntityResult]
    def result(self, target, status, **kw) -> EntityResult  # stamps platform/mode
    async def gather(self, hass, targets, send) -> list[EntityResult]  # platform + per-adapter semaphores; exc -> that target REJECTED
```

- **Registry:** `pkgutil.iter_modules` over `platforms/` and `features/`; each package exports
  data (`PLATFORM`, `ADAPTERS`, `FEATURE`), not decorators, so import has no side effects, order is
  deterministic (sorted), the docs generator can import without `hass`, and tests can build a
  registry from an explicit module list. Each platform import is guarded: a failing import
  (library absent because the core integration is not installed) records
  `PlatformInfo(available=False, unavailable_reason=...)` and setup continues. Discovery runs via
  `hass.async_add_import_executor_job`.
- **Resolver:** candidates = available platforms whose `ha_integration == entry.platform`;
  platforms with a `detect` hook win first (Z2M: a `("mqtt", "zigbee2mqtt_*")` device identifier
  [M]); then the generic one. Matter-paired Hue bulbs resolve to `matter` naturally. Unresolved
  reasons: `not_in_registry`, `no_platform`, `integration_not_loaded`.
- **Groups:** `core/groups.py:expand_ha_groups` recurses only through entities whose registry
  platform is `group` (via `get_entity_ids`), any domain, max depth 4, dedupe preserving order,
  `via_group` set on members. Native groups (Hue `grouped_light`, Z2M/ZHA group entities) pass
  through as one target; after bucketing, `expand_native_groups` replaces each native-group
  target in a bucket whose adapter lacks `native_groups` with the platform's `expand_group` output
  (or an `unsupported` result when the platform has no hook). Results for expanded members are
  reported per member; the wrapper itself gets no row.
- **Dispatcher:** `handle(feature, call)`: parse, `async_extract_entity_ids`, expand HA groups,
  resolve, domain filter, `feature.run`, append `unsupported` for unresolved, total-failure
  check, build response when `call.return_response`. `run_adapters` buckets targets by adapter (no
  adapter -> `no_adapter`; domain mismatch; `supports()` reason), expands native groups per bucket as
  above, then runs adapters concurrently under `asyncio.timeout(30)`; adapter exceptions become
  `REJECTED` for every target; `reconcile` ensures exactly one result per target;
  `duration.apply` clamps before the adapter sees the request and stamps `clamped_to`. Total
  failure (every result unsupported/rejected) raises
  `HomeAssistantError(translation_key="all_targets_failed")` with a per-entity summary; no
  targets raises `ServiceValidationError("no_targets")`.
- **Setting-class features** (future `set_turn_on_defaults`): same `Feature`/`Adapter` contract
  with `kind=SETTING`; ZHA/Matter adapters locate the sibling `number` entities on `target.device`
  (Matter sets `translation_key="on_level"`; transition time likewise), call `number.set_value`
  blocking, read back -> `CONFIRMED`; Z2M publishes `level_config` -> `SENT`. `kind` only
  drives docs grouping.
- **Query features** (`get_attributes`): payload in `EntityResult.data`, `supports_response=ONLY`.
- **Services:** one `hass.services.async_register(DOMAIN, feature.key, ...)` per discovered
  feature in `async_setup`; `_call_if_loaded` raises `ServiceValidationError("not_loaded")` until
  the entry is loaded.

### Platform routes for turn_on_for

- **Zigbee2MQTT:** ieee from device identifier; topic from the live MQTT entity's
  `command_topic` (via `hass.data["entity_components"]["light"].get_entity`, semi-internal [I]),
  fallback `zigbee2mqtt/<ieee>/set`. If fields present: `light.turn_on` first (blocking), then
  `mqtt.publish` `{"state":"ON","on_time":<s, 1dp>}`. Returns `SENT` (fire-and-forget). Limits
  0.1 to 6553.4 s. Tuya `countdown` devices are a documented v1 gap.
- **ZHA:** ieee from `("zha", ieee)` identifier; endpoint from unique_id `"{ieee}-{endpoint}"`
  [M]. Optional `light.turn_on`, then `zha.issue_zigbee_cluster_command` cluster 0x0006 cmd 0x42
  params `{on_off_control:0, on_time:tenths, off_wait_time:0}`, `context=call.context`. Exception
  -> `REJECTED`, else `SENT`; read-back of OnTime (0x4001) later for `CONFIRMED`.
- **Matter:** `get_node_from_device_entry(hass, device)` (`matter/helpers.py`); endpoint parsed
  from the right of unique_id `{node_device_id}-{endpoint}-{key}-{cluster}-{attr}` (`parts[-4]`).
  `supports()` requires the OnOff FeatureMap Lighting bit else `no_lt_feature`. Optional
  `light.turn_on`, then `matter_client.send_device_command(node_id, endpoint_id,
  OnOff.Commands.OnWithTimedOff(onOffControl=0, onTime=tenths, offWaitTime=0))`; optional
  `read_attribute` OnTime -> `CONFIRMED`. `switch` domain (plugs) unclaimed until the plug question is settled.
- **Shelly Gen2+:** `entry.runtime_data.rpc` (`None` -> `gen1_unsupported`); component and id from
  unique_id `{mac}-{light|rgb|rgbw|cct|switch}:{n}`; one `call_rpc("<Component>.Set",
  {id, on: True, toggle_after: s, **fields})` with field translation copied from `shelly/light.py`;
  `GetStatus` read-back -> `CONFIRMED`. `turn_off_for` is the same with `on: False`.
- **Hue port** (hue_dimmer module -> adapter): `bridge.py` resolve/controllers/writes ->
  `platforms/hue/bridge.py` taking a `Target` (drop `_iter_targets`; `_write_light` raises so the
  adapter emits SENT/REJECTED); `transitions.py` `_brightness_cache` -> `TransitionCache` instance in
  `runtime.platform_state["hue"]`, keyed by (resource_id, attribute) so brightness, color_temp,
  and saturation moves are tracked alike (start value, target, duration, started_at;
  interpolate on read); `_start_transition` -> `move.py` (per-attribute direction + sweep_time
  + limits; raise/lower partials go; color_temp writes `color_temperature.mirek`, saturation
  computes the xy end point via `colors.py`; `hue` -> `unsupported`); `_stop_transition` ->
  `stop.py` (all attributes in the cache for the light);
  `attributes.py` -> `colors.py`;
  `_handle_set_attributes` -> `set_attributes.py` ("nothing to set" becomes a
  `ServiceValidationError` in `parse`); `_handle_get_attributes` -> `get_attributes.py` (payload in
  `data`); `scenes.py` -> `set_scene.py` (smart-scene/not-found warnings become results).
  `api_version < 2` -> `supports()` returns `bridge_v1`.

### Concurrency

Platform semaphore from `PlatformInfo.max_concurrency` (Hue 2 because aiohue's cap of 3 is shared
with core; ZHA 2; Matter 2; Shelly 4; Z2M 4) plus a per-adapter semaphore from
`AdapterCapabilities.max_concurrency`, both applied inside `Adapter.gather()`. `execute` receives all
of an adapter's targets at once so native group commands stay possible. Hue `move`/`stop` keep the
"cache only after accept" rule.

### services.yaml, strings, icons

- `services.yaml` holds only `target` and `fields` with selectors. One filter dict per platform
  (`integration` is a single string): `{domain: [light, switch], integration: mqtt}` and so on for
  zha, matter, shelly; Hue-only features `{domain: light, integration: hue}`; `set_scene`
  `{domain: scene, integration: hue}`. Filters are UI-only; adapters enforce via `supports()`.
- `strings.json`: `services.<feature>.{name, description, fields.<field>.{name, description}}`
  plus `exceptions.{not_loaded, no_targets, all_targets_failed, invalid_duration, nothing_to_set}`.
- Adding a feature = one block each in `services.yaml`, `strings.json`, `icons.json`.
  `tests/core/test_services_setup.py` asserts all three exist for every discovered feature and
  every schema field has a strings entry.

### Docs generation

`scripts/gen_docs.py` imports the registry without `hass`, emits `docs/matrix.yaml` (machine
readable: per-adapter tier, fingerprint, mode, domains, duration, supports_fields, confirmable, native_groups, notes,
bench) and `docs/matrix.md`, and rewrites the generated block in README, in each
`docs/features/*.md`, and in each platform section of `docs/platforms.md` (one marker pair per
section, `<!-- generated:<platform>:start/end -->`). Matrix adapter text: `tier · best status · duration
range` with footnotes from `docs/_notes.yaml`. The generator fails on a missing or unused note
key, a `bench` path that does not exist, or a non-experimental adapter under 95% coverage
(`coverage.json`). CI runs `--check`. Fingerprint: AST hash of the adapter module, excluding
docstrings and the `AdapterCapabilities` declaration; bench records carry the fingerprint they
tested and list the backings (Shelly: RPC components) and light fields they exercised. Proof
follows the call: a record proves the device-side call, whatever HA domain the target shows, so a
relay exposed as a `switch` or as an on/off `light` rides one record. `beta` needs every claimed
component and field covered by a record with the current fingerprint; the generator fails on a
claim no such record covers. Untested backings are left out of `AdapterCapabilities.components` and
refused, not claimed on a sibling's proof. Adding a backing after a tester report is a claims edit
plus a record listing it; the fingerprint, and so the existing records, survive it. Tier ladder: see `CLAUDE.md`. A release-workflow check rejects tags not matching
`^v\d+\.\d+\.\d+(rc\d+)?$`.

Tester reports: RC builds raise one fixable Repairs issue ("vX.Y.ZrcN: help test on your
hardware"). Its repair flow multi-selects the RC's requested tests (each a feature x platform x
backing, labelled in device terms, e.g. "Shelly dimmer") that match the user's own entities; each
chosen test becomes a non-fixable Repairs issue ("Test wanted: <platform> · <device label>") whose
`learn_more_url` opens the `test-report.yml` GitHub issue form prefilled (text fields only) with
RC, HA version, feature, backing, device model, firmware (`sw_version`) and a per-test
checklist. The form says: "Already tested by someone else? Still worth sending: a different model
or firmware is new evidence." The requested tests are fixed per RC (no runtime
fetch); duplicate reports are welcome. New RCs clear and recompute these issues. Passing
reports become bench records citing the issue.

## Testing

### Unit (CI)

`pytest-homeassistant-custom-component` fixtures: `hass`, `enable_custom_integrations` (autouse),
`entity_registry`, `device_registry`; helpers `MockConfigEntry`, `async_mock_service`. Fabrication
helpers in `tests/fixtures/` all follow one shape: `MockConfigEntry(domain=<integration>)` added
to hass (state patched LOADED), `device_registry.async_get_or_create(identifiers=...)`,
`entity_registry.async_get_or_create(domain, platform, unique_id, device_id, config_entry_id)`,
`hass.states.async_set(...)`.

- Z2M: platform `mqtt`, identifier `("mqtt", "zigbee2mqtt_0x00124b0012345678")`; boundary
  `async_mock_service("mqtt","publish")` and `("light","turn_on")`.
- ZHA: platform `zha`, identifier `("zha", ieee)`, unique_id `"{ieee}-1"`; boundary
  `async_mock_service("zha","issue_zigbee_cluster_command")`; plug variant on `switch`.
- Matter: platform `matter`; monkeypatch `get_node_from_device_entry` and `get_matter` to mocks
  with `send_device_command = AsyncMock()` and a FeatureMap toggled per test.
- Shelly: unique_id `"AABBCCDDEEFF-light:0"`, `entry.runtime_data = SimpleNamespace(rpc=...)` with
  `call_rpc=AsyncMock`; Gen1 variant `rpc=None`.
- Hue: `entry.runtime_data = mock_bridge` reused from hue_dimmer's conftest; `is_hue_group` attr
  for grouped_light; scene entity.
- Groups: `make_light_group(hass, "light.kitchen", members)` on platform `group`.

One test module per adapter under `tests/platforms/<p>/test_<feature>.py` asserting the exact
response dict and boundary call arguments; `tests/core/` (registry, resolver, groups, dispatcher,
services_setup) use only `tests/fakes/fake_platform`; `tests/docs/test_matrix_generated.py`
regenerates into the scratch dir and diffs against committed output.

### Rig (approval-gated, real HA)

`scripts/rig.py` loads `tests/rig/inventory.yaml` (gitignored; `inventory.example.yaml` committed)
mapping each platform to household entities, prints inventory, the adapters about to run, estimated
duration and whether a restart is needed, then requires interactive y/N (or
`DEVICE_SIDE_RIG_APPROVED=1`). `scripts/rig.py` flow:

1. Read-only preflight: load inventory and `.env.rig` (`HA_URL`, `HA_TOKEN` for a non-admin user,
   `RIG_SSH` default `ha`); `AdapterRegistry.discover()` (no hass) intersected with inventory
   platforms -> one line per adapter (`shelly / turn_on_for -> light.office_strip (beta)`); sum each
   test's `RIG_SECONDS` for the estimate; compare `HEAD:custom_components/device_side` with
   `ssh ha ds-status` to decide whether a deploy+restart is needed, and refuse a deploy unless
   `origin/<branch>` carries that tree. Nothing mutates before the gate.
2. Gate: print the plan, `Proceed? [y/N]`. `--dry-run` stops here.
3. `scripts/deploy.sh`: `ssh ha ds-sync <branch>` (pi-stack verb: fetch into a device-side clone on
   the Pi, replace the integration dir inside the container), `ssh ha restart homeassistant`; poll
   `/api/config` until `RUNNING`, then wait for `device_side.turn_on_for` in `/api/services` (hard
   fail at 180 s).
4. `pytest <modules> --confcutdir tests/rig -p no:homeassistant -p no:cacheprovider` with
   `DEVICE_SIDE_RIG=1 DEVICE_SIDE_RIG_APPROVED=1`. Flags: `--no-deploy`, `--no-restart`,
   `--platform <key>`, `-k`.

Rig fixtures (`tests/rig/conftest.py`): session `inventory` (skips the session when
`inventory.yaml` is absent), per-test `ha` (`HAClient` in `tests/rig/client.py`: WS `call_service`
with `return_response`, REST state reads, `wait_for(entity_id, predicate, timeout)` on
`state_changed`; restart and readiness live in the runner), `snapshot` (captures state + brightness/CT/color, tracks touched entities,
restores on teardown via `light.turn_on/off`, logs rather than fails on mismatch; Hue tests capture
via `device_side.get_attributes` so off-light attributes restore), `timing` (per-platform
tolerance: Zigbee/Matter 3 s, Shelly/Hue 2 s), `require_adapter(platform, feature, role)` (skip when
inventory lacks the role or the registry lacks the adapter). Timing assertions are windows: still on
at `duration - tol`, off by `duration + tol`. Rig durations are 5 to 8 s; `clamped_to` is checked
via the response only. Rig tests cover one happy path and one `unsupported` path per adapter;
branches stay in unit tests. Unit runs never import rig fixtures (`DEVICE_SIDE_RIG=1` gates
collection; the fixtures skip everything without `DEVICE_SIDE_RIG_APPROVED=1`; `rig` marker
registered in pyproject).

`.gitignore`: `tests/rig/inventory.yaml`, `.env.rig` (example at `tests/rig/env.example`).
`docs/contributing/rig.md` covers the shim deploy path, token creation, inventory format (per
platform -> entities with role tags `light_dimmable`, `light_ct`, `light_color`, `switch_plug`,
`group`, `scene`), the first-load checklist and safety notes. **Claude asks before every rig run; the devices
are in-use household lights.** Rig passes are recorded in `docs/bench/<platform>/<feature>.md`
(date, HA version, device model, firmware, fingerprint, source: rig run or test-report issue).

## Delivery sequence

| # | Slice | Done when |
|---|---|---|
| 0 | Scaffold + CI | Plan saved to `docs/plans/`; `git init`, private GitHub repo `jasonmx/device-side`; manifest, config_flow, const, strings, icons, empty services.yaml; pyproject, pre-commit, workflows from hue_dimmer; `test_services_setup.py` green with zero features; hassfest + HACS validate green; README skeleton with matrix markers. |
| 1 | Core + fake platform | `core/*`; `features/turn_on_for.py`, `turn_off_for.py`; fake platform (with a fake native group and `expand_group` hook); dispatcher/resolver/groups tests green (HA-group expansion for light and switch, native-group pass-through vs expansion, clamp, total-failure raise, response shape, semaphore bound, guarded-import skip). No live load yet: there is no dev HA. |
| 2 | Shelly `turn_on_for` + `turn_off_for` | one RPC with fields; Gen1 -> unsupported; read-back -> confirmed under mock; Shelly section of `docs/platforms.md` on the template; adapter `experimental=True`. |
| 3 | Rig harness | `scripts/rig.py`, `deploy.sh`, `tests/rig/conftest.py`, inventory example, `docs/contributing/rig.md`; **first approved deploy is the integration's first load in any HA**: confirm entry adds, actions appear with translated names, the brightness fields hide for a switch-only selection; then Shelly `turn_on_for` passes against the house; bench record written; Shelly `switch` and on/off `light` -> beta (shared on/off: a relay shown as a light sends the same `Switch.Set`); Shelly light fields and the `Light`/`CCT`/`RGB*` components unclaimed until a tester reports. |
| 4 | `turn_off_for` rig pass | rig test for `turn_off_for`; bench records written, so both Shelly features reach beta. (`toggle_for` was dropped.) |
| 5 | First release (`v0.0.1`) + HACS submission | Detail in `2026-10-23-hacs-early-release.md`. Claims Shelly `switch` and on/off `light` (shared on/off) for `turn_on_for` and `turn_off_for`. MIT `LICENSE`; `custom_components/device_side/brand/icon.png` (+ `@2x`); hand-written bench records and README matrix (inside the matrix markers, taken over by `gen_docs.py` later); README install via HACS custom repository; short `CONTRIBUTING.md`; full-history `gitleaks detect` clean; topics added; repo flipped public; `gh workflow enable validate.yml`, nightly schedule restored and private-repo guard removed; PR `release/v0.0.1` -> `main`, `ci-green` on `main` with hassfest + HACS validate green; tag `v0.0.1` and a full (not pre-) GitHub release; PR to `hacs/default` adding `jasonmx/device-side` to `integration`, from a personal fork; issue filed to switch the README install section to a plain HACS search once that PR merges (review takes months); `release/v0.0.2` cut from `main`. **v0.0.1 ships without an RC soak to start the HACS review clock; from v0.0.2 the Releases rules apply in full.** |
| 6 | Z2M `turn_on_for` | detect, addressing, publish; `light.turn_on` precedes when fields present; group topic when `native_groups`; rig test. |
| 7 | Hue port | five adapters + bridge/transition_cache/colors; `move` across brightness, color_temp, hue, saturation; `grouped_light` native for move/stop, expanded for set/get_attributes; hue_dimmer tests ported to real-hass fixtures; rig parity with hue_dimmer `tests/RELEASE_CHECKLIST.md`. |
| 8 | Docs generator + templates | `gen_docs.py --check` in CI; matrix, README block, feature pages, `platforms.md` sections; `_notes.yaml`; contributing guides. Lands before the first v0.0.2 RC. |
| 9 | Bench + tiers + tester flow | fingerprinting and computed tiers in `gen_docs.py`, including the claims-coverage check; per-adapter coverage check; tag-format check; RC audit gate (`2026-10-23-rc-audit-gate.md`: `cut-rc` workflow, `check_audit.py`, `/rc-audit`); `test-report.yml` issue form; RC-only umbrella Repairs issue with multi-select flow and prefilled per-test links; bench files filled from rig runs and tester reports. Lands before the first v0.0.2 RC, which is the project's first RC. |
| 10 | ZHA `turn_on_for` | after Jason has ZHA running on the rig; addressing; admin context passthrough; ValueError -> rejected; rig test. |
| 11 | Matter `turn_on_for` | after Jason has Matter running on the rig; LT check; `OnWithTimedOff`; optional read-back; rig test on bulb and plug. |
| 12 | `v0.1.0` ("v1" names the scope, not the version) | feature complete for this plan; third-party tester reports for the hardware the rig lacks; matrix current; release checklist adapted from hue_dimmer. |

`v0.0.x` releases are cut between slices whenever a set of adapters reaches beta; one release may carry
several platforms or features.

Each slice ends with `/audit-code` on its diff (everything since the previous slice's audit, plus any
sibling-repo changes it needed), run by a fresh subagent that gets the code and no conclusions from the
building session. P0/P1 findings are fixed before the slice's commit; the rest are fixed or filed as issues.
The first audit, at the end of slice 3, covers the whole repo, since nothing before it was reviewed.
Each slice is a commit (or a few) pushed to the current `release/vX.Y.Z` branch, CI green (`ci-green`) before the next slice starts; no per-slice PRs, and each release's merge to `main` is its only PR. Rule evidence that would have gone in a PR body points at a commit sha or this plan instead. Implementation starts in a **fresh session** per the planning rule;
the first action of that session is slice 0.

## Open items to verify during implementation (not before)

1. Matter: `get_matter(hass)` stability across 2026.x; `matter_server.client.models.clusters`
   importable without the integration loaded; which device types carry OnOff `LT` (plugs?);
   endpoint parsing from unique_id vs iterating `node.endpoints`.
2. Shelly: `RpcDevice.call_rpc` signature at the pinned aioshelly; `toggle_after` type/unit and
   limits; `GetStatus` timer field names; `Switch.Set toggle_after` [M]; how `_id` derives from key.
3. ZHA: does `issue_zigbee_cluster_command` raise on NAK or time out silently; zigpy param names
   for OnWithTimedOff; unique_id endpoint format; admin refusal path.
4. Z2M: `zigbee2mqtt_` identifier prefix [M]; IEEE as topic segment [M]; `command_topic` from the
   entity object vs base-topic derivation; whether `on_time` + `brightness` in one payload is
   safe (would remove the two-step on Z2M).
5. Groups: switch groups expose `entity_id` like light groups (`group/switch.py`); how ZHA
   and Z2M group entities are identifiable in the registry (ZHA: `zha_group_0x...` unique_id
   [M]; Z2M: device identifier for the group [M]) and whether Z2M group membership is reachable
   from HA at all (if not, Z2M `expand_group` is `None` and non-native adapters return
   `group_not_supported`).
12. Hue `move` beyond brightness: whether `grouped_light` accepts `color_temperature`/`color`
    with `dynamics` (hue_dimmer only moved brightness on groups); whether a dimming dynamic and
    a color_temperature dynamic sent as separate writes run independently or the second cancels
    the first (decides per-attribute vs shared duration for combined moves); the bulb's gamut
    from `colors.py` for the saturation end point; whether `sections:` with `collapsed: true`
    in `services.yaml` passes hassfest for a custom component.
6. Frontend: does the `integration:` filter match entity registry platform (UI convenience only).
7. Blocking-import detector vs `pkgutil` discovery in the executor job.
8. `pytest-homeassistant-custom-component` version paired with the chosen HA 2026.x pin; fixture
   names above are from memory.
9. hassfest on custom components: accepts `services.yaml` without name/description when
   `strings.json` has `services`; `integration_type: service` + `single_config_entry`.
10. Hue `turn_on_for` via `behavior_instance` stays deferred (handoff 7.1).
11. Rig transport: WebSocket `call_service` `return_response` payload key and whether REST
    `?return_response` still exists in 2026.x (`websocket_api/commands.py:handle_call_service`,
    `api/__init__.py:APIDomainServicesView`); restart needs an admin token; SSH port and config
    path differ between HA OS and Container (inventory keys cover both).

## Verification (end to end)

- `pre-commit run --all-files`, `pytest` (unit), `python scripts/gen_docs.py --check` all green in CI
  on every PR.
- On the rig, with approval (there is no dev HA): first deploy adds the single entry, every
  action appears with translated names, light fields hide for switch-only selections; call
  `turn_on_for` on a mixed selection and inspect the response dict.
- Rig (with approval): one `turn_on_for` per platform adapter,
  `turn_off_for` on Shelly, the Hue port's five actions including a color_temp `move`/`stop` on
  a bulb and a brightness `move` on a `grouped_light`; lights return to snapshot state.
