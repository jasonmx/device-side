# Platforms

One section per platform, each on the same template: what Device Side talks to, how a target
entity becomes a device address, notes per feature, sharp edges, and a capability block generated
from the code. The generated blocks are rewritten by `scripts/gen_docs.py`; edit the prose around
them, never inside them.

## Shelly

### What it talks to

Shelly Gen2 and later devices (Plus, Pro, Gen3, Gen4), through the RPC connection the core
`shelly` integration already holds open. Device Side adds no connection of its own and needs no
credentials beyond the ones the Shelly integration was set up with. Gen1 devices (CoIoT) have no
flip-back timer in the API Device Side uses, and are reported `unsupported` with detail
`gen1_unsupported`.

### How targets resolve

An entity belongs to this platform when its registry platform is `shelly`. The RPC component and
instance come from the entity's unique ID, which the Shelly integration writes as
`<mac>-<key>`:

| Key | RPC component | Entity domains | Claimed | `light.turn_on` fields it can take |
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
another helper returns `not_addressable`. This holds on every platform, not only Shelly.

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

Only relays are claimed so far, whether HA shows them as a switch or a light. A dimmer, CCT or RGB
light returns `unsupported` with detail `component_not_supported` until someone tests one. A light
field (brightness, color, transition) on a light returns `unsupported` with detail
`fields_not_supported` rather than being dropped silently. Fields sent to a `switch` entity are
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
  floor, for all platforms; a duration under 50 ms or over 7 days is clamped and the result
  carries `clamped_to`.
- **The timer is the device's, not Home Assistant's.** Any on or off command cancels it, whatever
  sent it: Home Assistant, the Shelly app or another integration (see Cancelling).
- **Colors other than RGB.** `hs_color` and `xy_color` are refused rather than converted, because
  the conversion depends on the component's color mode. Send `rgb_color` or `color_temp_kelvin`.
- **Only relays are claimed.** `Light`, `CCT`, `RGB`, `RGBW` and `RGBCCT` document `toggle_after`
  the same way as `Switch`, but they are different firmware and no hardware run has covered them,
  so they are refused until a tester reports one.

<!-- generated:shelly:start -->
_Generated from the code by `scripts/gen_docs.py` (slice 8)._
<!-- generated:shelly:end -->
