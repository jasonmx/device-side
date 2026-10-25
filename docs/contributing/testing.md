# Testing on your own Home Assistant

The rig runs integration tests against the maintainer's live hardware. If you want to test a
pre-release on your own setup, here is what to do.

## Install

Copy `custom_components/device_side` into your Home Assistant config directory, or add
`https://github.com/jasonmx/device-side` as a custom HACS repository and install Device Side
from there. Restart Home Assistant.

Add the integration: Settings > Devices & services > Add integration > Device Side. Check that
it appears as loaded with no errors in Settings > System > Logs.

## Try the actions

Open Developer tools > Actions and find `device_side.turn_on_for`. Select only a switch entity:
the brightness, color and transition fields should hide. Add a dimmable light: they should show.

Run the action with a short duration (5-8 seconds) and check the device responds.

## Report

[Open an issue](https://github.com/jasonmx/device-side/issues/new?title=Test%20report)
with the Device Side version, the integration (Shelly, ZHA, etc.), the entity type, the fields
you tested, and whether each action worked. Include any error messages from the logs.

An automated runner that connects to your HA, executes the steps and prefills the issue body is
planned for a future release.

## Rig tests

Rig tests are YAML step files in `tests/rig/steps/`, one per action. `scripts/rig.py` runs each file against
every integration in your `tests/rig/inventory.yaml` that has an adapter for the action, after a y/N gate:
the devices change state, so nothing moves until you say yes. `--dry-run` prints the plan and stops.

### Token

Make a dedicated Home Assistant user without admin rights and create its long-lived token for `HA_TOKEN` in
`.env.rig`. The rig only calls actions and reads states and registries, so admin isn't needed, and a non-admin
token can't change your configuration if it leaks.

ZHA is the exception. Its cluster command is an admin-only action, and the ZHA adapter passes the caller's
context through to it, so a non-admin token is refused. ZHA rig tests will use an admin token, for that adapter
only, once the ZHA adapter lands.

### Writing a step file

```yaml
action: turn_on_for        # the device_side action every test in the file calls
rig_seconds: 25            # the gate's duration estimate
tests:
  - name: on_then_off
    roles: [switch_plug, light_onoff]   # one run per role the inventory names
    steps:
      - set: {state: off}
      - call: {duration: 6}
      - expect_response: {status: expected, integration: self}
      - expect_state: {state: on, within: tol}
      - wait: duration - tol
      - expect_state: {state: off, within: 2 * tol}
```

| Step | Does |
|---|---|
| `set` | Puts the target in a known state with plain HA actions (`state`, plus light attributes). |
| `call` | Calls the file's action with these fields; `duration` is sent in seconds. |
| `expect_response` | Checks the call's response: `status` (`expected` means `confirmed` where the adapter can confirm, else `sent`), `integration` (`self` is the one under test), `detail`, `clamped_to`, `attributes`. |
| `expect_error` | The call before it must fail, with this `key` and/or `summary`. |
| `expect_state` | Checks state and attributes now, or `within` seconds. `unchanged` is the state before the test. A `{min, max}` range fits values that drift. On a `group` it checks every member. |
| `wait` | Sleeps. |
| `sample` | Polls an attribute `for` seconds and expects it `rising`, `falling` or `steady`, optionally within `min`/`max`. |
| `observe` | Asks the person at the rig a y/N question. |
| `restore` | Puts back the state from before the test. It also runs after every test, pass or fail. |

Any step takes `target: <role>` to act on another role the test lists. Durations accept numbers, `duration`
(the last call's), `tol` (the integration's timing tolerance) and `+ - *`. `only: [<integration>]` limits a
test to some integrations; when those pile up, split the file. `tests/rig/steps/examples/` shows the planned
actions (ramps, attributes while off, scenes) and is only parsed, never run.

### Observe steps

An `observe` step is for what the state can't show, such as a light climbing smoothly without flashing. The
run pauses, prints the question and waits for you to answer: watch the device and answer `y` only if you saw
it. Anything else fails the test. `--unattended` skips the questions and reports those tests as
`not observed`; they don't fail, but their bench record proves nothing they cover.

### Bench records

When every test of an adapter passes, the run writes `docs/bench/<integration>/<action>.md`: the adapter's
fingerprint (`scripts/fingerprint.py`), the Home Assistant version, the devices' model and firmware, and the
capabilities and fields the tests reached. A failed or partial (`-k`) run writes nothing.
