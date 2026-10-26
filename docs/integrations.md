# Integrations

One section per integration, each on the same template: what Device Side talks to, how a target
entity becomes a device address, notes per action, and sharp edges.

## Shelly

### What it talks to

Shelly Gen2 and later devices (Plus, Pro, Gen3, Gen4), through the RPC connection the core
`shelly` integration already holds open. Device Side adds no connection of its own and needs no
credentials beyond the ones the Shelly integration was set up with. Gen1 devices (CoIoT) have no
flip-back timer in the API Device Side uses, and are reported `unsupported` with detail
`gen1_unsupported`.

### How targets resolve

An entity belongs to this integration when its entity registry entry comes from `shelly`. The RPC component and
instance come from the entity's unique ID, which the Shelly integration writes as
`<mac>-<key>`:

| Key | RPC component (capability) | Entity domains | In scope | `light.turn_on` fields it can take |
|---|---|---|---|---|
| `switch:N` | `Switch` | `switch`, or `light` for a relay set to "light" | yes | none |
| `light:N` | `Light` | `light` | not yet | `brightness`, `transition` |
| `cct:N` | `CCT` | `light` | not yet | `brightness`, `transition`, `color_temp_kelvin` |
| `rgb:N` | `RGB` | `light` | not yet | `brightness`, `transition`, `rgb_color` |
| `rgbw:N` | `RGBW` | `light` | not yet | `brightness`, `transition`, `rgb_color` |
| `rgbcct:N` | `RGBCCT` | `light` | not yet | `brightness`, `transition`, `color_temp_kelvin`, `rgb_color` |

Any other Shelly entity (virtual booleans, scripts, circuit breakers) has no flip-back timer and
returns `unsupported` with detail `not_addressable`. Shelly has no device-side groups, so a light
group helper over Shelly lights is expanded and each member gets its own command.

A `switch_as_x` light over a Shelly switch is served as that switch: the helper forwards on/off
unchanged, so the device receives the switch's own `Switch.Set`, and the result is keyed on the
light's entity ID. Light fields sent to such a light return `unsupported` with detail
`fields_not_supported`. An inverted helper returns `inverted_wrapper`, and a helper wrapping
another helper returns `not_addressable`. This holds on every integration, not only Shelly.

### `turn_on_for`

One `<Component>.Set` call with `on: true` and `toggle_after` set to the duration, so the device
runs the timer and turns itself off even if Home Assistant is offline. Light fields travel in the
same call, translated as the core Shelly light does: brightness to a 0 to 100 percent value,
`transition` to `transition_duration` (at least 0.5 s), and on `RGBCCT` the mode is switched to
`cct` or `rgb` to match the field sent. A color temperature outside the light's range is clamped
to the range the entity reports.

After the `Set`, Device Side reads `<Component>.GetStatus`. When the output matches and the device
reports a running timer (`timer_duration`), the result is `confirmed`. Otherwise it is `sent`, with
detail `timer_not_reported` (the device answered without a timer) or `readback_failed` (the
read-back call itself failed). Either way the `Set` was accepted.

Only relays are in scope so far, whether HA shows them as a switch or a light. A dimmer, CCT or RGB
light returns `unsupported` with detail `capability_not_tested` until someone tests one. A light
field (brightness, color, transition) on a light returns `unsupported` with detail
`fields_not_tested` rather than being dropped silently; a field the component can't take at all
returns `fields_not_supported`. Fields sent to a `switch` entity are
ignored and the result says so with detail `light_fields_ignored`.

### `turn_off_for`

The same `Set` with `on: false`: the device turns off now and turns itself back on after the
duration. Light fields are not accepted.

### Cancelling

Send a regular `turn_on` or `turn_off`: either cancels the flip-back timer. A `turn_on_for` or
`turn_off_for` during a timer replaces it, so the countdown restarts at the new duration.

Tested on Gen3 and Gen4 relays (firmware 2.0.1) by direct RPC. A wall switch wired to the device's
input was not tested, and what it does may depend on the input mode.

### Sharp edges

- **Timer limits are the device's.** The device accepts any duration over 0 s up to 7 days
  (604800 s) and keeps it to 0.01 s. Device Side rounds every duration to 10 ms with a 50 ms
  floor, for all integrations; a duration under 50 ms or over 7 days is clamped and the result
  carries `clamped_to`.
- **The timer is the device's, not Home Assistant's.** Any on or off command cancels it, whatever
  sent it: Home Assistant, the Shelly app or another integration (see Cancelling).
- **Colors other than RGB.** `hs_color` and `xy_color` are refused rather than converted, because
  the conversion depends on the component's color mode. Send `rgb_color` or `color_temp_kelvin`.
