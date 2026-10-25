# ZHA turn_on_for: confirm by reading back OnTime

## Context

The ZHA `turn_on_for` adapter (slice 10, PR #32) reports `sent`. Rig tests on the Hue LTA004 (PR #34) showed that the OnOff cluster's OnTime attribute (0x4001) counts down live, and that a new timer replaces an old one. So a fresh read right after the command tells us whether our timer is running. Shelly (`integrations/shelly/rpc.py`) and Matter already confirm this way. The read goes into its own module, so a later ZHA `get_attributes` adapter can reuse it without touching `turn_on_for.py` and resetting its fingerprint.

Decisions (Jason, 2026-10-25):
- **Window:** `confirmed` when `requested_tenths − 30 ≤ OnTime ≤ requested_tenths` and `OnTime > 0`. The 3 s slack matches the rig's ZHA timing tolerance (`tests/rig/inventory.py` `TOLERANCE_S["zha"]`).
- **Read fails** (any exception, including ImportError) → `sent`, `detail: readback_failed`. **Read succeeds but is outside the window** → `sent`, `detail: timer_not_reported`. These are the details Shelly and Matter already use.
- **Tests:** a lazy import and a fake. No `zha` dev dependency.
- **`experimental` stays** for now.

## Changes

Work in worktree `wt/zha-confirm` off `release/v0.0.2`. First commit this plan as `docs/plans/2026-10-25-zha-ontime-confirm.md`.

1. **New `custom_components/device_side/integrations/zha/zcl.py`**: `async def read_attribute(hass, addr: Address, cluster_id: int, attribute: int) -> Any`.
   - Lazy-import `homeassistant.components.zha.helpers.get_zha_gateway` and `zigpy.types.EUI64` inside the function. The `zha` library is installed only where ZHA runs, and isn't in `.venv`.
   - Mirror `websocket_read_zigbee_cluster_attributes`:
     - `gateway.get_device(EUI64.convert(addr.ieee))`;
     - `device.async_get_cluster(addr.endpoint_id, cluster_id, cluster_type="in")`;
     - `await cluster.read_attributes([attribute], allow_cache=False, only_cache=False)`.
   - Return the value from the success dict. Raise if the device is missing or the attribute lands in the failure dict, so callers handle one failure path.
   - Docstring: the read is internals-only (the public route is an admin websocket command), and it runs only after the admin-checked command succeeded, so it grants no extra rights.

2. **`integrations/zha/turn_on_for.py`**:
   - Move `_ON_OFF_CLUSTER` to `zcl.py`, and add `ON_TIME = 0x4001` there.
   - After the command succeeds, read OnTime. Map the read to a status by the decisions above, logging read failures at debug as `shelly/rpc.py` does.
   - Add a `_READBACK_SLACK_TENTHS = 30` constant with a comment pointing at the rig tolerance.
   - Set `confirmable=True` in scope.
   - Update the class docstring: it says the adapter returns SENT.

3. **Tests** in `tests/integrations/zha/test_turn_on_for.py`, which patch `zcl.read_attribute`:
   - `confirmed`: at the request, and at request − 30.
   - `timer_not_reported`: 0, above the request, and request − 31.
   - `readback_failed`: the read raises.
   - Unauthorized: no read is attempted, and the status is still `admin_required`.
   - New `tests/integrations/zha/test_zcl.py`: a fake gateway/device/cluster injected through `sys.modules` for `homeassistant.components.zha.helpers` and `zigpy.types`. Cover:
     - a success value;
     - a failure dict that raises;
     - a missing device that raises;
     - the ImportError path (no module present).
   - The module must hold ≥95% line coverage.

4. **Docs**:
   - `docs/integrations.md` ZHA section: state the confirm rule and both `sent` details.
   - Plan `docs/plans/2026-10-23-device-side-repo-plan.md`:
     - open item 3 says confirmation is built;
     - slice 10's / the ZHA design line says `read OnTime -> CONFIRMED` (the line already anticipates "read-back of OnTime later").

5. **Rig**: no step-file change needed. `tests/rig/engine.py` `expected()` derives `confirmed` from `confirmable`. The fingerprint changes, so the old bench record goes stale.

## Verification

- `.venv/bin/pytest` (whole suite, plus coverage of `integrations/zha/`), then `pre-commit run --all-files`.
- `/audit-code` on the diff. Fix P0/P1; fix or file the rest, with a comment on each filed issue.
- **Ask Jason before the rig run.** Then run `scripts/rig.py` on the ZHA suites only, with the admin token. Expect `confirmed` on the bulb steps.
- Write the new `docs/bench/zha/turn_on_for.md` record with the new fingerprint, and check that `scripts/check_tiers.py` still reports experimental.
- Open a PR into `release/v0.0.2`, run `ci-green wt/zha-confirm` in the background, squash-merge, and remove the worktree and branch.

## Amendment (rig, 2026-10-25)

`bulb_on_then_off` failed on this branch and on `release/v0.0.2` alike: the `set: off` step leaves ZHA ignoring the
light's "on" report for 1.5 s, so HA stayed `off`. The bulb cases now wait 2 s after `set: off`, and
`docs/integrations.md` lists the race as a ZHA sharp edge.
