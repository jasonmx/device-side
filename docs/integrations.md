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
`("mqtt", "zigbee2mqtt_<address>")` that Z2M writes during MQTT discovery. For a device, the
address is its IEEE address and the command topic is `zigbee2mqtt/<ieee>/set`. For a group, the
address is `<encoded base topic>_<group ID>`, the base topic written as character codes with no
separator (`1221051039810110150109113116116` for `zigbee2mqtt`; `getEncodedBaseTopic` in
[`lib/extension/homeassistant.ts`](https://github.com/Koenkk/zigbee2mqtt/blob/master/lib/extension/homeassistant.ts)),
and the command topic is `zigbee2mqtt/<group ID>/set`. Both assume the default Z2M base topic; see
Sharp edges if you changed it.

The topic uses the IEEE address, which Z2M accepts alongside the `friendly_name`, so it still
reaches a renamed device (`resolveEntity` in
[`lib/zigbee.ts`](https://github.com/Koenkk/zigbee2mqtt/blob/master/lib/zigbee.ts) looks the
segment up with `getDevice` in
[`lib/util/settings.ts`](https://github.com/Koenkk/zigbee2mqtt/blob/master/lib/util/settings.ts),
which matches the IEEE-keyed `devices` map before `friendly_name`). A group's ID topic likewise
survives a rename: `resolveEntity` falls back to `getGroup`, which matches the ID-keyed `groups` map
before `friendly_name`.

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

**State read-backs.** Z2M publishes no state for a timed command (the `on_time` branch of `on_off`
in zigbee-herdsman-converters returns none), and Z2M turns reporting off for Hue bulbs on purpose,
so without help Home Assistant shows a light that is on as off, or one that turned itself off as
still on. Device Side asks Z2M to read the state back by publishing `{"state":""}` to
`zigbee2mqtt/<address>/get`:

- 1 s after the timer starts, without fields only (with fields, `light.turn_on` already updated
  the state);
- at the end of the timer plus 1 s, and again plus 5 s or 2% of the duration, whichever is
  longer, in case the bulb's clock runs slow on a long timer.

A new call on the same entity replaces its pending reads. The reads never change the result, and a
failed read is logged at debug level. We don't use or recommend configuring attribute reporting
instead: it would have to be set up on every bulb, and Z2M's maintainers turned it off for Hue to
avoid reports that conflict with its optimistic state.

### Groups

A Z2M group entity is one target: Device Side publishes once to the group's ID topic, and Z2M
sends one `OnWithTimedOff` to the Zigbee group, so every member starts its timer at once. With
fields, `light.turn_on` goes to the group entity first, as for a device. The state read-backs go
to the group's own topic, `zigbee2mqtt/<group ID>/get`; Z2M rebuilds the group's state from its
members' answers and shows it off only once every member is off.

### Cancelling

Send a regular `turn_on` or `turn_off` through Home Assistant. This publishes `{"state":"ON"}` or
`{"state":"OFF"}` to the device topic, which Z2M forwards to the device. Whether the Zigbee device
cancels its running `OnWithTimedOff` timer on a plain `On` command depends on the device's
firmware. Most Z2M-supported lights cancel the timer on any state change.

### Sharp edges

- **Duration limits.** Zigbee `on_time` is a uint16 in tenths of a second, so the maximum is
  65534 tenths = 6553.4 s (about 1.8 hours). A duration over 6553.4 s is clamped and the result
  carries `clamped_to`. Durations under 50 ms are floored to 50 ms.
- **Custom base topic.** A group's identifier carries its base topic, so a group on any base
  topic other than `zigbee2mqtt` is refused as `not_addressable`. A device's identifier doesn't,
  so for a device the command topic is wrong and the publish reaches nothing, while the result
  still says `sent`. Check your Z2M configuration; there is no workaround yet.
- **A device named after a group's ID.** Z2M accepts a purely numeric friendly name and looks up
  devices before groups, so a device whose friendly name is exactly a group's ID takes that
  group's command. Don't name a device with a bare number.
- **Restart during a timer.** Pending state reads are lost when Home Assistant restarts or Device
  Side unloads, so the light's state stays stale until the device next reports or is next
  commanded.
- **Zigbee traffic.** Each call adds up to three Zigbee reads per target, spread over the timer.
  A group read is one groupcast that every member answers.
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

There is no way to stop the timer and keep the light on: on the tested bulb, every call that ends
it early also turns the light off. Keeping it on means off, then on, which blinks.

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
- **Nothing cancels it with the light left on.** Writing `OnTime` = 0 through
  `zha.set_zigbee_cluster_attribute` (ZCL write status `SUCCESS`) and sending `OnWithTimedOff` with
  `on_time: 0` each ended a running timer as if it had expired: the bulb turned off within 0.3 s.
  `turn_on_for` with `duration: 0.05` is clamped to 0.1 s and did the same.
- **Writing `OnTime` resets the remaining time.** Writing 100 with 15.6 s left set it to 10 s, and
  the bulb turned off 10 s later.
- **With no timer running, writing `OnTime` = 0 changes nothing,** whether the bulb is on or off.

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

The fields, units and names are hue_dimmer's, so its calls work unchanged under `device_side`.
`brightness` is percent, as Hue stores it; `color_temp_kelvin` is clamped to the light's range;
colors convert to xy, and given more than one, `rgb_color` wins, then `hs_color`, then `xy_color`.
`min_brightness` and `max_brightness` are percent and move the brightness the bridge last stored
into that range, so they work while off; a light already inside it is `unchanged` with
`within_limits` and nothing is written. An explicit `brightness` overrides both. A `0` leaves
`min_brightness`, `max_brightness` or `color_temp_kelvin` unset.

A field a light can't take (color on a white bulb) is dropped and the result is `sent` with
`fields_dropped`. A light that can take none of them is `unsupported` with `fields_not_supported`.

### `get_attributes`

Returns `brightness` (percent, to one decimal), `color_temp_kelvin`, `xy_color`, `rgb_color` and
`hs_color` under Home Assistant's names, for lights that are off too. The response is hue_dimmer's
and core's shape, each target's attributes under its entity ID (`response['light.desk'].brightness`),
so `merge_response` works on it; a target that can't be read is left out. `color_temp_kelvin` is
left out while a light is in color mode, since the value the bridge keeps is stale.

A room returns one entry, as any target does. While any light is on, the room's brightness is the
bridge's (the average of the lights that are on) and its color temperature and color average the
lights that are on, matching what the Hue integration shows for the room. With every light off the
bridge reports nothing useful, so the room's entry averages all of its lights.

### `set_scene`

Reads the scene from aiohue on every call, so edits made in the Hue app apply, then writes each
light's brightness, color temperature and color as a light write. The Hue API has no recall that
leaves lights off, which is why it isn't one. `on: true` is dropped so nothing turns on; `on: false`
is sent, as a recall would. Gradients, effects and dynamics are not written, so a dynamic scene
sets its first frame.

One failing light doesn't stop the rest: the result is `sent` with `some_lights_failed`, or
`rejected` if every light failed. All-Day (smart) scenes are `unsupported` with `smart_scene`;
a scene the bridge no longer has is `rejected` with `scene_not_found`.

### `move` and `stop`

`move` covers `brightness` for now; `color_temp` and `saturation` are refused with
`fields_not_tested` until they are tested, and `hue` is refused because a hue rotation isn't a
straight line the bridge can fade along. A brightness move is one write: the end point
(`brightness_limit`, or 0 % or 100 %) with a duration of `sweep_time` × the fraction of the range
left, which the bridge then runs on its own. Moving up turns the light on, from the bottom if it was
off. Moving down to 0 % is a plain soft off: `on: false` with the duration, so the bridge keeps the
stored brightness and the next plain on comes back at it. A light already at or past its limit is
`unchanged` with `at_limit` and nothing is sent.

A room moves with one write to its `grouped_light`, so its lights converge on the end point
together. `stop` sends the bridge's dimming stop to the light or room. The bridge refuses that stop
during a soft off, so a soft off Device Side started is cut by writing `on: true` with the predicted
brightness and no duration, light by light for a room. A light that is off, or fading off from
elsewhere, has nothing Device Side can stop: it is `unchanged` with `off` and nothing is sent.

While a fade runs the bridge reports its end value, and after a stop it reports where the light
halted late or not at all (Tested behavior, below). Device Side remembers each move and stop for its
duration plus 15 seconds and predicts the brightness of each light meanwhile, so a move after a stop
continues from where the light halted, and `get_attributes` returns the predicted brightness.

### `turn_on_for`, `turn_off_for`

`unsupported` with `no_adapter`. The bridge's own timers can do the flip, but nothing cancels
them except removing them on the bridge: a plain on/off from Home Assistant, the Hue app or a dimmer switch
leaves the timer running, and the Hue app doesn't show it. A bulb without power when its timer
fires misses the flip and the bridge doesn't retry. For timed Hue bulbs, pair them through ZHA,
Zigbee2MQTT or Matter.

### Tested behavior

What the bridge reports during a transition (a write with a duration), measured 2026-10-26 on a
BSB002 bridge (software 6.1.1978418030) and two LTA009 bulbs (firmware 1.163.1), with Home
Assistant 2026.10.2 and aiohue 4.9.0. The Hue integration copies each event into Home Assistant as
it arrives, so Home Assistant shows what is listed here.

- **A transition reports its end value at the start.** One event per light, about 70 ms after the
  write returns, holding the target the bridge stored (80 % reads 79.84). Nothing is sent when it
  ends. A second transition to the value the bridge already holds sends no event.
- **Where a stopped light halted is reported late, or not at all.** The report arrived 0.1 to 27 s
  after the stop; its varying timing suggests it comes from the bulb, not a bridge timer. After 4 of
  16 stops followed by 30 s of waiting, none came, and Home Assistant kept showing the end value.
  When a report did come, it matched a straight-line interpolation within 0.3 % for brightness and
  1 mirek for color temperature.
- **A report can arrive in the middle of a transition**, for a stop that came before it or partway
  through the transition itself, and may be the last one sent.
- **Rooms and zones:** each light reports its end value at once, then the `grouped_light` reports
  the average about 1 s later. After a stop the lights report separately, up to 16 s apart.
- **A change from elsewhere is reported promptly:** a `light.turn_on` from Home Assistant within
  0.25 s, and a Hue app slider with an event about once a second while it moves.
- **Dimming to off:** `on: false` (and brightness 0, if the write set it) is reported at the start. In
  1 of 2 runs, a report mid-transition then showed the light on at 17 % with nothing after it. A
  dimming stop is refused while the light dims to off ("soft off"), but writing `on: true` with a
  brightness and no duration ends the fade there; set to the straight-line value, it showed no jump
  or flash. A plain `on: false` with a duration keeps the stored brightness, and the next plain on
  comes back at it; with brightness 0 in the write, it comes back at the minimum.
- **Brightness 0 with the light left on** (`on: true`, brightness 0, with a duration) is accepted,
  reported as 0 at the start, and ends with the light on at its minimum (the bridge's
  `min_dim_level`, 0.2 % on the LTA009). Home Assistant shows it on at brightness 0. A dimming stop
  halts it.
- **A color temperature write reports only `color_temperature`,** never `dimming`. Color
  temperature transitions and their stop (`color_temperature_delta`) behave as brightness does
  above, on a light and on a zone.

### Sharp edges

- **No gamut clamp.** `set_attributes` sends a color outside a bulb's gamut as is, and the bulb
  shows the nearest color it can.
- **Large scenes are slow.** `set_scene` sends one write per light, one after another, and the
  bridge refuses more than 3 requests at once (aiohue retries with a growing wait), so a scene on a
  large room can take seconds to land.
- **Lights hidden from Home Assistant are skipped.** A light in a room with no light entity (a
  disabled one, say) gets no write from `set_attributes` on the room and no row from
  `get_attributes`, though `set_scene` writes it.