- **Only relays are in scope.** `Light`, `CCT`, `RGB`, `RGBW` and `RGBCCT` document `toggle_after`
  the same way as `Switch`, but they are different firmware and no hardware run has covered them,
  so they are refused until a tester reports one.

## Zigbee2MQTT

### What it talks to

Zigbee devices through the [Zigbee2MQTT](https://www.zigbee2mqtt.io/) bridge, via the core `mqtt`
integration. Device Side publishes directly to the Z2M device topic; Z2M translates the payload to
a Zigbee cluster command (`OnWithTimedOff`) and forwards it to the device. The timer therefore
runs on the device, not on the bridge or in Home Assistant.

Only entities Z2M registered via MQTT discovery are served; Z2M devices set up in any other way
are not detected.

### How targets resolve

An entity belongs to this integration when its device carries the identifier
`("mqtt", "zigbee2mqtt_<address>")` that Z2M writes during MQTT discovery. The address is
the device's IEEE address for individual devices.

Device Side builds the command topic from the identifier: `zigbee2mqtt/<address>/set`. This assumes
the default Z2M base topic; see Sharp edges if you changed it.

The topic uses the IEEE address, which Z2M accepts alongside the `friendly_name`, so it still
reaches a renamed device (`resolveEntity` in
[`lib/zigbee.ts`](https://github.com/Koenkk/zigbee2mqtt/blob/master/lib/zigbee.ts) looks the
segment up with `getDevice` in
[`lib/util/settings.ts`](https://github.com/Koenkk/zigbee2mqtt/blob/master/lib/util/settings.ts),
which matches the IEEE-keyed `devices` map before `friendly_name`).

### `turn_on_for`

For **light entities without fields**: publishes `{"state":"ON","on_time":<seconds>}` to the
device topic. Z2M translates `on_time` (in seconds, rounded to 1 decimal place) to the Zigbee
`OnWithTimedOff` command.

For **light entities with fields** (`brightness`, `color_temp_kelvin`, `rgb_color`, `hs_color`,
`xy_color`, `transition`): calls `light.turn_on` first (blocking) so HA's MQTT light entity
handles the color mode, sets the attributes through its own protocol, then publishes
`{"state":"ON","on_time":<seconds>}` separately. The two-step approach keeps HA's light state in
sync and delegates attribute handling to the integration that knows the device's capabilities.

Lights only. Zigbee plugs and switches (`switch`) are unsupported on Zigbee2MQTT and ZHA alike: few
honor `OnWithTimedOff` (IKEA's are moving to Thread, and Sonoff and Tuya run their own countdowns),
so a timer sent to one usually does nothing. If you have one that does, open an issue.

Returns `sent` (fire-and-forget). Z2M does not report the timer back; confirmation is not
available.

### Groups

Z2M group entities are passed through to the adapter as a single target when `native_groups` is
supported. The adapter publishes to the group's command topic. Detection of group entities in the
HA registry needs verification on hardware; see the rig verification list.

### Cancelling

Send a regular `turn_on` or `turn_off` through Home Assistant. This publishes `{"state":"ON"}` or
`{"state":"OFF"}` to the device topic, which Z2M forwards to the device. Whether the Zigbee device
cancels its running `OnWithTimedOff` timer on a plain `On` command depends on the device's
firmware. Most Z2M-supported lights cancel the timer on any state change.

### Sharp edges

- **Duration limits.** Zigbee `on_time` is a uint16 in tenths of a second, so the maximum is
  65534 tenths = 6553.4 s (about 1.8 hours). A duration over 6553.4 s is clamped and the result
  carries `clamped_to`. Durations under 50 ms are floored to 50 ms.
- **Custom base topic.** If Z2M is configured with a base topic other than `zigbee2mqtt`, the
  command topic Device Side builds will be wrong and the publish will reach no device. Check your
  Z2M configuration; there is no workaround in v1.
- **No confirmation.** Z2M's MQTT interface does not synchronously confirm the timer started.
  The result is always `sent`, never `confirmed`, regardless of whether the device accepted the
  command.

## ZHA

### What it talks to

Zigbee devices on the core `zha` integration's own coordinator. Device Side calls ZHA's
`zha.issue_zigbee_cluster_command` action, which sends the Zigbee `OnWithTimedOff` command to the
device. The timer runs on the device.

### How targets resolve

An entity belongs to this integration when its entity registry entry comes from `zha`. The IEEE
address and endpoint are parsed from the unique ID, which ZHA writes as `{ieee}-{endpoint_id}` for
a light. An entity with a longer unique ID on the same endpoint (a quirk's extra entity, such as a
child lock) is refused with `not_addressable`, so a timer never lands on the wrong entity.

ZHA group entities return `group_not_supported` for now; target the member lights instead.

### `turn_on_for`

Sends `OnWithTimedOff` (OnOff cluster `0x0006`, command `0x42`) with `on_off_control: 0`,
`on_time` in tenths of a second and `off_wait_time: 0`. With a light field, Device Side first calls
`light.turn_on`, then sends the timer.

ZHA raises when the device can't be reached or answers with a failure status, and that target is
`rejected`. Otherwise Device Side reads the OnOff (`0x0000`) and OnTime (`0x4001`) attributes
straight back in one uncached request. OnTime counts down live and a new timer replaces an old one,
so the result is `confirmed` when the device reads on and OnTime is above 0, at most the requested
tenths, and no more than 3 s under them. Otherwise it is `sent`, with detail `not_on` (the device
reads off), `timer_not_reported` (OnTime holds some other value) or `readback_failed` (the read
itself failed).

Lights only, with `brightness` and `color_temp_kelvin` as the fields, until more are tested on
hardware. Zigbee plugs and switches are unsupported, as on Zigbee2MQTT: the one tested, a Tuya
TS011F, stores OnTime as its own countdown and never switches on, so it reads back `not_on`.

### Cancelling

Send `light.turn_off`. Turning the light on again does not cancel the timer on the one bulb tested
(below), so don't rely on it. A second `turn_on_for` replaces the first.

### Tested behavior

How a device treats a running timer is up to its firmware, so this holds only for the bulb it was
measured on: a Philips Hue LTA004, firmware `0x01001416`, on Home Assistant 2026.10.2. Other
devices may differ.

- **The timer is readable.** `OnTime` (attribute `0x4001`) counts down in tenths of a second
  (a 30 s timer read 290, 250, 200 and 99 at 1, 5, 10 and 20 s), and the bulb turned off at 30.2 s.
  `OnTime` reads 0 when no timer is running.
- **A new timer replaces the old one,** in both directions: 60 s then 20 s left 20 s; 20 s then
  60 s left 60 s.
- **`light.turn_on` does not cancel it.** A plain `light.turn_on` (ZHA sends `On`) and one with
  `brightness` (ZHA sends `move_to_level_with_on_off`) both left the timer running, and the bulb
  still turned off on time.
- **`light.turn_off` cancels it.** After off then on, `OnTime` read 0.

### Sharp edges

- **Admin only.** `zha.issue_zigbee_cluster_command` is an admin-only action, and Device Side
  passes the caller's identity through to it. A call made as a non-admin user is `rejected` with
  detail `admin_required`. Automations run without a user, so they pass.
- **Duration limits.** `on_time` is a uint16 in tenths of a second, so the maximum is 6553.4 s
  (about 1.8 hours). A longer duration is clamped and the result carries `clamped_to`.
- **Turning the light on keeps the timer.** On the tested bulb, someone who turns the light on or
  changes its brightness during a timer still sees it switch off when the timer ends.
- **Home Assistant can show the wrong state.** For 1.5 s after `light.turn_off`, ZHA ignores a
  light's "on" report and never replays it. On the tested bulb, `turn_on_for` sent 0.1 s after
  `light.turn_off` lit the bulb and started its timer, while Home Assistant showed it `off`. That's
  why the timer belongs on the device: the bulb still switches itself off when the timer ends,
  whereas a timer in Home Assistant, such as an automation that turns the light off once it has
  been on for 10 minutes, would never fire.

## Matter

### What it talks to

Matter devices (Thread, Wi-Fi, Ethernet), through the connection the core `matter` integration
holds open to python-matter-server. Device Side adds no connection of its own and needs no
credentials beyond those the Matter integration was set up with.

### How targets resolve

An entity belongs to this integration when its entity registry entry comes from `matter`. The
node ID and endpoint ID are parsed from the entity's unique ID, which the Matter integration
writes as `{fabric_hex16}-{node_hex16}-{postfix}-{endpoint_id}-{key}-{cluster_id}-{attr_id}`.

Device Side requires the OnOff cluster's Lighting (LT) feature bit to be set on the endpoint.
Lighting-category device types (OnOffLight, DimmableLight, ColorTemperatureLight,
ExtendedColorLight) carry this feature; a plain on/off plug typically does not. An entity whose
endpoint lacks the LT bit returns `unsupported` with detail `no_lt_feature`.

Switch-domain entities (plugs) are out of scope for now: the LT feature behavior on plugs is not
yet confirmed on hardware.

### `turn_on_for`

Sends `OnOff.Commands.OnWithTimedOff(onOffControl=0, onTime=<tenths>, offWaitTime=0)` to the
device via python-matter-server. The device turns on and turns itself off after the duration
without needing Home Assistant to remain running.

`onTime` is the duration in 1/10-second units (`round(duration_s * 10)`). `onOffControl=0` means
the command is accepted whether the light is currently on or off. `offWaitTime=0` places no
restriction on retriggering.

After the command, Device Side reads back the `OnOff.OnTime` attribute. If it is non-zero (the
countdown is running), the result is `confirmed`. If it is 0 or the read-back fails, the result
is `sent` with detail `timer_not_reported` or `readback_failed`.

Light fields (`brightness`, `color_temp_kelvin`, etc.) are out of scope for now. When a tester
reports them, the adapter will send a `light.turn_on` first to set color and brightness, then
follow with `OnWithTimedOff`.

### Cancelling

Send a regular `light.turn_on` or `light.turn_off`: either cancels the timed-off (the Matter
spec says `On` and `Off` commands clear `OnTime`). A second `turn_on_for` during a timer replaces
it.

### Sharp edges

- **Timer limits are 0.1 to 6553.4 s.** `OnWithTimedOff.onTime` is a uint16 in 1/10-second
  units; the maximum of 65534 tenths corresponds to 6553.4 s. Device Side rounds durations to 10
  ms with a 50 ms floor; a duration outside the range is clamped and the result carries
  `clamped_to`.
- **The Lighting (LT) feature must be present.** The command is rejected at the device if the
  endpoint lacks this feature. Device Side refuses early with `no_lt_feature` rather than
  forwarding a command the device will ignore.
- **duck-typed attribute descriptor.** Device Side checks the LT feature by reading the OnOff
  cluster's FeatureMap attribute from the cached node data, using a minimal attribute descriptor
  class rather than importing chip.clusters. This should work with any python-matter-server
  version that exposes endpoint.get_attribute_value. Verified assumption: to confirm on hardware.

## Hue

### What it talks to

A Hue Bridge v2 or Bridge Pro, through the aiohue connection the core `hue` integration holds open.
Device Side adds no connection or credentials of its own. Reads come from aiohue's copy of the
bridge's state, which the bridge's event stream keeps current, so a read sends nothing to the bridge.
A v1 bridge is refused with `bridge_v1`.

### How targets resolve

An entity belongs to this integration when its entity registry entry comes from `hue`. Its unique
ID is the bridge's resource ID: a light, a scene, or the `grouped_light` of a room or zone, which
the Hue integration shows as one light marked `is_hue_group`. A room's lights are the ones the
bridge lists for it that have a light entity in Home Assistant.

### `set_attributes`

One write per light, with brightness, color temperature or color and never `on`, so a light that
is off stays off and comes on with the new settings. A room is written light by light, with one
result per light, because a write to the room's `grouped_light` misses the lights that are off.

`brightness` converts to Hue's percent as the Hue integration does; `color_temp_kelvin`
is clamped to the light's range; colors convert to xy. `min_brightness` and `max_brightness` are
percent and move the brightness the bridge last stored into that range, so they work while off; a
light already inside it is `confirmed` with `within_limits` and nothing is written. An explicit
`brightness` overrides both.

A field a light can't take (color on a white bulb) is dropped and the result is `sent` with
`fields_dropped`. A light that can take none of them is `unsupported` with `fields_not_supported`.

### `get_attributes`

Returns `brightness` (0 to 255), `color_temp_kelvin`, `xy_color`, `rgb_color` and `hs_color` under
Home Assistant's names, for lights that are off too. `color_temp_kelvin` is left out while a light
is in color mode, since the value the bridge keeps is stale.

A room returns its own row, then one per light marked `member_of` the room. While any light is on,
the room's brightness is the bridge's (the average of the lights that are on) and its color
temperature and color average the lights that are on, matching what the Hue integration shows for
the room. With every light off the bridge reports nothing useful, so the room row averages all of
its lights.

### `set_scene`

Reads the scene from aiohue on every call, so edits made in the Hue app apply, then writes each
light's brightness, color temperature and color as a light write. The Hue API has no recall that
leaves lights off, which is why it isn't one. `on: true` is dropped so nothing turns on; `on: false`
is sent, as a recall would. Gradients, effects and dynamics are not written, so a dynamic scene
sets its first frame.

One failing light doesn't stop the rest: the result is `sent` with `some_lights_failed`, or
`rejected` if every light failed. All-Day (smart) scenes are `unsupported` with `smart_scene`;
a scene the bridge no longer has is `rejected` with `scene_not_found`.

### Sharp edges

- **One write per light.** `set_scene` writes a scene's lights one after another; an 8-light scene
  takes under a second. The bridge refuses more than 3 requests at once and aiohue retries, so a
  much larger scene may take longer.
- **Lights with no entity in Home Assistant are skipped.** A light in a room whose light entity was
  deleted gets no write from `set_attributes` on the room and no row from `get_attributes`, though
  `set_scene` writes it. A disabled entity still counts: its light is written and reported.
