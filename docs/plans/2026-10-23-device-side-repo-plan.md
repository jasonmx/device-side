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
tension: expose the feature through one action per feature across integrations, execute it on the
device or bridge so it survives HA restarts and outages, and document the sharp edges per
adapter (action x integration) so users choose with open eyes.

Demand evidence (light-extras-research, 2023-10 to 2026-10, 248 relevant items): Turn On For
Duration scored 101.8 (12 requests, 2 refused, 11 workaround threads), Every-Turn-On Level 54.1,
Transition Control 41.6, Set Attributes While Off 32.6.

Integration shares, analytics.home-assistant.io 2026-10-22, of 561,214 installs reporting
integrations: mqtt 48.5%, matter 41.3%, zha 25.6%, shelly 25.3%, hue 15.9%. (Not in scope:
tuya 29.5%, esphome 27.3%, tplink 13.8%, zwave_js 8.3%, tasmota 7.6%.)

## Glossary

Code and docs use these terms. "Platform" and "backing" are retired; `services.yaml` keeps its name because HA
requires it.

- **Action**: what the user calls, e.g. `device_side.turn_on_for`.
- **Feature**: the user experience one or more actions deliver (a timed flip, smooth dimming). Prose only.
- **Integration**: the HA integration that is the first hop to the device (Shelly, ZHA, MQTT, Hue).
- **Bridge**: a separate system between the integration and the device, named only when the integration alone
  doesn't say how the device is reached (Zigbee2MQTT behind MQTT). The Hue Bridge is not counted.
- **Adapter**: one action on one integration (or bridge). Carries the tier.
- **Capability**: the device-side functional unit the adapter's call reaches, in vendor terms (Shelly component,
  Zigbee/Matter cluster, Z-Wave command class).
- **Field**: an action parameter, e.g. `brightness`.
- **Entity domain**: light, switch. "Domain" alone is fine where unambiguous.
- **Scope**: the entity domains, capabilities and fields an adapter is known to work with, on hardware someone has
  tested. Outside it, calls are refused as not yet tested.

## Decisions from the interview (2026-10-23)

### Rationale and principles

- The repo exists for all four reasons: one action that works on a mixed room; execution on the
  device so it survives HA outages; filling gaps core will not; a permissive stance with
  documented sharp edges.
- **Inclusion test** (all must hold) for a feature:
  1. Once the command is sent, the behavior completes (or degrades to plain device behavior)
     with HA offline. No HA-side timers, polling or emulation.
  2. Native on integrations covering at least 20% of HA installs (the analytics shares above).
     Overlap between integrations is not published, so count the largest single-integration share
     as the lower bound. Shelly alone (25.3%) passes; a Hue-only (15.9%) or Z-Wave-only (8.3%)
     feature does not.
  3. Not already exposed by core *in a user-friendly way*. Primitives that exist but demand
     protocol knowledge (brightness_step 0 = stop, computing per-call transition times) count as
     unexposed.
  4. Documented user demand (as in light-extras-research). Contributions without evidence are
     accepted but not prioritized.
- **One action per user intent, not per protocol primitive.** Zigbee has move/step/moveto;
  device_side exposes one `move`. Command selection is hidden in the adapter.
- **No HA-side help.** Every feature runs on the device or bridge; nothing Device Side does
  depends on HA staying up. Emulation is never shipped; docs show how to build it with
  `set_attributes` plus an automation.
- **Drop-in for hue_dimmer users.** `set_attributes`, `get_attributes` and `set_scene` take hue_dimmer's
  field names, units (brightness in percent), names and descriptions, and return its response shape, so a
  user changes only the domain. `move`/`stop` replace raise/lower by design and are the exception.
- **Behave as core does.** When to raise, what to skip and what a response looks like follow HA core's own
  actions: `docs/action-behavior.md`.
- **Audience:** automation authors and dashboard users from v1. Actions for everything; entities
  only where a feature is a persistent setting, not a command.

### Scope

- **Integrations (v1):** Zigbee2MQTT via `mqtt`, ZHA, Matter, Shelly Gen2+, Hue v2. Hue is v1 for the
  hue_dimmer port. Hue `turn_on_for`/`turn_off_for` are `unsupported` (2026-10-26): the bridge
  can't honor the cancel contract (open item 10).
