# device_side: handoff notes for repo planning

Session date: 2026-10-23. Written for the next session, which will plan the repository.
Everything below comes from one long design conversation. Upstream source and docs were
fetched into a sandbox on that date, so file and line references are approximate (repo HEAD
on 2026-10-23, aiohue checked at tag 4.9.0).

## 0. How to read this

Confidence tags:

- **[V]** verified this session against source code or docs. Paths and URLs are in section 9.
- **[M]** from memory, not verified. Treat as a hypothesis and check before building on it.
- **[I]** inference or judgement.

Where a claim has no tag, it is a decision made by the user.

## 1. The project in one paragraph

A Home Assistant custom integration with domain **`device_side`** (UI title "Device Side").
It exposes device-native features that HA's light and switch entity model does not expose,
by sending commands through the existing integrations' own connections: Z2M, ZHA, Shelly
Gen2+, Hue v2 and Matter. No forking of integrations. Forking a library is acceptable in
principle but turned out to be unnecessary (see 4.2).

Three features:

1. **Timed turn-on:** turn on, then the device turns itself off after N seconds.
2. **OnLevel:** set the brightness a light uses whenever it is turned on digitally.
3. **`set_attributes`:** set brightness, colour temperature and colour without changing
   on/off state (works whether the light is on or off).

## 2. Decisions made

| Topic | Decision |
|---|---|
| Domain | `device_side` (snake_case, two words). Calls look like `device_side.set_attributes`. |
| Action name | `set_attributes` (debate verdict over `set_look`; user confirmed the overall direction, not the action name specifically, so reconfirm). |
| Scope | `light` and `switch` entities (plugs are `switch`). Covers, locks, sirens, valves return `unsupported` for now. |
| Hue | v2 only. No v1 support. |
| Tuya | Dropped (local control only). Note: Tuya-protocol Zigbee devices via Z2M are local and still appear (see 4.3). |
| Timer semantics | "Turn on, then off after N seconds." |
| Out-of-range durations | Clamp, log a warning, and return `clamped_to` in the per-entity result. Limits go in the services.yaml description. Clamping is the safe direction (light turns off sooner, never not at all). |
| OnLevel | Native only, brightness only. Colour/CT on-level does not exist natively anywhere (see 4.5). HA-side emulation of OnLevel is dropped. |
| Emulation | Users who want OnLevel emulation can build it with `set_attributes` plus an automation. |
| HA-side help | None. Every feature runs on the device or bridge and never depends on HA staying up: no HA-side hooks, timers or emulation (such as reset-at-off OnLevel). Users who want HA-side behaviour build it with an automation. |
| Integrations | No forks of integrations. Reuse existing integration services or libraries so connections, queuing and throttling are shared where they exist. |
| Per-entity results | `unsupported`, `rejected`, `sent`, `confirmed`, plus adapter used and `clamped_to`. |
| Service registration | Register in `async_setup`; gate on config toggles inside the handler; do not add or remove services at runtime (see 4.1). |

## 3. Feature matrix by platform

