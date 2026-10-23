# The rig

The rig is a live Home Assistant with real devices on it. Rig tests call `device_side.*` actions over HA's
WebSocket API and watch the devices change state. There is no dev HA: on the maintainer's rig the devices
are **in-use household lights and plugs**, so every run is approval-gated.

**Agents ask before every rig run, every time.** That includes `--no-deploy` runs and reruns of a single
test. The gate exists so occupants aren't startled by devices switching on and off.

## One-time setup

1. **Deploy path.** `scripts/deploy.sh` installs the integration with two verbs of pi-stack's `ha-shim`,
   reached through the `ha` SSH alias:
   - `ssh ha ds-sync <branch>` fetches `<branch>` into a device-side clone on the Pi (`/home/pi/device-side`)
     and replaces `/config/custom_components/device_side` inside the HA container with that branch's tree.
     It installs only what is pushed to GitHub, never a local working tree.
   - `ssh ha restart homeassistant` restarts HA.

   `ssh ha ds-status` prints the tree hash last installed, so the runner can skip a deploy and its restart.
   The clone is made once, by hand, with a read-only deploy key (the repo is private).
2. **Token.** Create a long-lived token for a **non-admin** HA user (Profile > Security). The rig only calls
   services and reads states; restarts go through the shim, not the API.
3. **`.env.rig`** at the repo root (gitignored), from `tests/rig/env.example`: `HA_URL`, `HA_TOKEN`, and
   `RIG_SSH` (default `ha`).
4. **Inventory.** Copy `tests/rig/inventory.example.yaml` to `tests/rig/inventory.yaml` (gitignored) and list
   the rig's entities per platform, each with role tags: `switch_plug`, `light_onoff` (a relay shown as a light),
   `light_dimmable`, `light_ct`,
   `light_color`, `group`, `scene`. A test that needs a role the inventory lacks skips.

## Running

```sh
scripts/rig.py --dry-run          # preflight only: reads, prints the plan, changes nothing
scripts/rig.py                    # preflight, y/N gate, deploy + restart if needed, tests
scripts/rig.py --no-deploy        # test whatever HA already runs
scripts/rig.py --platform shelly -k switch
```

Preflight is read-only. It prints the inventory, one line per adapter (`shelly / turn_on_for -> switch.plug
(experimental)`), whether HA's installed tree matches `HEAD`, whether a restart will happen, and an
estimated duration. Then it asks `Proceed? [y/N]`. `DEVICE_SIDE_RIG_APPROVED=1` answers the gate for a
caller without a terminal (an agent that already has the human's yes in the conversation).

A deploy refuses to start if `custom_components/device_side` has uncommitted changes, or if `origin/<branch>`
doesn't match `HEAD`, because `ds-sync` installs from GitHub. Push first.

From a Claude Code session, the runner's own `ssh` and HTTP calls need the sandbox off. Each run is
user-approved anyway.

Rig tests never run in a unit `pytest`: `tests/conftest.py` skips `tests/rig` unless `DEVICE_SIDE_RIG=1`, and
the rig fixtures skip every test unless `DEVICE_SIDE_RIG_APPROVED=1`. The runner sets both, drops the HA test
plugin (it blocks sockets) and stops conftest lookup at `tests/rig`.

## First load

The first approved deploy is the integration's first load in any HA. After it, check by hand:

- [ ] *Settings > Devices & services > Add integration > Device Side*: the entry adds and shows as loaded,
      and `ssh ha err` has nothing from `device_side`. The runner waits for `device_side.turn_on_for` and
      stops with this hint if the entry is missing. Add it, then rerun with `--no-deploy`.
- [ ] *Developer tools > Actions*: the actions appear with their translated names and descriptions.
- [ ] Pick `device_side.turn_on_for` and select only a switch: the brightness, color and transition
      fields hide. Add a dimmable light: brightness and transition appear.

## Writing a rig test

One module per adapter, `tests/rig/test_<platform>_<feature>.py`, with two literal constants the runner reads
without importing the module: `ROLES` (the inventory roles it uses) and `RIG_SECONDS` (its estimated run
time). Cover one happy path and one `unsupported` path; branches belong in unit tests.

- `require_adapter(platform, feature, role)` returns the inventory entity, or skips.
- `snapshot.take(entity_id)` before touching an entity. Teardown restores its state, brightness and color
  temperature or color, and logs rather than fails if a restore doesn't take.
- `timing(platform)` is the tolerance: Shelly and Hue 2 s, Zigbee and Matter 3 s. Assert windows, not
  instants: still on at `duration - tolerance`, off by `duration + tolerance`. Keep durations to 5-8 s.
- `ha.call_service(..., return_response=True)` returns the per-entity response. A call where every target
  fails raises `HAError` with `translation_key == "all_targets_failed"`.

## Recording a pass

A rig pass that promotes an adapter becomes `docs/bench/<platform>/<feature>.md`: date, HA version, device model
and firmware (from the device page), the adapter's fingerprint, and the source (`rig run` or the test-report
issue).