- **Actions (v1):**
  - `turn_on_for` on Z2M, ZHA, Matter, Shelly.
  - `turn_off_for` on Shelly only: it is Shelly-only natively (Zigbee/Matter `OnWithTimedOff` is
    on-then-off only; `off_wait_time` is a re-on guard). Other integrations return `unsupported`.
  - **Cancel contract:** a regular `turn_on` or `turn_off` cancels the timed flip, on every
    integration but ZHA, where only `turn_off` does (cancel spike 2026-10-26, open item 3: nothing stops
    an LTA004 timer with the light left on). The action descriptions promise this, ZHA caveat included.
    Shelly honors it natively (bench, 2026-10-24,
    Gen3/Gen4 fw 2.0.1: any `Set` without `toggle_after` cancels; a new `toggle_after` replaces;
    `toggle_after: 0` is rejected). Hue can't honor it, so it doesn't get the timed actions
    (2026-10-26, open item 10): its bridge timers ignore every manual on/off, aren't visible in the
    Hue app, and drop their action if the bulb is unpowered at expiry. No `cancel_delayed_toggle`
    action and no HA-side cancel hook.
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
    - `brightness: up | down`, `color_temp: warmer | cooler`, `saturation: up | down`,
      `hue: up | down` (`up` = the hue angle increases, red → yellow → green, wrapping at
      360°). One field per attribute, each with its own direction, so "brighter and cooler" is
      one call with no ambiguity. Rule: `up | down` wherever the direction is unambiguous;
      color temperature is the exception (Kelvin up is cooler, mireds up is warmer). Why, and
      why not `brighter | dimmer`: `docs/plans/2026-10-25-hue-port.md`, Decisions.
    - `sweep_time` (seconds; hue_dimmer's existing field): how long a **full-range sweep**
      takes, 0 → 100 % brightness, coolest → warmest of this light's range, 0 → 100 %
      saturation, 360° of hue. Speed is therefore constant whatever the start point, which is
      what hold-to-dim needs, and one number covers every attribute in the call. Default from
      hue_dimmer.
    - Limits in a collapsed "Limits" section (`services.yaml` sections): `brightness_limit`
      (%), `color_temp_limit` (K), `saturation_limit` (%). A limit is "stop here instead of
      the range end". A move already at or past its limit (or range end) in its direction does
      nothing and returns `unchanged` with `detail: at_limit`: `down` to 30 % from 20 % never
      brightens (decided 2026-10-26). Hue has no limit: a wrapping hue range was considered and
      dropped as needless complexity for a niche feature; revisit only if users ask.
    `stop` takes no fields and halts every move in flight on the target. (Per-attribute
    direction words and the reserved `hue` field confirmed by Jason, 2026-10-23.)
    Hue implementation: target = limit or range end, `dynamics.duration` = sweep_time ×
    fraction of range still to travel; brightness and color_temp each as one write;
    saturation as one `color.xy` write along the line toward the white point or the gamut
    edge (straight in xy, so native); `hue` is **unsupported on Hue** in v1 because a hue
    rotation is not a straight line in xy and chaining segments from HA would violate the
    offline rule. Zigbee Color Control Move Hue is native, so the field exists in the contract
    for that integration later. `stop` writes the interpolated current value for every attribute
    the transition cache holds for that light. Combined moves on Hue: verify on the rig
    whether per-attribute writes with separate durations run independently; if not, send one
    write with the longest duration and record `detail: shared_duration` (open item 12).
- **Deferred, architecture must accommodate:** cross-integration `set_attributes`, `get_attributes`
  and `move`/`stop`, Shelly Gen1, further
  domains (cover, valve, lock), and one further integration: **Z-Wave JS**.
- **`get_attributes` pairs with timed on/off and set-while-off:** every `turn_on_for`, `turn_off_for`
  and `set_attributes` adapter needs a matching `get_attributes` capability on its integration, to
  read the device state HA doesn't show (timer status; brightness, color and color temperature while off).
- **Z-Wave JS (post-v1, decided 2026-10-23):** scope is `move`/`stop` via Multilevel Switch CC
  Start/Stop Level Change (direction + duration), plus auto-off only where a
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
- **Set scene while off on Zigbee dropped (2026-10-27):** Zigbee scenes live on the device and recall turns
  lights on, and an HA-scene composition over `set_attributes` changes `set_scene`'s scope. `set_scene` stays
  Hue-only until users ask.
- **Set Turn-On Levels dropped (2026-10-25):** `set_turn_on_defaults` (the level and fade a device
  remembers for a plain turn-on) is a big, complicated lift. Revisit once a large user base shows
  whether it's needed and what it should look like.
- **ZHA's power-on settings are not a substitute (checked 2026-10-25):** its device config sets the
  startup attributes (`StartUpOnOff`, `StartUpCurrentLevel`, `StartUpColorTemperatureMireds`), which
  apply when mains power returns, not to an On command (`OnLevel`, not exposed). Its "smooth
  transition power-on" option is HA-side sequencing of `light.turn_on`, not setting attributes while
  off. Neither overlaps timed on/off, `move`/`stop` or `set_attributes`.
- **Naming convention (fixed now; it is a 0-to-1 decision):**
  1. `verb_object`, HA vocabulary only. Objects are the names HA's own services and state
     attributes use (`brightness`, `color_temp`, `attributes`, `scene`); protocol vocabulary
     (`level`, `OnLevel`, `PulseTime`, `toggle_after`) never appears in an action or field name.
  2. Commands (do something now) use HA's command verbs: `turn_on_for`, `turn_off_for`,
     `move`, `stop`, `set_attributes` (write HA light attributes to the device
     without turning it on), `get_attributes`, `set_scene`.
  3. Persistent settings (change how the device behaves from now on) use `set_<behavior>` with
     the trigger named in plain English, e.g. `set_power_on_defaults`. None are planned.
  4. Field names are the `light.turn_on` field names wherever one exists; a feature-specific
     field gets plain words (`duration`, `sweep_time`, `brightness_limit`).
  5. Field *values* are human terms for the outcome (`brighter`, `warmer`, a full-sweep time,
     a stop point), never device mechanics (a rate per second, a step count, a mired value).
     The adapter owns the conversion and documents it in `docs/integrations.md`.
  Domain `device_side`, UI title "Device Side", is final.
- **Groups: highest aggregation the device accepts.** Two kinds of group reach the dispatcher:
  - *HA group entities* (light group helper, switch group, legacy `group.*`, later
    cover/fan). Nothing downstream can address them, so `core/groups.py` always expands them,
    for every domain, in one place. `Target.via_group` records the wrapper so an adapter can still
    batch members that came from the same group.
  - *Integration-native groups* (Hue `grouped_light`, Z2M group entities, ZHA group entities).
    These pass through to the adapter as a single target. Each adapter declares `native_groups`: when
    true the adapter sends one command to the group (hue_dimmer sends `move`/`stop` to
    `grouped_light`; Z2M `turn_on_for` can publish to the group topic). When false, the
    dispatcher calls the integration's `expand_group(hass, target) -> list[Target]` hook
    (`IntegrationInfo.expand_group`; Hue uses `grouped_light.get_lights`, exactly what hue_dimmer
    does for `set_attributes`/`get_attributes` in `bridge.py`) and the adapter sees members. An
    integration with no hook and an adapter without `native_groups` returns `unsupported`
    (`group_not_supported`). Membership knowledge therefore lives in the integration (only it can
    know Hue or Z2M membership), but the call site is single and central.
  - Why central: one implementation and one test module for HA-group expansion instead of
    five; adapters never see a wrapper they cannot address; `via_group` lets an adapter re-batch when
    useful. Cost: the dispatcher must expand before bucketing, so an adapter cannot choose to
    address an HA group natively, which is fine because no device can. Goal throughout:
    minimize radio traffic and popcorning by sending to the largest unit the device accepts.
- **Results:** `SupportsResponse.OPTIONAL`. Response maps entity_id to
  `{status: unsupported|rejected|sent|confirmed|unchanged, integration, clamped_to?, detail?}`; `unchanged` means nothing was sent because the target is already where the call would leave it. Tier is not in the response: it is a subjective label about the code, not a fact
  about this call. A query returns core's shape instead: each target's data under its entity_id, with
  targets that could not be read left out. Raise `HomeAssistantError` only on invalid input or when every
  target failed, so mixed rooms do not abort automations, until slice 9f moves the raise rule to core's.
- **Stability tiers** per adapter (action x integration): `experimental | untested | beta |
  stable`. Rules live in `CLAUDE.md` (Tiers, Releases); summary: only `experimental` is
  declared (`AdapterScope.experimental`), the rest are computed by `scripts/check_tiers.py` from
  coverage and bench records keyed by the adapter's fingerprint; `stable` means on `main`. A
  tier covers the adapter's whole scope: there is no runtime tier gate and no options flow for
  it, and a capability or field nobody has tested is simply left out of
  `AdapterScope.capabilities`/`.fields`, so `supports()` refuses it as not yet tested. Tier is not
  logged per call and not returned in results.
- **Quality bar:** HA quality scale Gold conventions (config flow, translations, tests,
  diagnostics, docs).
- **Config:** single config entry, one confirm step, no options in v1. Services registered in
  `async_setup`, refusing calls until the entry loads (hue_dimmer pattern).
- **Testing, three layers:**
  1. Unit: `pytest-homeassistant-custom-component` for dispatch, group expansion, schemas and
     result shapes against a real `hass` fixture; integration calls mocked at the boundary
     (`mqtt.publish`, ZHA service, aioshelly RPC, `matter_client`, aiohue).
  2. **Rig: scripted integration tests against Jason's real HA instance**, the only way to
     scale verification across many adapters. Tests are YAML step files run by a small async
     engine (no pytest), and talk to HA over its WebSocket/REST API with a
     long-lived token: call `device_side.*` actions, assert on service responses and on
     state changes (e.g. the light is off N seconds after `turn_on_for`). A rig inventory file
     (gitignored, `tests/rig/inventory.yaml`) maps each integration to the household entities to
     use; tests restore prior state afterwards. A deploy script installs the pushed branch's
     `custom_components/device_side` through the maintainer's deploy tooling's `the maintainer's deploy tooling` (`the deploy sync command`; the agent key
     cannot rsync) and restarts HA (`the deploy restart command`) before the run.
     **Human approval gate:** the rig runner (`scripts/rig.py`) prints the inventory, the
     adapters to be exercised, the estimated duration and whether a restart is needed, then
     requires an interactive y/N (and a `DEVICE_SIDE_RIG_APPROVED=1` env var for CI-style
     invocation). Both the deploy+restart and the test run sit behind that gate. The devices
     are in-use household lights, so **Claude must ask before invoking the rig, every time**;
     the gate exists so occupants are not startled by devices changing state.
  3. Bench: a per-adapter record (`docs/bench/<integration>/<action>.md`) of the rig pass that
     promoted an adapter, with date, HA version, device model and firmware. Rig test results feed
     this record. **There is no dev HA; the live rig is the only HA.** The first time the
     integration loads in a real HA is the first approved rig deploy (slice 3); until then
     correctness rests on unit tests plus hassfest.
- **Docs:** hand-written. README is the front door (pitch, install, feature table, usage). A
  single `docs/integrations.md`, one section per integration on a fixed template (what it talks
  to, how targets resolve, per-action notes, sharp edges), split into per-integration pages only
  if it outgrows one file. `docs/contributing/testing.md`. No docs generator (slice 8 dropped).
- **Repo:** private until v0.0.1 ships (slice 5), then public with contributor docs. MIT. American English in
  all user-facing text (matches HA).
- **Versions:** minimum HA set to a release within the last six months (2026.x) so no compat
  shims; tests pin current stable; Python 3.14 in CI; copy ruff, pre-commit, codespell,
  gitleaks, hassfest and HACS validate workflows from hue_dimmer. Releases go `v0.0.x` while
  building; `v0.1.0` once this plan is feature complete. Remote testers don't gate it: scope the
  maintainer's rig can't reach stays out of scope and is refused until a tester report covers it.
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
  `light.turn_on`), except `set_attributes`, which keeps hue_dimmer's percent brightness and several-colors
  rule so its calls work unchanged; `async_extract_entity_ids(call, expand_group)` is a coroutine; `helpers/group.py` gained a
  group-entity registry (`GenericGroup`) that no component uses yet, so group helpers still need our expansion.

