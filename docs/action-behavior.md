# How actions behave

When to stop an automation, what to skip, and what a response looks like follow Home Assistant core's own
actions. Users already know how core behaves, and blueprints and templates are written against it. When a
question here isn't covered, read core's code and match it rather than inventing a rule; device_side's own
habits are not precedents.

The facts below were read from HA 2026.10.2: `helpers/service.py` (`entity_service_call` and the functions it
calls), `helpers/target.py` (`async_extract_referenced_entity_ids`), `components/light/helper.py`
(`filter_turn_on_params`) and `helpers/template/extensions/functional.py` (`merge_response`). Re-read them when HA changes; `.venv` holds the version CI runs.

## When to stop an automation

An exception from an action stops the automation unless the step sets `continue_on_error`. Core raises only
when the call is wrong or a device failed, never because some targets didn't apply:

| Situation | Core | device_side |
|---|---|---|
| Invalid input (out of range, wrong type) | Raises at the schema | Raise at the schema |
| A target is unavailable or missing | Skips it, logs "Referenced entities ... are missing or not currently available" | Skip and log alike |
| No targets left after skipping | Returns, nothing raised | Return |
| The same, when the caller asked for a response | Raises: no entity matched | Raise `no_entities_matched` |
| A target the caller named can never support the action | Raises `ServiceNotSupported` | Raise `target_not_supported`, before anything is sent |
| The same target reached indirectly | Skips it silently | Skip it, with one warning per call listing each target and why |
| A light can't take one field (color on a white bulb) | Drops the field silently and acts on the rest | Drop it, act on the rest, `detail: fields_dropped` |
| The device or its integration fails | The error propagates | Run every target, then raise `targets_failed` listing the failures |

Why: a mixed room must not abort an automation over the lights that can't take part, but a call that names
the wrong entity, or a device that failed, should stop it, because carrying on would hide the mistake.

**Named or indirect.** A target is named when the caller listed its entity ID. Everything else is indirect:
an area, device or label, a member of an HA group (`group.*` or a group helper), or a member of a native group
the dispatcher expanded. Core treats a `group.*` member as named; device_side doesn't, because a group is a
deliberately mixed set. An indirect entity outside the action's domains is never a target, as in core.

**Can never support** is any reason that holds whatever the device's state: no adapter, a domain, capability
or option nobody has tested, an entity the integration can't address. A field nobody has tested is in this
class too: it is refused, never dropped. **Lacks a field** comes from the target's state, read as
`filter_turn_on_params` reads it (a color is lacked only without any color mode, color temperature only without
that or a color mode, since core converts between them first), and from the adapter where only it knows (Hue's
gamut, a Shelly component's fields, `AdapterScope.drops`). A `switch`, or a `switch_as_x` light, lacks every
light field, so a timed call still runs its timer. A call left nothing to do by dropping is `unchanged` with
`fields_dropped`. An empty group is skipped silently, as core's group expansion yields nothing for one.

## What a response looks like

Core's entity actions return `{entity_id: <that entity's data>}`, one entry per entity that ran, for example
`{"weather.home": {"forecast": [...]}}` from `weather.get_forecasts`. There is no status per entity: a failure
raises or the entity is skipped.

- **Queries** (`get_attributes`) return that shape: each target's data under its entity ID, nothing else, and
  a target that couldn't be read is left out. Templates read `response['light.desk'].brightness`.
- **`merge_response`** turns that shape into a list of the entities' dicts with `entity_id` added to each, so
  a blueprint can loop without knowing the IDs. It requires every value to be a dict and raises if one already
  has an `entity_id` key, so query data never carries `entity_id`.
- **One entry per target.** A room returns one entry, not one per light as well, so `merge_response` lists each
  target once.
- **Commands** return nothing in core. device_side keeps an optional status response, one entry per target
  that ran: `confirmed`, `sent` or `unchanged`, with `integration` and, where they apply, `detail` and
  `clamped_to`. Skipped targets are left out, as core leaves them out, and `unsupported` or `rejected` never
  reach a response: the call skips or raises instead. A call that has nothing to do succeeds quietly as
  `unchanged` with a `detail`.

## Replacing hue_dimmer

`set_attributes`, `get_attributes` and `set_scene` are drop-in replacements for hue_dimmer's: a user changes
only the domain. Same field names and units (brightness in percent), names and descriptions in the UI, the
same response shape, and hue_dimmer's input habits: `0` leaves `min_brightness`, `max_brightness` or
`color_temp_kelvin` unset, and given several colors, `rgb_color` wins, then `hs_color`, then `xy_color`.
Before changing any of these, check hue_dimmer
([jasonmx/hue-smooth-dimming](https://github.com/jasonmx/hue-smooth-dimming)) and say what breaks for its
users. `move`/`stop` replace raise/lower by design and are the exception.