| Feature | Z2M | ZHA | Shelly Gen2+ | Hue v2 | Matter |
|---|---|---|---|---|---|
| **Timed turn-on** | `{"state":"ON","on_time":N}` seconds, 0 to 6553.4 [V]; Tuya-protocol devices use `countdown`, max 43200 s [V] | On/Off cluster cmd 0x42, `on_time` in tenths of a second, via `zha.issue_zigbee_cluster_command` [M] | `toggle_after` on `Light.Set`, `RGB.Set`, `RGBW.Set`, `CCT.Set` [V]; `Switch.Set` [M]; Gen1 relay timer param [M] | Provisional: bridge-side `behavior_instance`, one-shot timer unverified | `OnWithTimedOff`, conformance `LT` (Lighting feature) [V] |
| **OnLevel (brightness)** | `level_config.on_level`, 1 to 254 or `"previous"` [V] | `on_level` number config entity, 0 to 255, 255 = previous [V] | None [V] | None [V for aiohue model] | `OnLevel`, nullable [V]; HA already exposes it as a `number` entity [V] |
| **Native on-colour or on-CT** | No | No | No | No | No |
| **Set brightness while off** | No clean route: `brightness` key forces the light on [V] | Raw cluster commands only [M] | Unknown (docs silent) | Yes, per user's existing build; aiohue `set_state(on=None)` omits `on` [V] | In spec: `MoveToLevel` plus per-command options override [V]; device may ignore |
| **Set colour/CT while off** | Likely, via colour commands; enable with `color_options.execute_if_off` [V, partly read] | Raw colour commands; ZHA tracks per-device support [V] | Unknown | Yes, per user's build | In spec, same mechanism [V]; device may ignore |
| **Route** | Public: `mqtt.publish` | Public: service and number entity | Internals: aioshelly RPC on the config entry [M] | Library: aiohue via core's bridge object `HueBridge.api` [V] | OnLevel via sibling number entity (public) [V]; everything else via `matter_client.send_device_command` [M] |
| **Capability check** | `level_config` and `countdown` exposes are advertised; `on_time` is not [V] | Cluster presence only, which does not prove the attribute exists [V] | Component presence | Unknown | FeatureMap and attribute list [V] |

## 4. Verified findings

### 4.1 Home Assistant core mechanics

- Actions are published under the integration's domain, so the domain prefixes every call [V, docs].
- Docs say register actions in `async_setup`, not `async_setup_entry` [V, docs].
- Service names and descriptions are translatable since HA 2023.8 [V, docs blog]. The UI label can therefore differ from the YAML slug.
- Manifest docs: the domain "has to be unique and cannot be changed" and must match the directory name [V, docs].
- `services.yaml` is static. It is loaded once per service on first description request and cached in `SERVICE_DESCRIPTION_CACHE` [V].
- `async_set_service_schema(hass, domain, service, schema)` writes straight into that cache. It accepts `name`, `description`, `fields`, `target`; validates `target`; and clears the all-descriptions cache [V]. It can be called from an options update listener to change the UI live.
- The UI lists only registered services, because `async_get_all_descriptions` iterates registered services [V].
- Entity selector `filter` supports `integration`, `domain`, `device_class`, `supported_features`, `unit_of_measurement`. `integration` is a single string per filter dict, so one dict per integration [V].
- The backend `EntitySelector.__call__` validates only `domain`, `include_entities` and `exclude_entities`. The other filters are UI-only, so handlers must enforce support themselves [V].
- Whether the frontend's `integration` filter matches the entity registry platform: [M]. If so, Z2M lights are `mqtt` and Matter-paired Hue bulbs are `matter`, so the filter is coarse [I].
- Whether the frontend prefers translated descriptions over `async_set_service_schema` text: not verified. `description_placeholders` is a supported route for dynamic translated text (it exists on the service registration signature) [V].
- Naming data: about 213 core service names start with `set` [V]. No core `set_look` or `set_attributes`. Nearest: `zha.set_zigbee_cluster_attribute`, `lifx.set_state`, Yeelight `set_color_*_scene` [V].
- Core has 1,551 component directories; 507 contain an underscore [V]. "device-side" or "on-device" appears in zero core `strings.json` files [V]. HA's local-control vocabulary is `iot_class` `local_polling` / `local_push` [V].

### 4.2 aiohue and the Hue integration (aiohue 4.9.0, which core pins)

Files checked are identical at tag 4.9.0 and HEAD.

