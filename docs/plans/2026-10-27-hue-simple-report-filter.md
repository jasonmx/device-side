# Hue: a bulb's reports during a fade and after a stop are ours, keyed by attribute

## Context

`report_filter` tells the bridge's reports of our own fades from real changes by matching each value: armed
end values (echoes), points between a fade's start and target, and, since #77, anything for 15 s after a stop.
The rig showed why matching values loses: a bulb reported, 4 s after a stop, the brightness it held before the
write that preceded the move (56 % against a 40 % halt). Bulbs report late, stale and off any straight line, so
value matching keeps needing new bands.

What matters is that HA shows the real bulb consistently and predictably, and that the rule stays simple. A
user who wants the bridge's raw reports turns predicted_state off.

Slice 7c adds color temperature and saturation moves, so the design is keyed by attribute now, with brightness
its only attribute until then.

## Architecture

- **One store of transitions keyed `(light, attribute)`**, as `TransitionCache` is today: a move records one
  per attribute it moves, a stop turns each live one on the light into a halt (duration 0). A combined move is
  several entries, so shared or separate durations (repo plan, open item 12) need no special case.
- **One table of what each attribute means on Hue**: the bridge report keys a write of it makes the bridge
  report, how to read its value from a report, how to build the report that shows a value, and how to
  interpolate. Brightness owns `dimming.brightness` and `on` (a move turns a light on, a soft off turns it
  off). 7c adds rows: color temperature owns `color_temperature.mirek` (a CT write reports only that, per
  Tested behavior), saturation `color.xy` (to be measured). No attribute gets its own cache or rules.
- **A transition is ownership.** While it is live (the fade's duration plus `API_SETTLE_SECONDS`, 15 s), the
  report keys its attribute owns are ours. Every other report key passes through to HA untouched, so a
  brightness fade never hides a color temperature change.
- **Forgetting is per light.** Evidence that something else changed the light ends every transition on it and
  hands HA the bridge's values: a scene recalled elsewhere almost certainly set brightness too, and our end
  would otherwise overwrite it.
- **One end timer per `(light, attribute)`**, showing only that attribute's report keys.
- **Hidden values are kept per report key**, and forgetting a light hands all of them back.

A stop by attribute, should the action ever take fields, fits without change: it halts and cancels only the
matching entries. Whether Hue can halt one attribute of a combined fade (no xy delta stop; a cut may cancel the
other attribute's fade) is a rig question for 7c.

## Decisions

- **The window:** a light is followed from just before a move's or stop's write until its transition's guard
  window ends. Recording before the write replaces arming: the bridge can report before the write returns. A
  refused write puts back what was recorded before it, as `write_forgetting` does.
- **The rule:** inside the window every report key a live transition owns is ours, except `on: false` while
  the light's brightness transition targets above 0 (a fade to a lit level, or a halt above 0). That is a switch
  to off from elsewhere (Hue app, dimmer, a Hue automation): it forgets the light and reaches HA. A soft off's
  own `on: false` is not an exception, as its target is 0.
- **Another actor, by report key (adopted only if step 1 confirms it):** a report of a key no live transition
  owns, among those some attribute could own (brightness, on, mirek, xy), forgets the light, as does a scene
  recall on the bridge for a room or zone holding it. Step 1 must show our own fades, stops and the bulbs' late
  reports never carry such keys; if they do, this rule is left out and `on: false` stays the only exception.
- **Changes from HA** stay caught at once by the service-call listener, whatever their value, as do
  `set_attributes` and `set_scene` (`write_forgetting`). Unchanged.
- **Accepted losses** (documented under "Not caught"): a change from outside HA during the window to a report
  key we own, e.g. a Hue app brightness change. With predicted_state on, HA shows the prediction until the
  bridge next reports after the window.
- **Up from off** shows the light on at its dimmest at once. Today that hangs off the `on: true` echo; it moves
  to `ReportFilter.fading`, which knows which lights were off.
- **Rooms:** a grouped_light's report is ours while any of its lights is followed, as now. Aggregating color
  temperature and xy for a room is 7c's to measure.
- **predicted_state off:** the same rules decide what forgets the prediction; nothing is hidden. Unchanged.
- **Tier:** a simplification of experimental adapters, so no `experimental` change; the fingerprint reset
  means a rig run writes new records.

## What goes

- `TransitionCache`: `Echo`, `arm`, `disarm`, `write_armed`, `echoed`, `bridge_value`, `path`, `on_path`,
  `REPORT_TOLERANCE` (check every other use first), and the echo half of `follows`, `forget`, `Forgotten`,
  `restore`.
- `move.end_echo` and the echoes `stop.py` builds for a soft-off cut.
- `report_filter`: the `Report.ECHO`/`PATH` split, `_value`'s value matching, and the brightness knowledge in
  `reported_values`, `_strip` and `show`, which moves to the attribute table.

## What stays

The service-call listener, `write_forgetting`, hiding, `show`, `halted`, `fading`, room means, and the
hidden-value bookkeeping (`hidden`, `shown`, `release`, `hand_back`).

## Steps

1. **Probe** (needs the rig free of other sessions): run the full Hue suite while logging every light,
   grouped_light and scene report whole (a scratch subscriber to the bridge's event stream). List every key in
   our own fades', stops' and late reports. Record the result under Tested behavior in `docs/integrations.md`
   and settle the "another actor" decision above.
2. `transition_cache.py`: drop the echo and path machinery; `follows` is a live transition; add what a refused
   write needs to put the previous transition back.
3. The attribute table, with brightness; end timers keyed `(light, attribute)`.
4. `move.py` and `stop.py`: record before the write, put back on refusal; drop `end_echo` and the stop's echoes.
5. `report_filter.py`: the rules above, reading report keys from the table; up from off shown at its dimmest
   from `fading`.
6. Tests: replace the echo, path and halt-band tests with the window rule; cover `on: false` at a lit target
   (real), a soft off's `on: false` (ours), a stale brightness mid-fade and after a stop (ours), an unowned key
   passing through (and forgetting, if adopted), the window's end, a refused write, and up from off at the
   dimmest. Keep ≥ 95 % coverage of each Hue module.
7. `docs/integrations.md`: rewrite how Device Side tells its reports from real changes, and "Not caught".
8. Rig: full Hue suite, unattended plus the observed briefs Jason chooses; commit the records.
9. `/audit-code`, PR into `release/v0.0.2`, `ci-green`, merge.
