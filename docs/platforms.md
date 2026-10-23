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

| Key | RPC component | Entity domains | `light.turn_on` fields accepted |
|---|---|---|---|
| `switch:N` | `Switch` | `switch`, or `light` for a relay set to "light" | none |
| `light:N` | `Light` | `light` | `brightness`, `transition` |
| `cct:N` | `CCT` | `light` | `brightness`, `transition`, `color_temp_kelvin` |
| `rgb:N` | `RGB` | `light` | `brightness`, `transition`, `rgb_color` |
| `rgbw:N` | `RGBW` | `light` | `brightness`, `transition`, `rgb_color` |
| `rgbcct:N` | `RGBCCT` | `light` | `brightness`, `transition`, `color_temp_kelvin`, `rgb_color` |

Any other Shelly entity (virtual booleans, scripts, circuit breakers) has no flip-back timer and
returns `unsupported` with detail `not_addressable`. Shelly has no device-side groups, so a light
group helper over Shelly lights is expanded and each member gets its own command.

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

A field the component cannot take (`color_temp_kelvin` on a plain dimmer, any field on a relay
shown as a light, `hs_color` or `xy_color` anywhere) returns `unsupported` with detail
`fields_not_supported` rather than being dropped silently. Fields sent to a `switch` entity are
ignored and the result says so with detail `light_fields_ignored`.

### `turn_off_for`

The same `Set` with `on: false`: the device turns off now and turns itself back on after the
duration. Light fields are not accepted.

### Sharp edges

- **Timer limits are provisional.** The Shelly API documents `toggle_after` only as a number of
  seconds. Device Side accepts 0.1 s to 24 h in 0.1 s steps; durations outside that range are
  clamped and the result carries `clamped_to`. The real device limits are confirmed on hardware
  before this cell leaves `experimental`.
- **The timer is the device's, not Home Assistant's.** Turning the output on or off by any other
  route (the Shelly app, a wall switch, a plain `light.turn_off`) can replace or cancel the
  flip-back timer, according to the device's own rules.
- **Colors other than RGB.** `hs_color` and `xy_color` are refused rather than converted, because
  the conversion depends on the component's color mode. Send `rgb_color` or `color_temp_kelvin`.
- **Color components are untested.** `CCT`, `RGB`, `RGBW` and `RGBCCT` document `toggle_after`
  the same way as `Light`, but no hardware run has covered them yet.

<!-- generated:shelly:start -->
_Generated from the code by `scripts/gen_docs.py` (slice 9)._
<!-- generated:shelly:end -->