- `HueBridgeV2.request(method, path)` builds `https://{host}/{path}` with no `clip/v2` prefix, so arbitrary paths work [V].
- `request()` assumes the v2 envelope (`result["data"]`). A v1-shaped response raised `AttributeError` after the request had already been sent [V, tested on mock]. `create_request()` yields the raw `ClientResponse` and avoids this. v1 is now out of scope, but the finding matters for any raw call.
- aiohue uses its **own** aiohttp session with `TCPConnector(limit_per_host=3)` and `ssl=False`. It sends the `hue-application-key` header. There is no way to inject HA's session, and core does not [V].
- Pacing is a concurrency cap (3), not a rate limiter [V]. Measured on a mock bridge: max in-flight 3; 12 requests with 0.2 s server latency ran at 14.6 req/s; `create_request()` shares the same cap [V].
- `request()` retries 429/503 with sleep `0.25 * attempt`, up to 25 attempts (measured gaps 0.5, 0.76, 1.0 s). `create_request()` has no retry [V].
- `HueBridgeV1` constructs an `asyncio_throttle.Throttler` but never uses it. Core only uses V1 for v1 bridges [V].
- Core's `async_request_call` only maps exceptions to `HomeAssistantError`. It adds no pacing. No `PARALLEL_UPDATES` found in the v2 light, entity or group files [V].
- `bridge.api` on core's `HueBridge` object is the `HueBridgeV2` for v2 bridges [V]. How to reach it from a config entry: not verified.
- Core registers the Hue bridge as a device in the device registry; bulbs link to it via `via_device` [V]. So "device-side" legitimately includes the bridge.
- aiohue has `BehaviorInstanceController` (in `controllers/config.py`) with `set_enabled`, `start`, `stop` plus generic `create` and `update`, and `BehaviorInstance` / `BehaviorScript` models [V]. Whether the model can express a one-shot "on, then off after N seconds" config is **not verified**.
- `lights.set_state` takes `on=None` and omits it from the PUT; core's light `turn_on` always sends `on=True` [V].
- aiohue's `powerup` feature is power-restore behaviour only, not digital turn-on [V].
- Hue v2 has no per-light one-shot "off after N" [M]; `dynamics.duration` is a transition time [M].
- The "about 10 light commands per second" bridge limit is Signify documentation as recalled [M]. aiohue's own comment says the bridge returns 429 above 3 simultaneous requests [V].
- Forking aiohue is not needed: stock 4.9.0 is enough for everything planned [I].

### 4.3 Z2M (zigbee-herdsman-converters HEAD)

- Generic on/off converter keys `state`, `on_time`, `off_wait_time`. `on_time` and `off_wait_time` are validated 0 to 6553.4 s. Sends `genOnOff` `onWithTimedOff` when state is on and either key is present [V].
- `on_time` is not an advertised expose, so support cannot be detected up front. `mqtt.publish` is fire-and-forget [V].
- Tuya-protocol devices use a `countdown` expose (in 32 expose definitions, plus numbered and layer variants). Max 43200 s. Their converter uses `onWithTimedOff` non-standardly and a source comment says on/off/toggle cancel it [V]. That comment is about Tuya devices only.
- `level_config` composite exposes `on_level`, `on_off_transition_time`, `on_transition_time`, `off_transition_time`, `execute_if_off`, `current_level_startup`. `on_level` writes the Level Control `onLevel` attribute, clamped to 1 to 254, with `"previous"` = 255 [V].
- Z2M itself probes OnLevel support by reading the attribute and caching `onLevelSupported=false` on failure [V].
- `color_options.execute_if_off` (write-only) writes the colour cluster Options attribute [V].
- The main light converter's `brightness` key forces state to on (via `MoveToLevelWithOnOff`). The `moveToLevelWithOnOffDisable` quirk uses plain `moveToLevel` but still turns the light on when state changes. No `/set` message found that sends plain `MoveToLevel` while off [V].
- Colour converters send colour commands only, with no on/off command [V, first part of the converter read].
- `on` without brightness sends a plain `on`, except after an off-with-transition or when a transition is specified, where Z2M simulates it using `level_config.on_level` or "previous" [V].
- Other timer-like exposes seen (device-specific, not planned): `auto_relock_time` for locks (persistent setting, 0 to 3600), IAS WD `warning` with duration (default 10), irrigation `*_duration` names [V as names only].
- How Z2M surfaces `/set` failures: not investigated.

### 4.4 ZHA (zigpy/zha HEAD)