### Directory layout

Top level of `custom_components/device_side/` holds only the fixed HA files and three
subpackages: HA auto-imports top-level modules named after entity platforms and after
`group`, `diagnostics`, `repairs`, `trigger`, `device_trigger` etc., so adapters live
under `integrations/` and nothing is called `light.py`.

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
  strings.json           title/config/exceptions + one "services.<action>" block per action
  icons.json             "services": {<action>: {"service": "mdi:..."}}
  translations/en.json   copy of strings.json
  core/
    models.py            Status, Tier, ActionKind, Target, EntityResult, LightFields + validators
    scope.py             DurationLimits, AdapterScope, IntegrationInfo
    action.py            Action[RequestT] base class
    adapter.py              Adapter[RequestT] base class + gather() pacing helper
    registry.py          AdapterRegistry: pkgutil discovery, guarded import, lookup, matrix iteration
    resolver.py          entity_id -> Target (integration key via IntegrationInfo.ha_domain + detect)
    groups.py            expand HA group entities (any domain) to members; call the integration's expand_group
                         for native groups when the chosen adapter lacks native_groups
    duration.py          clamp(request, limits) -> (request, clamped_to)
    dispatcher.py        parse, extract, expand, resolve, run adapters, merge, raise rule, response
    actions.py           register one HA service per Action; _call_if_loaded gate (hue_dimmer pattern)
    runtime.py           DeviceSideData in hass.data[DOMAIN]: registry, dispatcher, semaphores, integration_state
  actions/
    __init__.py          discover() -> actions sorted by module name
    turn_on_for.py  turn_off_for.py                         (COMMAND)
    set_attributes.py  set_scene.py  move.py  stop.py        (COMMAND, Hue port)
    get_attributes.py                                         (QUERY, SupportsResponse.ONLY)
  integrations/
    __init__.py          discover() -> modules sorted; each exports INTEGRATION and ADAPTERS
    zigbee2mqtt/  __init__.py detect.py addressing.py turn_on_for.py
    zha/          __init__.py addressing.py turn_on_for.py
    matter/       __init__.py addressing.py turn_on_for.py
    shelly/       __init__.py addressing.py turn_on_for.py turn_off_for.py
    hue/          __init__.py bridge.py transition_cache.py colors.py
                  set_attributes.py get_attributes.py set_scene.py move.py stop.py
scripts/
  check_tiers.py         computed tiers, coverage and scope-coverage checks for CI (slice 9c)
  deploy.sh              the deploy sync command <branch>, then the deploy restart command (rig only)
  rig.py                 approval gate (inventory, adapters, duration, restart?) -> y/N -> deploy -> step files
  fingerprint.py         adapter fingerprints: AST hash of the adapter and its package imports, without docstrings or AdapterScope
docs/
  device_side_handoff-2026-10-23.md          existing
  plans/2026-10-23-device-side-repo-plan.md  this plan, saved in slice 0
  integrations.md                            one section per integration, fixed template
  contributing/testing.md
  bench/<integration>/<action>*.md           bench records (rig run, or -issue-<N> per tester report)
