# How actions behave

When to stop an automation, what to skip, and what a response looks like follow Home Assistant core's own
actions. Users already know how core behaves, and blueprints and templates are written against it. When a
question here isn't covered, read core's code and match it rather than inventing a rule; device_side's own
habits are not precedents.

The facts below were read from HA 2026.10.2: `helpers/service.py` (`entity_service_call` and the functions it
calls), `components/light/helper.py` (`filter_turn_on_params`) and `helpers/template/extensions/functional.py`
(`merge_response`). Re-read them when HA changes; `.venv` holds the version CI runs.

## When to stop an automation

An exception from an action stops the automation unless the step sets `continue_on_error`. Core raises only
when the call is wrong or a device failed, never because some targets didn't apply:

| Situation | Core | device_side |
|---|---|---|
| Invalid input (out of range, wrong type) | Raises at the schema | Raise at the schema |
| A target is unavailable or missing | Skips it, logs "Referenced entities ... are missing or not currently available" | Skip and warn alike |
| No targets left after skipping | Returns, nothing raised | Return |
| The same, when the caller asked for a response | Raises: no entity matched | Raise |
| A target the caller named can never support the action | Raises `ServiceNotSupported` | Raise |
| The same target reached through an area, device or label | Skips it silently | Skip |
| A light can't take one field (color on a white bulb) | Drops the field silently and acts on the rest | Drop it; act on the rest |
| The device or its integration fails | The error propagates | Raise |

Why: a mixed room must not abort an automation over the lights that can't take part, but a call that names
the wrong entity, or a device that failed, should stop it, because carrying on would hide the mistake.

The dispatcher still raises when every target ends `unsupported` or `rejected`, and on no targets. Slice 9f of
the repo plan replaces that with the table above.

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
- **Commands** return nothing in core. device_side's optional status response has no core precedent; slice 9f
  decides whether it stays.

## Replacing hue_dimmer

`set_attributes`, `get_attributes` and `set_scene` are drop-in replacements for hue_dimmer's: a user changes
only the domain. Same field names and units (brightness in percent), names and descriptions in the UI, the
same response shape, and hue_dimmer's input habits: `0` leaves `min_brightness`, `max_brightness` or
`color_temp_kelvin` unset, and given several colors, `rgb_color` wins, then `hs_color`, then `xy_color`.
Before changing any of these, check hue_dimmer
([jasonmx/hue-smooth-dimming](https://github.com/jasonmx/hue-smooth-dimming)) and say what breaks for its
users. `move`/`stop` replace raise/lower by design and are the exception.