- `on_level` is a number config entity (0 to 255) created for any device with a Level Control server cluster. That is a cluster match, not an attribute check. `read_on_startup=False`, so the value is unknown until read [V].
- Also present: `start_up_current_level`, `start_up_color_temperature`, on/off transition numbers [V].
- The light platform reads the colour cluster Options attribute to learn whether `execute_if_off` is supported, and orders colour commands before or after turn-on accordingly [V].
- When `brightness is None` and the light was turned off with a transition (or a colour is supplied while off), ZHA restores the stored off-brightness via `move_to_level_with_on_off`. That bypasses OnLevel [V]. Whether the common plain-`on` path sends a plain `on`: not verified.
- `zha.issue_zigbee_cluster_command` for cmd 0x42 and raw level and colour commands: [M]. Whether it raises on a rejected command, and whether zigpy's level commands carry the options fields: not verified.

### 4.5 Matter (matter.js `@matter/model` latest, plus HA core)

- OnOff: `OnWithTimedOff` (cmd 0x42) has conformance `LT`. `OnTime` and `OffWaitTime` are uint16, max 65534 (tenths of a second) [V]. `StartUpOnOff` exists [V].
- Level Control: `OnLevel` (0x11) is uint8, RW, conformance mandatory, constrained to min to max level, nullable (null = previous). `StartUpCurrentLevel` has conformance `LT`. Options attribute is mandatory. Every Move/Step command carries `OptionsMask` and `OptionsOverride`, which allows a per-command `ExecuteIfOff` override. The `ExecuteIfOff` bit has conformance `LT | OO` [V].
- Color Control: Options attribute mandatory; colour commands also carry options mask and override. The only startup attribute is `StartUpColorTemperatureMireds`. There is no on-colour [V].
- Other Matter timers: Valve Configuration and Control `Open` with optional `OpenDuration` (min 1 s), plus `AutoCloseTime`, `DefaultOpenDuration`, `RemainingDuration`. Door Lock `AutoRelockTime` (persistent setting). Energy EVSE `EnableCharging` (fields not checked) [V]. Window Covering has no timer elements. Closure Control has `CountdownTime`, a status attribute only. No generic Timer cluster (`SetTimer`, `AddTime`) in this matter.js version [V].
- HA core Matter: a `number` entity for `on_level` (0 to 255, 255 maps to null) is created when the `LevelControl.OnLevel` attribute is present [V]. HA's Matter light with no brightness sends `OnOff.On`, so OnLevel applies; with brightness it uses its brightness path [V].
- Which Matter device types include `LT` (for example plain on/off plugs): not verified. This is the likely coverage gap for plugs [I].

### 4.6 Shelly Gen2+ (docs fetched 2026-10-23)

- `Light.Set` accepts `id`, `on`, `brightness`, `transition_duration`, `toggle_after` (flip-back timer, requires `on`) and `offset`. At least one of `on`, `brightness` or `offset` is required [V].
- `RGB.Set`, `RGBW.Set` and `CCT.Set` also accept `toggle_after`; CCT also takes `ct` [V].
- So on+brightness+timer can go in one RPC for Shelly lights. The "two commands" caveat applies only to Zigbee and Matter [V].
- Light config: `initial_state` (power-on), `auto_on` / `auto_off` with delays (persistent timers), `transition_duration`, `min_brightness_on_toggle` (a floor applied on toggle only), `night_mode.brightness` (a cap inside a time window), `button_presets`. There is no fixed default on-level [V].
- Docs do not say what a brightness-only `Set` does when the output is off [V as a gap].
- `Switch.Set toggle_after` and the Gen1 relay timer param: [M]. Gen1 not checked. The aioshelly access route and its pacing: not checked.

### 4.7 Naming and collision check