tests/
  conftest.py            enable_custom_integrations autouse; setup_integration; fake_registry; call()
  fakes/fake_integration/ INTEGRATION "fake" + scripted adapters for dispatcher tests
  fixtures/{z2m,zha,matter,shelly,hue,groups}.py   fabricate registry entries + boundary mocks
  core/   actions/   integrations/<i>/               one module per adapter; see Testing
  rig/    client.py (HA WS/REST client), inventory.py, engine.py (step runner, snapshot/restore, bench writer),
          inventory.yaml (gitignored), inventory.example.yaml, steps/<action>.yaml
```

Repo root: README.md (hand-written feature table), hacs.json, pyproject.toml,
.pre-commit-config.yaml, requirements_test.txt, `.github/workflows/{lint,tests,hassfest,validate}.yml`
copied from `/Users/jason/projects/hue-smooth-dimming`.

### Core contract

```python
# core/models.py
class Status(StrEnum): UNSUPPORTED, REJECTED, SENT, CONFIRMED, UNCHANGED
class Tier(StrEnum): STABLE, BETA, UNTESTED, EXPERIMENTAL   # computed by check_tiers, never stored on an adapter
class ActionKind(StrEnum): COMMAND, SETTING, QUERY

@dataclass(frozen=True, slots=True)
class LightFields:  # brightness, color_temp_kelvin, hs_color, rgb_color, xy_color, transition
    def present(self) -> frozenset[str]; def as_turn_on_data(self) -> dict

@dataclass(frozen=True, slots=True)
class Target: entity_id, domain, integration, entry: er.RegistryEntry, device, config_entry, state, via_group

@dataclass(slots=True)
class EntityResult: entity_id, status, integration, clamped_to, detail, data
    def as_response(self) -> dict   # drops None; data under "attributes"; no tier (a query returns data alone)

# core/scope.py
@dataclass(frozen=True) class DurationLimits: min_s, max_s
@dataclass(frozen=True) class AdapterScope:
    experimental: bool = False; domains = {"light"}; duration: DurationLimits | None
    fields: frozenset[str]; capabilities: frozenset[str] | None; confirmable: bool; native_groups: bool
    max_concurrency: int = 4; notes: tuple[str, ...] = ()
@dataclass class IntegrationInfo:
    key, title, ha_domain, detect: Callable[[hass, entry, device], bool] | None
    is_group: Callable[[hass, Target], bool] | None             # flags a native group (resolver sets Target.is_group)
    expand_group: Callable[[hass, Target], list[Target]] | None   # native-group members; None = cannot
    max_concurrency: int; available: bool = True; unavailable_reason: str | None

# core/action.py
class Action[RequestT](ABC):
    key: ClassVar[str]; kind: ClassVar[ActionKind]; domains: ClassVar[frozenset[str]]
    supports_response: ClassVar[SupportsResponse] = OPTIONAL
    fields: ClassVar[dict[vol.Marker, Any]]            # merged into cv.make_entity_service_schema
    @classmethod def schema(cls) -> vol.Schema
    @classmethod @abstractmethod def parse(cls, hass, call) -> RequestT   # ServiceValidationError on bad input
    @classmethod async def run(cls, hass, request, targets, dispatcher) -> list[EntityResult]:
        return await dispatcher.run_adapters(cls.key, request, targets)      # overridable

# core/adapter.py
class Adapter[RequestT](ABC):
    action: ClassVar[str]; integration: ClassVar[str]; scope: ClassVar[AdapterScope]
    def supports(self, hass, request, target) -> str | None  # None = ok, else reason key; sync, cheap; request so fields out of scope refuse
    @abstractmethod async def execute(self, hass, request, targets) -> list[EntityResult]
    def result(self, target, status, **kw) -> EntityResult  # stamps integration
    async def gather(self, hass, targets, send) -> list[EntityResult]  # integration + per-adapter semaphores; exc -> that target REJECTED
