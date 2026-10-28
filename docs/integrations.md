# Integrations

One section per integration, each on the same template: what Device Side talks to, how a target
entity becomes a device address, notes per action, and sharp edges.

A target "refused with" a reason can never take the action: the call raises if you named it, and skips
it otherwise ([action-behavior.md](action-behavior.md)).

## Shelly

### What it talks to

Shelly Gen2 and later devices (Plus, Pro, Gen3, Gen4), through the RPC connection the core
`shelly` integration already holds open. Device Side adds no connection of its own and needs no
credentials beyond the ones the Shelly integration was set up with. Gen1 devices (CoIoT) have no
flip-back timer in the API Device Side uses, and are refused with
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
| `rgbcct:N` | `RGBCCT` | `light` | yes | `brightness`, `transition`, `color_temp_kelvin`, `rgb_color` |

Any other Shelly entity (virtual booleans, scripts, circuit breakers) has no flip-back timer and
is refused with `not_addressable`. Shelly has no device-side groups, so a light
group helper over Shelly lights is expanded and each member gets its own command.

A `switch_as_x` light over a Shelly switch is served as that switch: the helper forwards on/off
unchanged, so the device receives the switch's own `Switch.Set`, and the result is keyed on the
light's entity ID. Light fields sent to such a light are dropped, as a switch can't take them, and the
timer still runs, with detail `fields_dropped`. An inverted helper returns `inverted_wrapper`, and a helper wrapping
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

Relays (whether HA shows them as a switch or a light) and `RGBCCT` color bulbs are in scope so far.
A `Light`, `CCT`, `RGB` or `RGBW` light is refused with `capability_not_tested`
until someone tests one. A light field the component can't take, such as brightness on a relay, is
dropped and the timer still runs, with detail `fields_dropped`; `hs_color` and `xy_color` are refused
with `fields_not_tested` (see Sharp edges). Fields sent to a `switch` entity are dropped the same way.

### `turn_off_for`

The same `Set` with `on: false`: the device turns off now and turns itself back on after the
duration. Light fields are not accepted.

### `get_attributes`

One `<Component>.GetStatus` per target. A running flip-back timer is returned as `timer`, the shared row: what the
timer turns the target to (`turns`), `ends_at` and `remaining_s`. The time left is the device's `timer_started_at`
plus `timer_duration`, against Home Assistant's clock; both clocks are SNTP-synced, and the result is kept between
0 and the duration, which bounds any skew. With no timer running there is no `timer` key, so a relay with none
returns an empty entry.

An `RGBCCT` bulb also returns `brightness` (the device's percent, as Hue's is), and, for the active mode only,
`color_temp_kelvin` or `rgb_color` with `hs_color` and `xy_color` derived from it. The bulb keeps these while off,
so they read then too. The same capabilities as `turn_on_for` are in scope; other light components are refused
with `capability_not_tested`. A device that doesn't answer raises.

### Cancelling

Send a regular `turn_on` or `turn_off`: either cancels the flip-back timer. A `turn_on_for` or
`turn_off_for` during a timer replaces it, so the countdown restarts at the new duration.

Tested on Gen3 and Gen4 relays (firmware 2.0.1) and a Multicolor Bulb Gen3 (firmware 2.0.3) by rig run. A wall
switch wired to the device's input was not tested, and what it does may depend on the input mode.

### Sharp edges

- **Timer limits are the device's.** The device accepts any duration over 0 s up to 7 days
  (604800 s) and keeps it to 0.01 s. Device Side rounds every duration to 10 ms with a 50 ms
  floor, for all integrations; a duration under 50 ms or over 7 days is clamped and the result
  carries `clamped_to`.
- **The timer is the device's, not Home Assistant's.** Any on or off command cancels it, whatever
  sent it: Home Assistant, the Shelly app or another integration (see Cancelling).
- **Colors other than RGB.** `hs_color` and `xy_color` are refused rather than converted, because
  the conversion depends on the component's color mode. Send `rgb_color` or `color_temp_kelvin`.
