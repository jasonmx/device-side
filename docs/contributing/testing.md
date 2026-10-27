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

ZHA and Zigbee2MQTT are the exceptions. ZHA's cluster command is an admin-only action, and the ZHA adapter passes
the caller's context through to it, so a non-admin token is refused. The Zigbee2MQTT suites set and read Z2M
device options over MQTT, which only an admin may. Put an admin user's token in `HA_ADMIN_TOKEN`: those suites run
on it and every other suite stays on `HA_TOKEN`. Without it, a run that includes either stops before the gate;
`--integration` or `--action` leaves them out. Suites whose adapter has options (Hue `move` and `stop`) need it too, to set them
(below).

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
| `sample` | Polls `attribute` for `for` seconds and expects it `rising`, `falling` or `steady`, optionally within `min`/`max`. `source: device_side` reads `device_side.get_attributes` instead of HA's state, in its units (brightness in percent), for a fade HA shows only the end of. |
| `do` | Prints an instruction for the person and waits for Enter. Only in the `setup` of an observed test. |
| `restore` | Puts back the state from before the test. It also runs after every test, pass or fail. |
| `bridge` | Hue only: writes to the Hue bridge directly, bypassing Home Assistant, as another actor (the Hue app) would. `put: {...}` sends that CLIP v2 body to the target's light (a `group` target's grouped_light); `recall: true` recalls the `scene` target. In an observed run it runs as written. It needs `HUE_BRIDGE_HOST` and `HUE_APP_KEY` in `.env.rig`, and fails in any other integration's suite. |
| `z2m_option` | Sets Zigbee2MQTT device options on the target (`hue_native_control: false`) and waits for Z2M's ok. Does nothing in another integration's suite. |
| `expect_z2m_option` | Expects the target's Zigbee2MQTT device options to hold the given values. Does nothing in another integration's suite. |

Any step takes `target: <role>` to act on another role the test lists. Durations accept numbers, `duration`
(the last call's), `tol` (the integration's timing tolerance) and `+ - *`. `only: [<integration>]` limits a
test to some integrations; when those pile up, split the file.

An adapter with options runs each file for its action with them pinned through Device Side's options flow:
`options: [<name>]` at the top of a file turns those on, and every other option in the adapter's scope runs off.
Its record is `<action>-<name>.md`, with an `Options` row. The rig's own options are put back when the run ends.

An integration in `SETTLE_S` (`tests/rig/inventory.py`) predicts a light's brightness for a while after a
`move` or `stop`, so a later test on that light waits until it reads the device again.

### Observed tests

Some things need eyes, such as a light climbing smoothly without flashing. A test asks for them with an
`observe:` block and puts its start state in `setup:`. Each question costs the person at the rig, so ask as
few as cover everything a check can't measure: watch a behavior once, in the test that shows it best, and
leave its other tests automated.

```yaml
  - name: raise
    roles: [light_ct, group]
    setup:
      - set: {state: on, brightness_pct: 20}
    steps:
      - call: {brightness: brighter, sweep_time: 5}
      - sample: {attribute: brightness, for: 3, expect: rising}
    observe:
      see: The light at 20 %, climbing to full over 5 s.
      watch: Steps or flashes on the way up.
      ask: Did it climb smoothly to full?
```

Such a test runs twice, so you are asked only what a machine can't check:

1. **Automated**, with every other test first: setup and steps, every check applied. It has no automated run if
   its steps check nothing or its setup has a `do`.
2. **Observed** (`<name>[<role>] observed`), after all automated runs. Setup runs and settles for 2 s, then the
   runner prints `see` (in bold) and `watch` and waits for Enter. The steps run with their checks turned
   into waits, so the timing matches. Then you answer `ask`: Enter or `y` if you saw it, `n` if not, which fails
   the test and asks what you saw instead. It is skipped if its automated run failed, and if a step fails after Enter it prints
   `nothing to observe` and the reason.

`--unattended` skips the observed runs and reports them `not observed`. They don't fail, but a test counts toward
a bench record only when both of its runs pass.

### Run reports

Every run, failed, partial or unattended, ends by writing a report to `device_side-rig/` in the system temp
folder and printing its path: each suite's results with the reason for every failure and skip. The OS clears it
out in time.

### Bench records

When every test of an adapter passes, the run writes `docs/bench/<integration>/<action>.md`: the date, the Home
Assistant version, the devices' model and firmware, and each test's result. A failed or partial (`-k`) run writes
nothing. Records are evidence for people, not read by any script: the PR that clears an adapter's `experimental`
flag cites one.

### Tester reports

A passing [Test report](../../.github/ISSUE_TEMPLATE/test-report.yml) issue becomes its own record,
`docs/bench/<integration>/<action>-issue-<N>.md`, next to the rig's, so a rig run never overwrites it. It uses the
rig record's key/value table: `Source` cites the issue and the RC the tester ran (`tester report, #<N>, <rc>`).
Note the capabilities, fields and device_side options the report shows working. The tests table is optional.
