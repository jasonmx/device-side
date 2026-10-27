# Hue: a bulb's reports during a fade and after a stop are ours, except a switch to off

## Context

`report_filter` tells the bridge's reports of our own fades from real changes by matching each value: armed
end values (echoes), points between a fade's start and target, and, since #77, anything for 15 s after a stop.
The rig showed why matching values loses: a bulb reported, 4 s after a stop, the brightness it held before the
write that preceded the move (56 % against a 40 % halt). Bulbs report late, stale and off any straight line, so
value matching keeps needing new bands.

What matters is that HA shows the real bulb consistently and predictably, and that the rule stays simple. A
user who wants the bridge's raw reports turns predicted_state off.

## Decisions

- **The window:** a light is followed from just before a move's or stop's write until its transition's guard
  window ends (the fade's duration plus `API_SETTLE_SECONDS`, 15 s; a stop's duration is 0). Recording before
  the write replaces arming: the bridge can report before the write returns. A refused write puts back what
  was recorded before it, as `write_forgetting` does.
- **The rule:** inside the window every report from the light is ours, except `on: false` while the light's
  transition target is above 0 (a fade up or down to a lit level, or a halt above 0). That is a switch to off
  from elsewhere (Hue app, dimmer, a Hue automation): it is real, forgets the light, and reaches HA. A soft
  off's own `on: false` is not an exception, as its target is 0.
- **Changes from HA** stay caught at once by the service-call listener, whatever their value, as do
  `set_attributes` and `set_scene` (`write_forgetting`). Unchanged.
- **Accepted losses** (documented under "Not caught"): any other change from outside HA during the window,
  e.g. a Hue app brightness change, or turning a light on within 15 s of a soft off reaching 0. With
  predicted_state on, HA shows the prediction until the bridge next reports after the window.
- **Up from off** shows the light on at its dimmest at once. Today that hangs off the `on: true` echo; it moves
  to `ReportFilter.fading`, which knows which lights were off.
- **Rooms:** a grouped_light's report is ours while any of its lights is followed, as now. A member switched
  off elsewhere is caught by its own light's report.
- **predicted_state off:** the same rule decides what forgets the prediction; nothing is hidden. Unchanged.
- **Tier:** a simplification of experimental adapters, so no `experimental` change; the fingerprint reset
  means a rig run writes new records.

## What goes

- `TransitionCache`: `Echo`, `arm`, `disarm`, `write_armed`, `echoed`, `bridge_value`, `path`, `on_path`,
  `REPORT_TOLERANCE` (check every other use first), and the echo half of `follows`, `forget`, `Forgotten`,
  `restore`.
- `move.end_echo` and the echoes `stop.py` builds for a soft-off cut.
- `report_filter`: the `Report.ECHO`/`PATH` split and `_value`'s value matching. `classify` answers ours,
  real, or not followed.

## What stays

The service-call listener, `write_forgetting`, hiding (`_hide`, `_strip`), `show`, `halted`, `fading`, room
means, and the hidden-value bookkeeping (`hidden`, `shown`, `release`, `hand_back`), which hands HA the
bridge's real values when a light is forgotten mid-fade.

## Steps

1. `transition_cache.py`: drop the echo and path machinery; `follows` is a live transition; add what a refused
   write needs to put the previous transition back.
2. `move.py` and `stop.py`: record before the write, put back on refusal; drop `end_echo` and the stop's echoes.
3. `report_filter.py`: the rule above; up from off shown at its dimmest from `fading`.
4. Tests: replace the echo, path and halt-band tests with the window rule; cover `on: false` at a lit target
   (real), a soft off's `on: false` (ours), a stale brightness mid-fade and after a stop (ours), the window's
   end, a refused write, and up from off at the dimmest. Keep ≥ 95 % coverage of each Hue module.
5. `docs/integrations.md`: rewrite how Device Side tells its reports from real changes, and "Not caught".
6. Rig: full Hue suite, unattended plus the observed briefs Jason chooses; commit the records.
7. `/audit-code`, PR into `release/v0.0.2`, `ci-green`, merge.