- **Only relays and `RGBCCT` are in scope.** `Light`, `CCT`, `RGB` and `RGBW` document `toggle_after`
  the same way, but they are different firmware and no hardware run has covered them, so they are
  refused until a tester reports one.

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

### What Device Side changes in Zigbee2MQTT

Device Side sets three of Z2M's per-device and per-group options, each logged at info level when it changes:

- **`hue_native_control`**, on a Hue bulb or a group with one, before a timer with a color, so the light comes
  on in that color rather than its last one (see `turn_on_for`).
- **`filtered_cache`**, before the first `get_attributes` read of a device, so a read's answer isn't cached and
  resent in every later message (see `get_attributes`).
- **`homeassistant.light.supported_color_modes`**, on every full-color light and group, so Home Assistant shows
  the light's color in either color mode (below).

**Color modes.** A light whose Z2M definition exposes both `color_xy` and `color_hs` can be in either mode, but
Z2M announces only one of them to Home Assistant, usually `xy`. When the bulb is in the other (after a hue or
saturation move, a Hue gradient scene, a remote's binding, or a power cut), Z2M reports `color_mode: "hs"`, and
Home Assistant rejects a mode it wasn't announced: it keeps showing the old color, even as Z2M resends the state
every few minutes ([Koenkk/zigbee2mqtt#28757](https://github.com/Koenkk/zigbee2mqtt/issues/28757)). Z2M declined
to announce both modes by default, as some lights handle mixed modes badly
([#33025](https://github.com/Koenkk/zigbee2mqtt/issues/33025)).

So Device Side sets the light's Home Assistant override in Z2M to `xy`, `hs`, and `color_temp` where the light
has it. Z2M applies the override to its discovery message at once, Home Assistant keeps the entity, and from
then on accepts every state Z2M sends. The bulb itself is never touched. A group is changed when every member
qualifies. Lights exposing one color model, and lights on an endpoint (`light_l1`), are left alone. Device Side
does this at setup and again whenever Z2M announces a device or group change (a device joining, being
interviewed, coming back after a power cut, a group's members changing), reading Z2M's settings each time. An
override of your own is never changed, and a light you excluded from discovery is left alone.

**Opting out.** Turn off "Fix colors of full-color Zigbee2MQTT lights" in Device Side's options, or delete Device
Side. Z2M's settings can't delete an override (a `null` there strips the setting from Home Assistant's
announcement instead), so Device Side writes back the modes Z2M announces by itself, wherever the value is still
the one it set, and Home Assistant goes back to Z2M's single mode. Turning the option back on replaces those
again.

### `turn_on_for`

For **light entities without fields**: publishes `{"state":"ON","on_time":<seconds>}` to the
device topic. Z2M translates `on_time` (in seconds, rounded to 1 decimal place) to the Zigbee
`OnWithTimedOff` command.

For **light entities with fields** (`brightness`, `color_temp_kelvin`, `rgb_color`, `hs_color`,
`xy_color`, `transition`): calls `light.turn_on` first so HA's MQTT light entity handles the color
mode and sets the attributes through its own protocol, waits for Z2M to publish the light's state on
`zigbee2mqtt/<friendly name>`, then publishes `{"state":"ON","on_time":<seconds>}` separately. The
two-step approach keeps HA's light state in sync and delegates attribute handling to the integration
that knows the device's capabilities.

The wait matters because Z2M handles two messages for one light at once: sent straight after
`light.turn_on`, the timer's message would publish the light's state from before the fields landed,
which Home Assistant keeps, and contend with them on the mesh, so the timer could start seconds
late. The wait is usually a fraction of a second. If Z2M publishes nothing within 5 s, Device Side
logs a warning and sends the timer anyway, so that light stays on up to 5 s longer than asked.

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

**Hue native control.** Z2M sends on and color as separate Zigbee commands, and a Hue bulb drops a
color it receives while off, so a timer with a color would light at the bulb's last color first.
Z2M's per-device option `hue_native_control` sends on, brightness, color and color temperature as
one Philips command instead, which lights in the new color from the start and keeps the timer.

So the first time a call carries `color_temp_kelvin`, `rgb_color`, `hs_color` or `xy_color` to a
Hue bulb (manufacturer `Philips` in Home Assistant's device registry), Device Side turns that
option on for it, and logs it at info level. It checks Z2M's settings on every such call, which adds
a fraction of a second before the light turns on, waits up to 5 s for Z2M's answer when it changes
the option, and sends the timer either way. If Z2M doesn't answer, it logs a warning
and that one call may light at the last color first. Calls without a color or color temperature
never touch the option.

The option is Z2M's, so it applies to every command Z2M sends the bulb, not just Device Side's: all
of them use the Philips protocol, and Z2M no longer simulates on/off transitions for it. To turn it
back off, set `hue_native_control` to false in the device's settings in Z2M's frontend; Device Side
turns it on again at the next timer with a color.

### Groups

A Z2M group entity is one target: Device Side publishes once to the group's ID topic, and Z2M
sends one `OnWithTimedOff` to the Zigbee group, so every member starts its timer at once. With
fields, `light.turn_on` goes to the group entity first, as for a device. The state read-backs go
to the group's own topic, `zigbee2mqtt/<group ID>/get`; Z2M rebuilds the group's state from its
members' answers and shows it off only once every member is off.

A command to a group uses the group's Z2M options, not its members', so for a timer with a color
Device Side turns `hue_native_control` on as an option of the group itself when any member is a Hue
bulb (members read from `zigbee2mqtt/bridge/groups`). A group takes a color only when every member
can show one, as Z2M exposes the features its members share.

### `get_attributes`

Reads each light live from the bulb, not from Z2M's or Home Assistant's state: Hue bulbs on Z2M don't report, so
both can be stale. For each cluster the light has, Device Side publishes Z2M's generic read,
`{"read": {"cluster", "attributes", "state_property": "device_side_read"}}`, to `zigbee2mqtt/<ieee>/set` and takes
the answer Z2M publishes on the light's state topic:

- `genOnOff` (`onOff`, `onTime`): a running `turn_on_for` timer, as `timer` with `turns: off`. `onTime` is the
  time the bulb has left, in tenths of a second.
- `genLevelCtrl` (`currentLevel`), when the light dims and is on: `brightness` in percent, as Hue's is. An off
  light's `brightness` is Z2M's instead, from the state the `genOnOff` answer carries: the level the light comes
  back at. The bulb's own isn't. After an off with a transition it holds the minimum (0.4%) while Z2M keeps the
  level it restores on the next on, and for about a second after a plain off a Hue bulb's own fade still dims it.
  Reading it would also overwrite Z2M's `brightness`, which takes every level read. With no `brightness` in Z2M's
  state, an off light's row has none.
- `lightingColorCtrl`, when it has a color mode: `colorMode`, plus `colorTemperature` for `color_temp`, `currentX`
  and `currentY` for `xy`, and `currentHue` and `currentSaturation` for `hs`. Only the active mode's color is
  returned, `color_temp_kelvin` or `xy_color`/`hs_color` with the others derived from it. A read that asks for
  one attribute the bulb lacks fails as a whole, so only the light's own color modes' attributes are asked for.

Bulbs keep their color and timer while off, so those read then too. Each cluster is one Zigbee round trip, a
quarter of a second or less, read one after another: up to three per light per call. A read the bulb doesn't answer raises: at once
when Z2M logs the failure on `zigbee2mqtt/bridge/logging`, else after 5 s.

**Z2M's `filtered_cache`.** Z2M deep-merges a read's answer into the device's cached state, and every message it
publishes for the device carries that whole cache, so a cached answer would ride in every later message and look
like a fresh one. Before the first read of a device, Device Side adds `device_side_read` to its per-device
`filtered_cache` option, after any entries of yours, and logs it at info level. Z2M then publishes the answer
once, in the read's own message, and never caches it. It checks Z2M's settings on every call, and if the option
can't be set, the call raises rather than read. Removing the entry is harmless; it comes back at the next call.

**Groups.** A group returns one entry, averaged the way the Hue integration averages a room: brightness, color
temperature and color over the members that are on, or over all of them when every member is off. It has a
`timer` only when every member that is on runs one, and then it is the one with the most time left. Members come
from `zigbee2mqtt/bridge/groups` and are read one after another, so a group costs its members' reads. An
unavailable member is left out, a member that doesn't answer fails the group, and a group with no members is
skipped.

Lights only, as for `turn_on_for`.

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
- **Other brands' color bulbs.** Hue native control is Philips-only, so a color bulb of any other
  brand, timed with a color from off, may light at its last color for a moment first. Untested;
  if yours does, open an issue.
- **Old color shown at first.** With Hue native control on, a Hue light may report its old color
  for the first seconds of a timer while it shows the new one, so Home Assistant shows the old
  color until the next report.
- **Restart during a timer.** Pending state reads are lost when Home Assistant restarts or Device
  Side unloads, so the light's state stays stale until the device next reports or is next
  commanded.
- **Zigbee traffic.** Each call adds up to three Zigbee reads per target, spread over the timer.
  A group read is one groupcast that every member answers.
- **Large groups on a busy mesh.** `get_attributes` reads a group's members one after another, up to three
  round trips each, and a call has 30 s for all its targets. A healthy read takes a quarter of a second or less,
  but a group of many bulbs on a slow mesh can run out the 30 s, and then every target in that call fails with
  `timeout`. Read a large group's members by area or label instead, which reads them four at a time.
- **No confirmation.** Z2M's MQTT interface does not synchronously confirm the timer started.
  The result is always `sent`, never `confirmed`, regardless of whether the device accepted the
  command.

## ZHA

### What it talks to

Zigbee devices on the core `zha` integration's own coordinator. Device Side calls ZHA's
`zha.issue_zigbee_cluster_command` action, which sends a Zigbee command to the device:
`OnWithTimedOff` for a timer, which then runs on the device, and the `MoveTo…` commands for
`set_attributes`.

### How targets resolve

An entity belongs to this integration when its entity registry entry comes from `zha`. The IEEE
address and endpoint are parsed from the unique ID, which ZHA writes as `{ieee}-{endpoint_id}` for
a light. An entity with a longer unique ID on the same endpoint (a quirk's extra entity, such as a
child lock) is refused with `not_addressable`, so a timer never lands on the wrong entity.

A ZHA group entity (unique ID `{platform}_zha_group_0x{group_id:04x}`) expands to its members in
the group entity's domain: a light group to its lights. Each member gets its own result; the group
entity gets none. A group ZHA no longer knows is skipped, like an empty group.

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

Members of a ZHA group share one command, so they start and stop together: with a light field,
one `light.turn_on` on the group entity, then one `OnWithTimedOff` to the group through
`zha.issue_zigbee_group_command`. One command per member would start them a slot apart, about
0.7 s across 8 lights. A group command gets no reply, and a member that can't run the timer
ignores it without a word, so each member is still read back as above. A light without the OnTime
attribute reads as no timer: `not_on`, or `timer_not_reported` once a field has turned it on. A
light slow to take the group's `light.turn_on` (the rig's Sengled, a Zigbee end device) still reads
off and reports `not_on`, then comes on and stays on. The measurements are in `docs/plans/2026-10-27-zha-groups-probe.md`.

Lights only, with `brightness` and `color_temp_kelvin` as the fields, until more are tested on
hardware. Zigbee plugs and switches are unsupported, as on Zigbee2MQTT: the one tested, a Tuya
TS011F, stores OnTime as its own countdown and never switches on, so it reads back `not_on`.

### `set_attributes`

Sends each light the Level and Color cluster `MoveTo…` commands, one after another, never the
`…WithOnOff` ones, so a light that is off stays off and comes on with the new settings. Each
command carries the ZCL `ExecuteIfOff` override (`options_mask: 1, options_override: 1`), which
makes a light that is off take it, and a 0.4 s transition, the Hue bridge's default, so a light
that is on fades as it would on Hue. Then Device Side calls `homeassistant.update_entity` on the
light, since ZHA never applies a color temperature report.

The fields, units and names are Hue's (below). `brightness` is a percent of level 254, and `0`
sends level 1, the lowest; `min_brightness` and `max_brightness` read the light's CurrentLevel
live and clamp it, so they work while off, and a light already inside them is `unchanged` with
`within_limits`. `color_temp_kelvin` goes as mireds, clamped to the light's range. A color goes as
xy (`MoveToColor`), or as hue and saturation (`MoveToHueAndSaturation`) on a light without xy;
the light clamps it to its own gamut. Given a color and a color temperature, only the color is
sent, as both set the light's color; a color light without color temperature takes it as a color,
as core's `light.turn_on` does. A field the light can't take is dropped, as on Hue.

A light whose commands return is `sent`: ZHA raises when one can't be delivered or fails, and that
light is `rejected`. Nothing is read back, so a bulb that ignores the override reports `sent` too.
A model shown to mishandle a write while off (tested behavior, below) is refused with
`execute_if_off_unsupported`. A ZHA group expands to its members, written one at a time. Lights
only.

### `get_attributes`

Reads each light live, never from zigpy's attribute cache: ZHA doesn't apply color temperature
reports, so the cache goes stale after a raw command or a bound remote. One uncached request per
cluster per light, one after another: OnOff and OnTime always, Level when the light's
`supported_color_modes` go beyond on/off, and Color when they include a color mode. That is slower
than reading Home Assistant's state, but right mid-transition and after commands HA didn't send.
The bulb keeps these values while off, so they read then too.

`brightness` is a percent (CurrentLevel / 254), as Hue's is, so a read can be written back. Color
is the active mode only (EnhancedColorMode where the light has it, else ColorMode):
`color_temp_kelvin`, or `xy_color` or `hs_color` with the other two color keys derived from it. A
running timer is returned as `timer`, the shared row, from OnTime, and only while the light reads
on: a TS011F counts OnTime down while off. A ZHA group expands to its members, one entry each.
Lights only, as for `turn_on_for`. A light that doesn't answer raises.

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

For `set_attributes`, the LTA004 stores `MoveToLevel` and `MoveToColorTemp` with the
`ExecuteIfOff` override while off, stays off and comes on at them; without the override it drops
them (`docs/plans/2026-10-27-zigbee-probe.md`). A Sengled E11-G13, firmware `0x00000009`, takes
`MoveToLevel` while on, but while off, with the override or without, its CurrentLevel jumped to 255
and it came on at full brightness, so `set_attributes` refuses that model.

### Sharp edges

- **Admin only.** `zha.issue_zigbee_cluster_command` and `zha.issue_zigbee_group_command` are
  admin-only actions, and Device Side passes the caller's identity through to them. A call made as a non-admin user is `rejected` with
  detail `admin_required`. Automations run without a user, so they pass.
- **Duration limits.** `on_time` is a uint16 in tenths of a second, so the maximum is 6553.4 s
  (about 1.8 hours). A longer duration is clamped and the result carries `clamped_to`.
- **A clamp reads the light mid-fade.** `min_brightness` and `max_brightness` clamp the level the
  light is at, read live. Within about 0.5 s of a brightness change it is still fading, and the
  clamp's `MoveToLevel` replaces the fade's end: a light turned on at 70 % and clamped to at least
  50 % at once can end at 50 %. Home Assistant shows a ZHA group's new brightness on its members
  straight away, before the bulbs get there.
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

Plugs (`switch` entities) are in scope. Matter lights take the same command but are refused with
`domain_not_tested` until a tester reports one. Device Side requires the OnOff cluster's Lighting
(LT) feature, bit 0 of its FeatureMap, on the endpoint. Lights carry it, and so do some plugs. An
entity whose endpoint lacks it is refused with `no_lt_feature`.

### `turn_on_for`

Sends `OnOff.Commands.OnWithTimedOff(onOffControl=0, onTime=<tenths>, offWaitTime=0)` to the
device via python-matter-server. The device turns on and turns itself off after the duration
without needing Home Assistant to remain running.

`onTime` is the duration in 1/10-second units (`round(duration_s * 10)`). `onOffControl=0` means
the command is accepted whether the device is currently on or off. `offWaitTime=0` places no
restriction on retriggering.

After the command, Device Side reads back the `OnOff.OnTime` attribute (python-matter-server
answers `{path: value}`). If it is non-zero (the countdown is running), the result is `confirmed`.
If it is 0 or the read-back fails, the result is `sent` with detail `timer_not_reported` or
`readback_failed`.

### `get_attributes`

One live read of `OnOff.OnTime` per target. The node cache can't answer: the plug tested never reports `OnTime` on
its subscription, so the cached value stays 0 while a timer runs. A running timer is returned as `timer`, the shared
row: `turns` is always `off`, as Matter's only timer here is `turn_on_for`'s, and `remaining_s` is `OnTime`'s tenths
in seconds, with `ends_at` from Home Assistant's clock. `OnTime` is 0 with no timer running, and then there is no
`timer` key, so the entry is empty. A device that doesn't answer raises.

### Cancelling

Send a regular `turn_off`: it cancels the timed-off, as the Matter spec says `Off` clears `OnTime`. A plain
`turn_on` does not: on the plug tested, the timer still turned it off on time. A second `turn_on_for` during a timer
replaces it.

### Sharp edges

- **Timer limits are 0.1 to 6553.4 s.** `OnWithTimedOff.onTime` is a uint16 in 1/10-second
  units; the maximum of 65534 tenths corresponds to 6553.4 s. Device Side rounds durations to 10
  ms with a 50 ms floor; a duration outside the range is clamped and the result carries
  `clamped_to`.
- **The Lighting (LT) feature must be present.** The command is rejected at the device if the
  endpoint lacks this feature. Device Side refuses early with `no_lt_feature` rather than
  forwarding a command the device will ignore.
- **The LT check reads the raw attribute cache.** Device Side reads the OnOff FeatureMap from
  python-matter-server's node data (`node_data.attributes["{endpoint}/6/65532"]`), which needs no
  chip.clusters import. `MatterEndpoint.get_attribute_value` would need a real chip descriptor.

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
`fields_dropped`. A light that can take none of them is `unchanged` with `fields_dropped`.

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
`rejected` if every light failed. All-Day (smart) scenes are refused with `smart_scene`;
a scene the bridge no longer has is `rejected` with `scene_not_found`.

### `move` and `stop`

`move` covers `brightness` and `color_temp`; `saturation` is refused with `fields_not_tested`
until it is tested, and `hue` is refused because a hue rotation isn't a straight line the bridge
can fade along. Each attribute is one write: the end point (the limit, or the end of the range) with
a duration of `sweep_time` × the fraction of the range left, which the bridge then runs on its own.
Brightness and color temperature in one call are two writes, each with its own duration; the bridge
runs them independently (Tested behavior, below).

Moving brightness up turns the light on, from the bottom if it was off. Moving down to 0 % is a
plain soft off: `on: false` with the duration, so the bridge keeps the stored brightness and the
next plain on comes back at it. `color_temp_limit` is in kelvin and clamped to the light's range.
Color temperature moves only a light that is on: without `brightness: up`, a light or room that is
off is `unchanged` with `off` and nothing is sent. A light in color mode is `unchanged` with
`not_in_color_temp_mode` and its color temperature is left alone. An attribute the light can't move
(brightness on an on/off light) is dropped, with `fields_dropped`. An attribute already at or past its limit is left out, and a move with
nothing left to do is `unchanged` with `at_limit` and nothing is sent.

A room moves with one write per attribute to its `grouped_light`, so its lights converge on the end
point together. Its color temperature heads for the end of the widest range among its lights; a
light with a narrower range stops at the end of its own. `stop` sends the bridge's dimming stop to
the light or room, and its color temperature stop in the same write when a color temperature move
is remembered. The bridge refuses a dimming stop during a soft off, so a soft off Device Side
started is cut by writing `on: true` with the predicted brightness and no duration, light by light
for a room. A light that is off, or fading off from elsewhere, has nothing Device Side can stop: it
is `unchanged` with `off` and nothing is sent.

While a fade runs the bridge reports its end value, and after a stop it reports where the light
halted late or not at all (Tested behavior, below). Device Side remembers each move and stop for its
duration plus 15 seconds and predicts the brightness and color temperature of each light meanwhile,
so a move after a stop continues from where the light halted, and `get_attributes` returns the
predicted values.

A change made elsewhere ends the prediction, so the next move starts from the brightness the bridge
reports. A bulb reports late, stale, and off any straight line (Tested behavior, below), so Device
Side doesn't judge a report by its value. While it remembers a move or stop, it takes every report
of what it moved (brightness and on/off, color temperature) from that light as its own, with two
exceptions, both a change from elsewhere (the Hue app, a dimmer switch, a Hue automation): a switch
to off while the light is fading to, or halted at, a lit level, and a report of anything the move
didn't change, such as a color temperature report during a brightness move. A scene recalled on the bridge ends the prediction of its room's or zone's lights, and a light
or scene call from Home Assistant ends the prediction of every Hue light it targets at once, whatever
its value, as do `set_attributes` and `set_scene`. Not caught: a brightness change, or a switch to on,
from outside Home Assistant while a move or stop is remembered, such as a light turned back on in the
Hue app within 15 seconds of a fade to off.

With **Show predicted brightness during Hue fades** on (the default), Home Assistant shows Device
Side's predictions in place of those reports: the brightness at the start while a fade runs, where a
stop halted the light, and the end once the fade has run. A fade to off shows the light on until it
ends, a move up from off shows it on at its dimmest, and a room shows the mean of its lit lights. A
change caught as made elsewhere shows at once; one not caught shows once the bridge next reports
after the move or stop is no longer remembered. Nothing is sent while a fade runs, so a dashboard slider holds
still and then jumps to the stop or the end. After Home Assistant restarts, or reconnects to the
bridge, mid-fade, it shows what the bridge reports. To always show what the bridge reports, turn the
option off: Settings › Devices & services › Device Side › Configure. Color temperature isn't
predicted in Home Assistant's state: it shows the end of a color temperature fade at once, as the
bridge reports it.

### `turn_on_for`, `turn_off_for`

Refused with `no_adapter`. The bridge's own timers can do the flip, but nothing cancels
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
  1 mirek for color temperature. On 2026-10-27 a bulb in a zone instead reported, 4 s after a stop,
  the brightness it held before the write that preceded the move (56 %, against a 40 % halt).
- **A report can arrive in the middle of a transition**, and may be the last one sent. The one
  measured was the transition's own value about 1 s stale, so on the path the light had travelled.
  Every stop report that came was within 0.4 % of the straight-line value.
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
- **Brightness and color temperature fade independently.** A write of one neither cancels nor
  reshapes a fade of the other already running, in either order, on a light and on a zone: mid-fade
  reports of both lay on their own straight lines (2026-10-27). One write holding both reports two
  events, one per attribute. The bridge takes a dimming stop and a color temperature stop in one
  write, on a light and on a zone.
- **A brightness write never reports a color.** Across the full Hue rig suite on 2026-10-27, every
  report of a light during or after Device Side's brightness moves and stops held only `on` and
  `dimming`; `color_temperature` came only from color writes, and `color` never.
- **A scene recalled on the bridge reports its status:** `status.active` turns `static` within
  about 1 s of its lights' reports, before or after them. A light whose color the scene leaves alone
  reports only `on` and `dimming`, so only the scene's report shows the change came from elsewhere.

### Sharp edges

- **One write per light.** `set_scene` writes a scene's lights one after another; an 8-light scene
  takes under a second. The bridge refuses more than 3 requests at once and aiohue retries, so a
  much larger scene may take longer.
- **Lights with no entity in Home Assistant are skipped.** A light in a room whose light entity was
  deleted gets no write from `set_attributes` on the room and no row from `get_attributes`, though
  `set_scene` writes it. A disabled entity still counts: its light is written and reported.