- `set_attributes` beat `set_look` in a structured debate. Decisive reasoning: the UI label is decoupled from the slug, so brevity matters little and misreading costs more; consistency with the user's Hue component has real value [I].
- Domain: `direct_control` was the first verdict; it flipped to `device_side` after the user pointed out that "device-side" means the opposite of "HA-side", which includes the Hue bridge, and that core registers the bridge as a device [V]. The flip came from an inconsistency in my reasoning, not pushback alone. `direct_control` remains a defensible runner-up if call-site readability is valued over precision.
- Scope limit of the name: it fits only features that run on the device or bridge. HA-dependent features would make the name wrong [I].
- Candidates also considered and not chosen: `on_device`, `device_features`, `native_features`, `device_extras`, `onboard` (prefix of core `onboarding`), `firmware_features`, `passthrough` (misleading) [V on core collisions only].
- Collision check results: no core domain named `device_side` [V]. HACS default dataset (3,984 integration repos): no hit for `device_side` or `deviceside` [V]. HA brands repo `custom_integrations` (4,025 entries): absent [V]. Web search: nothing relevant [V].
- The authenticated GitHub code search (`gh search code '"domain": "device_side"' --filename manifest.json`) could not be run in the sandbox. The user reported afterwards that the check came back clean; assumed to include that search, so confirm.
- Name forms: domain and directory `device_side`; UI title "Device Side"; prose "device-side" (adjective) or "device side" (noun phrase).

## 5. Design rules agreed

- Dispatch key is the entity registry `platform`. Z2M entities appear as `mqtt`, so also check device identifiers (the `zigbee2mqtt_` prefix) [M]. Matter-paired Hue bulbs appear as `matter` [M].
- Result states: `unsupported` (no adapter or a pre-check failed), `rejected` (explicit device or bridge error), `sent` (accepted, unconfirmed), `confirmed` (accepted and a read-back shows the timer or value). Callers needing safety can require `confirmed`.
- Read-back: `OnTime` and `OnLevel` are readable on ZHA and Matter; Z2M has no clean read-back for `on_time`; Shelly and Hue acceptance is a strong signal, so read-back matters less [M].
- Other `turn_on` data (brightness, colour): for Zigbee and Matter, send via the normal `<domain>.turn_on` first, then the timed-on command, because the timed-on commands ignore brightness [M]. Shelly can do it in one call [V].
- Reuse `light.turn_on` field names (`brightness`, `color_temp_kelvin`, `hs_color`, `rgb_color`, `xy_color`).
- Lead every description with "without changing on/off state" for `set_attributes`, and say that it also works while the light is on.
- One small adapter file per platform that needs internals (Shelly, Matter, Hue), with guarded imports and a smoke test per HA release [I].
- Keep your own concurrency low on Hue (1 or 2 lights at a time) so core's light commands interleave. aiohue's cap of 3 is shared with core's commands, and a 30-light call with several requests each can queue ahead of manual commands [I].
- Hue timer caveats to document: the timer lives on the bridge, so a bulb that is unreachable at expiry stays on; a manual off may not cancel it (to test; a `cancel_delayed_toggle` action covers it if not); repeat calls would stack unless each timer has a deterministic name that is replaced on each call [I].
- Enforce support in the handler. The UI entity filter is only a convenience.

## 6. Corrections to earlier claims (do not repeat these errors)

1. aiohue `request()` takes any path and is not `clip/v2`-prefixed; aiohue uses its own session, not HA's.
2. aiohue does wrap `behavior_instance` (`BehaviorInstanceController`).
3. aiohue v2 has no rate limiter, only a concurrency cap of 3. V1's throttler is dead code. The "10 commands per second" figure is Signify documentation from memory.
4. Z2M `mqtt.publish` returns no per-call result (earlier advice to "try it and check the result" was wrong).
5. Shelly `Light.Set` accepts brightness and `toggle_after` in one call.
6. Removing or adding services at runtime via a toggle conflicts with the docs ("register in `async_setup`"). Gate in the handler instead.
7. "Device-side" was wrongly treated as excluding the Hue bridge; the bridge is a device in HA's own registry.
8. The first domain verdict (`direct_control`) used a generous reading for "direct" but not for "device-side". Corrected.

## 7. Open items, in priority order