```

- **Registry:** `pkgutil.iter_modules` over `integrations/` and `actions/`; each package exports
  data (`INTEGRATION`, `ADAPTERS`, `ACTION`), not decorators, so import has no side effects, order is
  deterministic (sorted), the tier check and rig runner can import without `hass`, and tests can build a
  registry from an explicit module list. Each integration import is guarded: a failing import
  (library absent because the core integration is not installed) records
  `IntegrationInfo(available=False, unavailable_reason=...)` and setup continues. Discovery runs via
  `hass.async_add_import_executor_job`.
- **Resolver:** candidates = available integrations whose `ha_domain == entry.platform`;
  integrations with a `detect` hook win first (Z2M: a `("mqtt", "zigbee2mqtt_*")` device identifier
  [M]); then the generic one. Matter-paired Hue bulbs resolve to `matter` naturally. Unresolved
  reasons: `not_in_registry`, `integration_not_supported`, `integration_not_loaded`.
- **Groups:** `core/groups.py:expand_ha_groups` recurses only through entities whose registry
  platform is `group` (via `get_entity_ids`), any domain, max depth 4, dedupe preserving order,
  `via_group` set on members. Native groups (Hue `grouped_light`, Z2M/ZHA group entities) pass
  through as one target; after bucketing, `expand_native_groups` replaces each native-group
  target in a bucket whose adapter lacks `native_groups` with the integration's `expand_group` output
  (or an `unsupported` result when the integration has no hook). Results for expanded members are
  reported per member; the wrapper itself gets no row.
- **Dispatcher:** `handle(action, call)`: parse, `async_extract_entity_ids`, expand HA groups,
  resolve, domain filter, `action.run`, append `unsupported` for unresolved, total-failure
  check, build response when `call.return_response`. `run_adapters` buckets targets by adapter (no
  adapter -> `no_adapter`; domain mismatch -> `domain_not_supported`; `supports()` reason, e.g.
`domain_not_tested`, `fields_not_tested`, Shelly `capability_not_tested`), expands native groups per bucket as
  above, then runs adapters concurrently under `asyncio.timeout(30)`; adapter exceptions become
  `REJECTED` for every target; `reconcile` ensures exactly one result per target;
  `duration.apply` clamps before the adapter sees the request and stamps `clamped_to`. Total
  failure (every result unsupported/rejected) raises
  `HomeAssistantError(translation_key="all_targets_failed")` with a per-entity summary; no
  targets raises `ServiceValidationError("no_targets")`.
- **Setting-class actions** (none planned): same `Action`/`Adapter` contract with `kind=SETTING`.
- **Query actions** (`get_attributes`): payload in `EntityResult.data`, `supports_response=ONLY`. The
  response is `{entity_id: data}` for every target that was read, one entry per target, as core's
  `weather.get_forecasts` returns, so templates index it by entity_id and `merge_response` flattens it.
- **Actions:** one `hass.services.async_register(DOMAIN, action.key, ...)` per discovered
  action in `async_setup`; `_call_if_loaded` raises `ServiceValidationError("not_loaded")` until
  the entry is loaded.

### Integration routes for turn_on_for

- **Zigbee2MQTT:** ieee from device identifier; topic from the live MQTT entity's
  `command_topic` (via `hass.data["entity_components"]["light"].get_entity`, semi-internal [I]),
  fallback `zigbee2mqtt/<ieee>/set`. If fields present: `light.turn_on` first (blocking), then
  `mqtt.publish` `{"state":"ON","on_time":<s, 1dp>}`. Returns `SENT` (fire-and-forget). Limits
  0.1 to 6553.4 s. Tuya `countdown` devices are a documented v1 gap.
- **ZHA:** ieee from `("zha", ieee)` identifier; endpoint from unique_id `"{ieee}-{endpoint}"`
  [M]. Optional `light.turn_on`, then `zha.issue_zigbee_cluster_command` cluster 0x0006 cmd 0x42
  params `{on_off_control:0, on_time:tenths, off_wait_time:0}`, `context=call.context`. Exception
  -> `REJECTED`; then read OnTime (0x4001) -> `CONFIRMED` within 3 s under the request, else `SENT`.
- **Matter:** `get_node_from_device_entry(hass, device)` (`matter/helpers.py`); endpoint parsed
  from the right of unique_id `{node_device_id}-{endpoint}-{key}-{cluster}-{attr}` (`parts[-4]`).
  `supports()` requires the OnOff FeatureMap Lighting bit else `no_lt_feature`. Optional
  `light.turn_on`, then `matter_client.send_device_command(node_id, endpoint_id,
  OnOff.Commands.OnWithTimedOff(onOffControl=0, onTime=tenths, offWaitTime=0))`; optional
  `read_attribute` OnTime -> `CONFIRMED`. `switch` domain (plugs) out of scope until the plug question is settled.
- **Shelly Gen2+:** `entry.runtime_data.rpc` (`None` -> `gen1_unsupported`); component and id from
  unique_id `{mac}-{light|rgb|rgbw|cct|switch}:{n}`; one `call_rpc("<Component>.Set",
  {id, on: True, toggle_after: s, **fields})` with field translation copied from `shelly/light.py`;
  `GetStatus` read-back -> `CONFIRMED`. `turn_off_for` is the same with `on: False`.
- **Hue port** (hue_dimmer module -> adapter): `bridge.py` resolve/controllers/writes ->
  `integrations/hue/bridge.py` taking a `Target` (drop `_iter_targets`; `_write_light` raises so the
  adapter emits SENT/REJECTED); `transitions.py` `_brightness_cache` -> `TransitionCache` instance in
  `runtime.integration_state["hue"]`, keyed by (resource_id, attribute) so brightness, color_temp,
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

Integration semaphore from `IntegrationInfo.max_concurrency` (Hue 2 because aiohue's cap of 3 is shared
with core; ZHA 2; Matter 2; Shelly 4; Z2M 4) plus a per-adapter semaphore from
`AdapterScope.max_concurrency`, both applied inside `Adapter.gather()`. `execute` receives all
of an adapter's targets at once so native group commands stay possible. Hue `move`/`stop` keep the
"cache only after accept" rule.

### services.yaml, strings, icons

- `services.yaml` holds only `target` and `fields` with selectors. One filter dict per integration
  (`integration` is a single string): `{domain: [light, switch], integration: mqtt}` and so on for
  zha, matter, shelly; Hue-only actions `{domain: light, integration: hue}`; `set_scene`
  `{domain: scene, integration: hue}`. Filters are UI-only; adapters enforce via `supports()`.
- `strings.json`: `services.<action>.{name, description, fields.<field>.{name, description}}`
  plus `exceptions.{not_loaded, no_targets, all_targets_failed, invalid_duration, nothing_to_set}`.
- Adding an action = one block each in `services.yaml`, `strings.json`, `icons.json`.
  `tests/core/test_actions_setup.py` asserts all three exist for every discovered action and
  every schema field has a strings entry.

### Tier computation

`scripts/check_tiers.py` (slice 9c, `2026-10-25-release-gates.md`) imports the registry without `hass`
and computes each adapter's tier from its records, found by path (`docs/bench/<integration>/<action>*.md`).
It fails on a malformed record, a record with no adapter, or a non-experimental adapter under 95%
coverage (`coverage.json`); CI runs it and prints the tier table. `--require-beta`, run only by
`cut-release`, also fails on any `untested` adapter. It generates no docs: the README feature table and
`docs/integrations.md` are hand-written. Fingerprint: AST hash of the adapter module and, in turn, the
modules it imports from its own integration package, excluding docstrings and the `AdapterScope`
declaration; bench records carry the fingerprint they tested and list the capabilities (Shelly: RPC components) and light fields they exercised. Proof
follows the call: a record proves the device-side call, whatever HA domain the target shows, so a
relay exposed as a `switch` or as an on/off `light` rides one record. `beta` needs a record with the
current fingerprint, and every capability and field in scope covered: a capability by any passing
record (any fingerprint), a field by a current-fingerprint record, an option in scope
(`AdapterScope.options`) by current-fingerprint records with it on and with it off. Untested capabilities are left out of
`AdapterScope.capabilities` and refused, not taken into scope on a sibling's proof. Adding a capability
after a tester report is a scope edit plus a record listing it; the fingerprint survives it. Tier ladder: see `CLAUDE.md`. Tags come only from the `cut-release-candidate` and `cut-release`
workflows (a tag ruleset refuses any other), and `scripts/check_tag.py` refuses a tag not matching
`^v\d+\.\d+\.\d+(rc\d+)?$` or not matching its branch.

Tester reports (slice 9b): RC builds raise one fixable Repairs issue ("vX.Y.ZrcN: help test on your
hardware"). Its repair flow multi-selects the RC's requested tests (each an adapter and capability, e.g.
Shelly `turn_on_for` on the `Light` component) that match the user's own entities; each chosen test
becomes a non-fixable Repairs issue ("Test wanted: <integration> · <capability> on <device model>") whose
`learn_more_url` opens the `test-report.yml` GitHub issue form prefilled (text fields only) with
RC, HA version, action, capability, device model, firmware (`sw_version`) and a per-test
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

One test module per adapter under `tests/integrations/<i>/test_<action>.py` asserting the exact
response dict and boundary call arguments; `tests/core/` (registry, resolver, groups, dispatcher,
actions_setup) use only `tests/fakes/fake_integration`.

### Rig (approval-gated, real HA)

`scripts/rig.py` loads `tests/rig/inventory.yaml` (gitignored; `inventory.example.yaml` committed)
mapping each integration to household entities, prints inventory, the adapters about to run, estimated
duration and whether a restart is needed, then requires interactive y/N (or
`DEVICE_SIDE_RIG_APPROVED=1`). `scripts/rig.py` flow:

1. Read-only preflight: load inventory and `.env.rig` (`HA_URL`, `HA_TOKEN` for a non-admin user,
   `RIG_SYNC_CMD`, `RIG_STATUS_CMD`, `RIG_RESTART_CMD`); `AdapterRegistry.discover()` (no hass) intersected with inventory
   integrations -> one line per adapter (`shelly / turn_on_for -> light.office_strip (beta)`) then one per
   test case with its entity; sum each step file's `rig_seconds` for the estimate; compare `HEAD:custom_components/device_side` with
   `the deploy status command` to decide whether a deploy+restart is needed, and refuse a deploy unless
   `origin/<branch>` carries that tree. Nothing mutates before the gate.
2. Gate: print the plan, `Proceed? [y/N]`. `--dry-run` stops here.
3. `scripts/deploy.sh`: `the deploy sync command <branch>` (the maintainer's deploy tooling verb: fetch into a device-side clone on
   the Pi, replace the integration dir inside the container), `the deploy restart command`; poll
   `/api/config` until `RUNNING`, then wait for `device_side.turn_on_for` in `/api/services` (hard
   fail at 180 s).
4. `tests/rig/engine.py` runs the step files on one `HAClient`. Flags: `--no-deploy`, `--no-restart`,
   `--integration <key>`, `-k <test name substring>`, `--unattended` (skips `observe` steps).

Step files (`tests/rig/steps/<action>.yaml`, one per action) run against every inventory integration
that has the adapter; the registry supplies the expected status (`confirmable` -> `confirmed`, else
`sent`), the timing tolerance (`TOLERANCE_S`: Zigbee/Matter 3 s, Shelly/Hue 2 s) and the fields in scope.
`only: [<integration>]` is the one per-test escape hatch. Steps: `set`, `call`, `expect_response`,
`expect_error`, `expect_state` (immediate or `within`; every member of a `group`), `wait`, `sample`
(ramps), `observe` (y/N to the person at the rig), `restore`; any step may take `target: <role>`.
Durations accept numbers, `duration`, `tol` and `+ - *`, parsed by a safe AST walk; a new need is a new
step in Python, never templating. A schema error names the file, test and step at load. `HAClient`
(`tests/rig/client.py`): WS `call_service` with `return_response`, REST state reads,
`wait_for(entity_id, predicate, timeout)` on `state_changed`. Each case snapshots state + brightness/CT/
color of its entities (group members too) and restores in a `finally` (Hue will capture via
`device_side.get_attributes` so off-light attributes restore). Timing assertions are windows:
still on at `duration - tol`, off by `duration + tol`. Rig durations are 5 to 8 s. Rig tests cover one
happy path and one refusal path per adapter; branches stay in unit tests, which never touch the rig.
hue_dimmer's release checklist (§2-5) became the Hue step files.

When every test of an adapter passes (no `-k`, nothing failed), the engine writes its bench record;
Jason reviews and commits the diff. A test with an unobserved `observe` step proves no capability or field.

`.gitignore`: `tests/rig/inventory.yaml`, `.env.rig` (example at `tests/rig/env.example`).
The maintainer's rig has private setup docs. `docs/contributing/testing.md` covers manual testing
on any Home Assistant: install, first-load check, and how to file a test report.
Inventory format (per integration -> entities with role tags `light_dimmable`, `light_ct`,
`light_color`, `switch_plug`, `group`, `scene`) is in `tests/rig/env.example` and
`tests/rig/inventory.example.yaml`. **Claude asks before every rig run; the devices are
in-use household lights.** Rig passes are recorded in `docs/bench/<integration>/<action>.md`
(date, HA version, device model and firmware from `config/device_registry/list`, fingerprint from
`scripts/fingerprint.py`, capabilities and fields reached, per-test table, source: rig run or
test-report issue).

## Delivery sequence

| # | Slice | Done when |
|---|---|---|
| 0 | Scaffold + CI | Plan saved to `docs/plans/`; `git init`, private GitHub repo `jasonmx/device-side`; manifest, config_flow, const, strings, icons, empty services.yaml; pyproject, pre-commit, workflows from hue_dimmer; `test_actions_setup.py` green with zero actions; hassfest + HACS validate green; README skeleton with matrix markers. |
| 1 | Core + fake integration | `core/*`; `actions/turn_on_for.py`, `turn_off_for.py`; fake integration (with a fake native group and `expand_group` hook); dispatcher/resolver/groups tests green (HA-group expansion for light and switch, native-group pass-through vs expansion, clamp, total-failure raise, response shape, semaphore bound, guarded-import skip). No live load yet: there is no dev HA. |
| 2 | Shelly `turn_on_for` + `turn_off_for` | one RPC with fields; Gen1 -> unsupported; read-back -> confirmed under mock; Shelly section of `docs/integrations.md` on the template; adapter `experimental=True`. |
| 3 | Rig harness | `scripts/rig.py`, `deploy.sh`, `tests/rig/conftest.py`, inventory example, `docs/contributing/testing.md`; **first approved deploy is the integration's first load in any HA**: confirm entry adds, actions appear with translated names, the brightness fields hide for a switch-only selection; then Shelly `turn_on_for` passes against the house; bench record written; Shelly `switch` and on/off `light` -> beta (shared on/off: a relay shown as a light sends the same `Switch.Set`); Shelly light fields and the `Light`/`CCT`/`RGB*` components out of scope until a tester reports. |
| 4 | `turn_off_for` rig pass | rig test for `turn_off_for`; bench records written, so both Shelly adapters reach beta. (`toggle_for` was dropped.) |
| 5 | First release (`v0.0.1`) + HACS submission | Detail in `2026-10-23-hacs-early-release.md`. Scope: Shelly `switch` and on/off `light` (shared on/off) for `turn_on_for` and `turn_off_for`. MIT `LICENSE`; `custom_components/device_side/brand/icon.png` (+ `@2x`); hand-written bench records and README feature table (no matrix markers); README install via HACS custom repository; short `CONTRIBUTING.md`; full-history `gitleaks detect` clean; topics added; repo flipped public; `gh workflow enable validate.yml`, nightly schedule restored and private-repo guard removed; PR `release/v0.0.1` -> `main`, `ci-green` on `main` with hassfest + HACS validate green; tag `v0.0.1` and a full (not pre-) GitHub release; PR to `hacs/default` adding `jasonmx/device-side` to `integration`, from a personal fork; `release/v0.0.2` cut from `main`. **v0.0.1 ships without an RC soak to start the HACS review clock; from v0.0.2 the Releases rules apply in full.** |
| 9a | Rig step files | **Done** (#26, #27). **plan in /plan first** (interview the maintainer before any code); rig tests converted to declarative YAML step files (set state → call action → expect → restore), keyed by inventory roles so a tester can later map roles to their own entities; the format is designed against every planned action (timed on/off, `move`/`stop` ramps from hue_dimmer's `RELEASE_CHECKLIST.md`, `set_attributes`/`get_attributes` while off), not just Shelly's; `scripts/rig.py` runs the step files, `--dry-run` prints the steps with entities filled in; adapter fingerprinting; each rig run prints the bench record fields (pass/fail per step, HA version, device model, firmware, adapter fingerprint). `testing.md` updated: dedicated non-admin HA user for the token; ZHA needs an admin token for its adapter only. Lands before slice 6, so every later rig test is written as step files. Plan: `docs/plans/2026-10-25-rig-step-files.md`. |
| 6 | Z2M `turn_on_for` | **Done** (#22, #23, #25). detect, addressing, publish; `light.turn_on` precedes when fields present; group topic when `native_groups`; rig test. |
| 11 | Matter `turn_on_for` | **Done** (#24). LT check; `OnWithTimedOff`; optional read-back; rig test on bulb and plug. |
| 10 | ZHA `turn_on_for` | **Done** (#31, #32, #34, #39). ZHA set up on the maintainer's rig first: a second Zigbee coordinator on its own channel, apart from Z2M's network; devices paired to it for the rig roles; steps in the private rig notes; addressing; admin context passthrough; ValueError -> rejected; rig test, run with an admin token (`.env.rig`) for ZHA suites only. |
| 7 | Hue port | Plan: `docs/plans/2026-10-25-hue-port.md` (three PRs, 7a to 7c). five adapters + bridge/transition_cache/colors; `move` across brightness, color_temp, saturation (`hue` unsupported on Hue); `grouped_light` native for move/stop and get_attributes, expanded for set_attributes; hue_dimmer tests ported to real-hass fixtures; rig parity with hue_dimmer `tests/RELEASE_CHECKLIST.md`. Hue `turn_on_for`/`turn_off_for` dropped after the open item 10 bench (2026-10-26): `unsupported`. |
| 9c | Release gates | **Done** (#33, #35, #36, #37). Plan: `docs/plans/2026-10-25-release-gates.md`. Computed tiers and the scope-coverage check in `scripts/check_tiers.py`, run in CI; per-adapter coverage check; `test-report.yml` issue form (bug reports need it whenever 9b lands); every `v*` tag from a workflow (`cut-release-candidate` with the RC audit gate of `2026-10-23-rc-audit-gate.md`, `cut-release` with `check_tiers --require-beta`) behind a tag ruleset. Lands before the first RC (`v0.0.2rc1`), wherever in this sequence a release is first wanted. |
| 9d | Rig coverage sweep | **plan in /plan first**; audit every adapter's scope (domains, capabilities, fields, native groups) against the maintainer's rig hardware; add inventory roles and step files for everything the rig can reach; rig runs leave a current-fingerprint bench record for each, so v0.1.0 launches with the widest scope the rig can prove. What the rig can't reach is listed for 9b and stays out of scope. |
| 9e | Native groups survey | **plan in /plan first**; a short exploration of integration-native groups beyond Hue (Z2M and ZHA group entities; Matter and Shelly where HA exposes any): how each is detected and addressed, whether its native group command keeps the device-side behavior (timed off, transitions) across members, and a rig check of each candidate. Outcome: per integration, `native_groups` on or off for v0.1.0, recorded as a decision here, with bench records for those turned on. Hue's `grouped_light` ships in 7 regardless. |
| 9f | Core-aligned failure behavior | **plan in /plan first**; move the dispatcher's raise rule from "raise when every target failed" to core's, per `docs/action-behavior.md`: unavailable or missing targets skipped with core's warning; a field a target can't take dropped; a target the caller named that the action can never support raises (as `ServiceNotSupported`); a device or bridge error raises; a query that reads nothing raises. Decide whether command actions keep their optional status response, which core's commands don't have, and whether `nothing_to_set` becomes a warning (a hue_dimmer call passing only zeros did nothing). Every action's tests and the rig's `expect_error` steps follow. |
| 13 | Zigbee parity and timer state | Plan: `docs/plans/2026-10-27-zigbee-parity-timer-state.md` (13a to 13k). `get_attributes` takes switches and reports a running timer (Shelly, Matter, ZHA, Z2M where readable); ZHA and Z2M gain `get_attributes`, `move`/`stop` (hue cycling included) and `set_attributes` while off; after a probe spike, by integration, with the Hue A60 visiting the Hue bridge, ZHA and Z2M once each after that integration's code freezes. Needs 7c and 9f first. |
| 12 | `v0.1.0` ("v1" names the scope, not the version) | feature complete for this plan; scope limited to what rig runs (and any tester reports) cover; README feature table current; release checklist adapted from hue_dimmer; the `predicted_state` default reviewed (flip it to off if flaky), on the regression issues and rig runs since it landed. |
| 9b | Remote tester flow (after `v0.1.0`) | **plan in /plan first**; starts when an adapter needs hardware the rig lacks (a reported bug on someone else's device, a community integration such as Z-Wave JS). Standalone tester runner: one file (`uv run`, PEP 723 inline metadata, aiohttp WebSocket + PyYAML), talks to HA_URL + long-lived token, assumes integration installed via HACS or by hand (no deploy), runs 9a's YAML step files with a confirmation gate on every run; `tests/rig/client.py` moved to a location both the runner and `scripts/rig.py` import; runner prints a prefilled `test-report.yml` issue body; RC-only umbrella Repairs issue with multi-select flow and prefilled per-test links; bench files filled from tester reports. |

Slice 9 was split on 2026-10-25. Color bulbs from Shelly and Hue let the maintainer's rig cover the v1
integrations, so v0.1.0 needs no remote testers and the tester tooling moves to 9b. Hardware the rig still
lacks (plugs on ZHA, Z2M and Matter; a Thread-native Matter bulb; Shelly components beyond the bulb's) stays
out of scope until someone tests it.

Re-planned later on 2026-10-25. Slice numbers are IDs; rows are in delivery order. Set Turn-On Levels was
dropped (see Not planned). Slice 8 (docs generator) was dropped because the maintainer's rig now tests most
devices: the README table stays hand-written and tier computation moves to 9c. Matter (11) and ZHA (10) moved
ahead of the Hue port now that the rig can run both networks. 9a was split: rig step files land before slice 6
so no later rig test is written twice, and the release gates (9c) land before the first RC.
9d (rig coverage sweep) and 9e (native groups survey) were added on 2026-10-25, between 9c and v0.1.0.
9f (core-aligned failure behavior) was added on 2026-10-26, after the Hue port showed device_side's raise rule
differs from both core's and hue_dimmer's.
13 (Zigbee parity and timer state) was added on 2026-10-27, after a v0.1.0 gap review.

`v0.0.x` releases are cut between slices whenever a set of adapters reaches beta; one release may carry
several integrations or actions.

Each slice ends with `/audit-code` on its diff (everything since the previous slice's audit, plus any
sibling-repo changes it needed), run by a fresh subagent that gets the code and no conclusions from the
building session. P0/P1 findings are fixed before the slice's commit; the rest are fixed or filed as issues.
The first audit, at the end of slice 3, covers the whole repo, since nothing before it was reviewed.
Each slice lands by PR into the current `release/vX.Y.Z` branch, one per session, from that session's own worktree and `wt/<topic>` branch; the session squash-merges it once `ci-green` passes (see `docs/plans/2026-10-24-parallel-sessions.md`). Implementation starts in a **fresh session** per the planning rule;
the first action of that session is slice 0.

## Open items to verify during implementation (not before)

1. Matter: `get_matter(hass)` stability across 2026.x; `matter_server.client.models.clusters`
   importable without the integration loaded; which device types carry OnOff `LT` (plugs?);
   endpoint parsing from unique_id vs iterating `node.endpoints`.
2. Shelly: `RpcDevice.call_rpc` signature at the pinned aioshelly; `toggle_after` type/unit and
   limits; `GetStatus` timer field names; `Switch.Set toggle_after` [M]; how `_id` derives from key.
3. ZHA (answered in slice 10, zha 2.3.1): `Device.issue_cluster_command` raises `ZHAException` on a
   non-success ZCL status and zigpy raises on delivery failure, so a returned call was accepted. Params
   `on_off_control`, `on_time`, `off_wait_time`, `command_type: server`. A light's unique_id is
   `{ieee}-{endpoint}`; group entities are `{platform}_zha_group_0x{id:04x}`. A non-admin caller gets
   `Unauthorized` -> `REJECTED`/`admin_required`. OnTime read-back works on the rig's Hue bulb (counts
   down live; a new timer replaces the old), so `CONFIRMED` = OnTime at or just under the request.
   Built: `integrations/zha/zcl.py` reads it through ZHA internals (`get_zha_gateway`), since the
   public read is an admin websocket command. Per-device results: `docs/integrations.md`, ZHA, Tested behavior.
   Cancel spike 2026-10-26 (`docs/plans/2026-10-26-zha-ontime-cancel-spike.md`), LTA004 fw `0x01001416`,
   HA 2026.10.2: no flicker-free cancel. Writing `OnTime` = 0, `OnWithTimedOff` `on_time: 0` and
   `turn_on_for` 0.05 s (clamped to 0.1 s) each end the timer by turning the bulb off.
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
    from `colors.py` for the saturation end point. Answered in 7b (#48): hassfest accepts
    `sections:` with `collapsed: true` in a custom component's `services.yaml`.
6. Frontend: does the `integration:` filter match entity registry platform (UI convenience only).
7. Blocking-import detector vs `pkgutil` discovery in the executor job.
8. `pytest-homeassistant-custom-component` version paired with the chosen HA 2026.x pin; fixture
   names above are from memory.
9. hassfest on custom components: accepts `services.yaml` without name/description when
   `strings.json` has `services`; `integration_type: service` + `single_config_entry`.
10. Hue `turn_on_for`/`turn_off_for` (slice 7). Answered by bench spike 2026-10-26
    (`docs/plans/2026-10-26-hue-timer-spike.md`): bridge BSB002 sw 6.1.1978418030, two LTA009 sw 1.163.1.
    The bridge does **not** honor the cancel contract natively. **Decision:** Hue is `unsupported`
    for both actions (Scope, cancel contract).
    - **Expressible:** yes, as an instance of the built-in "Timers" `behavior_script` (raw
      `POST clip/v2/resource/behavior_instance`). Configuration: `duration: {seconds: int}` (1 s
      resolution; 0 fires at once), `where: [{group: room, items: [lights]}]`,
      `what: [{group: room, actions: [{target: light, action: {on: {on: false}}}]}]`. Action targets
      must be `light`: `room` and `grouped_light` are rejected, so a group needs one action per member.
      `turn_off_for` is the same with `on: true` after an immediate off.
    - **Start:** creating or enabling doesn't start it; `PUT {"trigger": {"start": {}}}` does (aiohue
      `start`). POST rejects `trigger`, so it is always two calls. `state.next_trigger_time` appears once
      started, a read-back for `confirmed`.
    - **Accuracy:** fired within about 1 s of the duration at 1, 10, 12, 15, 45 and 60 s (1 s
      sampling), inside `TOLERANCE_S`.
    - **Plain on/off through HA:** no cancel. Off then on mid-timer, the timer still fired.
    - **Hue app toggle, dimmer press:** no cancel. Both fired on time.
    - **Delete, `stop` trigger:** both cancel. **Disable:** does not; a disabled started timer still fired.
    - **Second call:** a second instance stacks (both fire). `metadata.name` isn't unique, so
      find-and-replace by name is the adapter's job. Re-sending `start` restarts an instance from now;
      a new duration is a `configuration` PUT (which stops it) then `start`, as the bridge refuses
      both in one PUT.
    - **Cleanup:** a fired instance stays (`timer_state: stopped`) until deleted. Not shown in the
      Hue app. Cap: 43 `behavior_instance`s per bridge, shared with the app's own automations
      (`507 Instance capacity limit error`).
    - **Unreachable at expiry:** the bulb stays on. Power cut across expiry: the bridge still showed
      it connected, sent the off, recorded it as off, and never retried; on power-up the bulb came on
      and stayed on.
11. Rig transport: WebSocket `call_service` `return_response` payload key and whether REST
    `?return_response` still exists in 2026.x (`websocket_api/commands.py:handle_call_service`,
    `api/__init__.py:APIDomainServicesView`); restart needs an admin token; SSH port and config
    path differ between HA OS and Container (inventory keys cover both).

## Verification (end to end)

- `pre-commit run --all-files`, `pytest` (unit), `scripts/check_tiers.py` all green in CI
  on every PR.
- On the rig, with approval (there is no dev HA): first deploy adds the single entry, every
  action appears with translated names, light fields hide for switch-only selections; call
  `turn_on_for` on a mixed selection and inspect the response dict.
- Rig (with approval): one `turn_on_for` per integration,
  `turn_off_for` on Shelly, the Hue port's five actions including a color_temp `move`/`stop` on
  a bulb and a brightness `move` on a `grouped_light`; lights return to snapshot state.
