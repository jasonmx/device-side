# Rig and deploy lifecycle: failure modes and fixes

## Context

The rig lock (`flock` on `<git-common-dir>/device_side-rig.lock`) is taken at the top of `scripts/rig.py` `main()`
by `hold_rig()` and held across journal replay, the gate, `deploy.sh` (sync and restart), `wait_until_ready`, the
tests and cleanup. `--dry-run` takes none. The deploy is inside the lock; the trouble is what the lock does not cover:

1. A session found the lock free but HA running another worktree's tree, and stalled, unsure whether it could deploy.
2. A deploy restart left `device_side` `not_loaded`: ZHA's config entry hung in setup, and `device_side` lists `zha`
   in `after_dependencies`, so it waited forever. HA reached RUNNING only because bootstrap stage 2 timed out, and
   every household `device_side.*` call failed.

## Failure modes

| # | Gap | Effect |
|---|---|---|
| A | The lock spans one run; a session's work spans many (deploy, probe, edit, rerun). Between runs the deployed tree is whoever ran last. | "Free lock, foreign tree" is ambiguous; sessions stall. |
| B | `--no-deploy` and ad hoc probes take no lock and don't check the tree. | A probe hits another session's code. |
| C | The lock lives on the dev machine. HA restarts from other tooling, updates and the UI bypass it. | A restart mid-run drops the WebSocket; tests fail confusingly. |
| D | `RIG_STATUS_CMD` reports the tree on disk, not the tree HA loaded. | After a failed restart, `--no-restart` or a killed run, the next run skips the deploy and tests old code. |
| E | The sync deletes then copies into the live container. | A lazy adapter import in that window loads a partial tree. |
| F | `wait_until_ready` waits 180 s (HA's stage-2 timeout is 300 s) and, with the service missing, says "add the integration". | A stuck dependency reads as a missing entry; the run doesn't say the house is degraded. |
| G | `after_dependencies: [hue, matter, mqtt, shelly, zha]`; HA awaits each one's config-entry setup. | **Product bug:** one hung integration disables device_side for every integration in a user's house. |
| H | `cancel_on_signals()` is installed only in `run_rig`; a deploy failure is a `CalledProcessError` traceback. | SIGTERM mid-deploy drops the lock while HA restarts; the next run syncs into a booting HA. |
| I | A dry run is a lockless snapshot. | Read as "is the rig free?", it is stale at once. |

## Steps

### 1. Each run deploys what it tests (A, I)

- B stays as is, by choice: `--no-deploy` and ad hoc probes keep running against whatever tree HA has, unlocked.
- With every deploying run deploying its own tree, queuing behind the lock is safe. Update `docs/contributing/testing.md` (or
  wherever the rig workflow is documented) to say: queue behind the lock; your run redeploys.
- No multi-run session lease until restart ping-pong between sessions is measured.

### 2. Know what HA loaded (D, E)

- `rig.py` reads two trees from `RIG_STATUS_CMD`: synced and loaded (one per line, `synced <tree>` / `loaded <tree>`),
  and keeps accepting the old single-hash output as both. A loaded tree that differs from the local one forces a
  restart even when the synced tree matches.
- Document the contract in `tests/rig/env.example`: the restart command records the synced tree as loaded only on a
  successful restart; the sync command swaps the directory by rename.
- Drop `--no-restart`: its only effect is to create D.
- The maintainer's deploy tooling change lives outside this repo (gitignored notes).

### 3. Diagnose a bad restart (F)

In `wait_until_ready`:
- Wait up to 450 s after a restart, past stages 1 and 2 (120 s + 300 s): a restart behind a hung ZHA took ~350 s.
- With the service missing, HA running or still starting, read config entries over the admin WebSocket (`config_entries/get`, reusing `HAClient`
  from `tests/rig/client.py`). No device_side entry: keep the first-load hint. Otherwise print device_side's state and
  each `after_dependencies` entry that isn't `loaded` (for example `zha: setup_in_progress`), and say "device_side
  actions are unavailable in the house until this is fixed". Without an admin token, say what couldn't be checked.

### 4. Hold signals for the whole run (H)

Install the abort handlers in `main()` right after the lock, so deploy and wait finish under the lock or exit
cleanly. Catch `CalledProcessError` from `deploy.sh` with one line saying HA may be mid-restart.

### 5. One hung integration must not disable device_side (G): its own PR

- Remove `hue`, `matter`, `mqtt` and `shelly` from `after_dependencies`: nothing imports them, and targets resolve
  through `hass.config_entries` at call time.
- `zha`: `integrations/zha/zcl.py` imports `homeassistant.components.zha.helpers` inside a function. Check whether
  hassfest still requires the declaration for that, and whether the gateway is reachable without the import. If
  neither works, keep `zha` and record the risk in the PR.
- Unit test: actions register while a dependency's entry is still setting up; a call to its targets fails per target.
- A full rig run covers it (a behavior change the rig exercises: no `experimental` flag).

## Out of scope here

A lock on the HA host that every restart path honors (C). Revisit once steps 1 to 4 have run for a while.

## Verification

- `.venv/bin/pytest`: status parsing (old and new formats, loaded ≠ synced),
  the diagnosis branches (no entry, dependency stuck, admin token missing), a signal during deploy.
- Rig, on the maintainer's go: a dry run shows both trees; a full run from one worktree, then one from another redeploys
  its own tree.
- Step 5: hassfest CI green; restart with ZHA disabled leaves device_side loaded and the non-ZHA suites passing.