1. **Hue timed turn-on.** Can `behavior_instance` express a one-shot "on, then off after N seconds"? Read aiohue's `BehaviorInstance` model and the Hue v2 `behavior_script` schema, then bench on a real bridge: timer start semantics (on create, on enable, or via `start`), instance count limit, whether instances appear in the Hue app, cleanup, and what happens when the bulb is unreachable at expiry. This decides whether Hue is in scope for timed turn-on. If not, Hue reports `unsupported` and users pair safety-critical bulbs to Z2M, ZHA or Matter.
2. **Shelly bench.** Does a brightness-only `Light.Set` (or RGB, RGBW, CCT) with the output off turn it on or store the level? Also confirm `Switch.Set toggle_after`, check Gen1, find the aioshelly access route from the config entry, and check aioshelly pacing.
3. **Z2M failure surfacing.** How does Z2M report a failed `/set` (log topic? bridge/logging?) and is there any read-back for `on_time`? Decides how far Z2M timed turn-on can go beyond `sent`.
4. **ZHA.** Does `issue_zigbee_cluster_command` raise on a rejected command? Does zigpy's `move_to_level` carry `options_mask` and `options_override`? Does the common ZHA `turn_on` path send plain `on`, so OnLevel applies? How to read `OnTime`.
5. **Matter.** Which device types include the `LT` feature (plain plugs?). How to reach `matter_client` from the entry. Can a raw `MoveToLevel` with an options override be sent via `send_device_command`? Pacing.
6. **Hue.** Confirm on real bulbs that brightness and colour set while off are stored and applied on the next turn-on (the user's existing build suggests yes).
7. **Cancel semantics per device.** Does a plain `turn_off` or `turn_on` cancel a running device timer? Only one source comment exists (Tuya devices).
8. **Frontend behaviour.** Does the `integration` filter match the entity platform? Do translations override `async_set_service_schema` text? (Both [M].)
9. **Dispatch details.** Verify the Z2M device identifier prefix and the entity platform of Matter-paired Hue bulbs.
10. **Collision.** Confirm the authenticated GitHub code search result.
11. **Test device matrix.** Choose real devices per platform (a Zigbee bulb and plug each via Z2M and ZHA, a Shelly dimmer and relay, Hue bulbs, a Matter bulb and plug).
12. **Minimum HA version, repo scaffolding choices** (for example whether to restrict to a single config entry, which the multi-entry toggle conflict would suggest; the manifest key for that is [M]).

## 8. Suggested starting point for planning

1. Define the adapter interface and the per-entity result schema (states, adapter, `clamped_to`) first. Everything else hangs on it.
2. Build the Matter OnLevel adapter first. It needs only the existing `number` entity, so it is the cheapest end-to-end slice.
3. Then Z2M and ZHA timed turn-on and OnLevel, which use public services.
4. Then Shelly, once item 2 above is closed.
5. Hue last and provisional, once item 1 above is closed.
6. Scaffolding: `custom_components/device_side`, manifest, `services.yaml`, `strings.json` and translations, `icons.json`, hassfest and HACS validation in CI. Hassfest warns when a custom domain collides with a built-in one [V from a core issue thread].
7. Tests: reuse the mock-bridge approach in Appendix A for any aiohue-facing code.

## 9. Source index

HA core (github.com/home-assistant/core, HEAD 2026-10-23):

- `homeassistant/helpers/service.py`: `async_set_service_schema`, `async_get_all_descriptions`, `SERVICE_DESCRIPTION_CACHE`, `description_placeholders`
- `homeassistant/helpers/selector.py`: `EntityFilterSelectorConfig`, `EntitySelector.__call__`
- `homeassistant/components/hue/`: `manifest.json` (pins `aiohue==4.9.0`), `bridge.py`, `v2/light.py`, `v2/device.py`
- `homeassistant/components/matter/number.py` (on_level) and `light.py` (`async_turn_on`)
- `homeassistant/components/*/services.yaml` and `manifest.json` (naming and `iot_class` counts)

aiohue (github.com/home-assistant-libs/aiohue, tag 4.9.0): `aiohue/v2/__init__.py`, `aiohue/v1/__init__.py`, `aiohue/v2/controllers/lights.py`, `aiohue/v2/controllers/config.py`, `aiohue/v2/models/feature.py`.

zigbee-herdsman-converters (github.com/Koenkk/zigbee-herdsman-converters, HEAD): `src/converters/toZigbee.ts` (`on_off` ~lines 17 to 45, `level_config` ~740 to 867, `light_color_options` ~378, light converter ~1253 to 1400), `src/lib/exposes.ts` (`withLevelConfig` ~409, `color_options` ~1132), `src/lib/tuya.ts` (`on_off_countdown` ~3290), `src/lib/modernExtend.ts` (lock ~1636).

zigpy/zha (github.com/zigpy/zha, HEAD): `zha/application/platforms/number/__init__.py` (`OnLevelConfigurationEntity`), `zha/application/platforms/light/__init__.py` (`execute_if_off` handling and off-with-transition path).

matter.js (npm `@matter/model`, latest on 2026-10-23): `dist/esm/standard/elements/` files `on-off.element.js`, `level-control.element.js`, `color-control.element.js`, `valve-configuration-and-control.element.js`, `door-lock-cluster.element.js`, `window-covering-cluster.element.js`, `closure-control.element.js`.

Shelly Gen2 API docs (fetched 2026-10-23): https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/Light and the `RGB`, `RGBW`, `CCT` pages at the same path.

HA developer docs: https://developers.home-assistant.io/docs/dev_101_services (publishing under the domain, register in `async_setup`); https://developers.home-assistant.io/docs/creating_integration_manifest/ (domain unique and unchangeable); developer blog post on service translation (HA 2023.8).

Collision data: HACS dataset https://data-v2.hacs.xyz/integration/data.json (3,984 repos); HA brands repo https://github.com/home-assistant/brands (`custom_integrations`, 4,025 entries).

## Appendix A: aiohue mock-bridge test harness

Used to measure concurrency, rate, retry timing and v1-style response handling against the
real `HueBridgeV2` class. Create a self-signed cert first
(`openssl req -x509 -newkey rsa:2048 -nodes -keyout k.pem -out c.pem -days 1 -subj /CN=127.0.0.1`),
then install aiohue (`pip install -e . --break-system-packages` from a checkout at tag 4.9.0).

```python
import asyncio, ssl, time
from aiohttp import web
from aiohue.v2 import HueBridgeV2

state = {"inflight": 0, "max": 0, "times": [], "n429": 0, "mode": "ok"}

async def handler(req):
    state["times"].append(time.monotonic())
    if state["mode"] == "429" and state["n429"] < 3:
        state["n429"] += 1
        return web.Response(status=429, text="busy")
    state["inflight"] += 1
    state["max"] = max(state["max"], state["inflight"])
    await asyncio.sleep(0.2)
    state["inflight"] -= 1
    if req.path.startswith("/api/"):  # v1-style payload
        return web.json_response([{"success": {"/schedules/1": "x"}}])
    return web.json_response({"data": [{"id": "abc"}], "errors": []})

async def main():
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain("c.pem", "k.pem")
    await web.TCPSite(runner, "127.0.0.1", 8443, ssl_context=ctx).start()
    b = HueBridgeV2("127.0.0.1:8443", "key")

    t0 = time.monotonic()
    await asyncio.gather(*[
        b.request("put", f"clip/v2/resource/light/{i}", json={"on": {"on": False}})
        for i in range(12)
    ])
    print("burst: max in-flight", state["max"], "wall", round(time.monotonic() - t0, 2))

    state.update(times=[], mode="429", n429=0)
    t0 = time.monotonic()
    await b.request("get", "clip/v2/resource")
    print("429 attempt times:", [round(x - t0, 2) for x in state["times"]])
    state["mode"] = "ok"

    try:
        await b.request("post", "api/key/schedules", json={"name": "t"})
    except Exception as e:
        print("v1 via request() fails:", type(e).__name__, e)
    async with b.create_request("post", "api/key/schedules", json={"name": "t"}) as r:
        print("v1 via create_request():", r.status, await r.json())

    await b.close()
    await runner.cleanup()

asyncio.run(main())
```

Results on 2026-10-23: max in-flight 3; 12 requests in 0.82 s (14.6 req/s); 429 retry gaps
0.5, 0.76, 1.0 s; `request()` raised `AttributeError: 'list' object has no attribute 'get'`
on the v1-style response; `create_request()` returned status 200 with the raw body.
