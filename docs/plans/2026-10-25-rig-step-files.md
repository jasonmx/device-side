# Slice 9a: rig step files

Agreed 2026-10-25. Implement in a fresh session, in worktree `wt/rig-step-files` off `release/v0.0.2`. First commit:
this plan saved as `docs/plans/2026-10-25-rig-step-files.md`.

## Context

Repo plan `docs/plans/2026-10-23-device-side-repo-plan.md`, delivery row 9a. The rig tests are hand-written pytest
modules per integration × action (`tests/rig/test_shelly_turn_on_for.py`, `test_shelly_turn_off_for.py`), so
every new adapter (Z2M slice 6 and Matter slice 11 are being built now) would need another one. Bench records are
written by hand with fingerprints computed ad hoc. 9a replaces both with declarative YAML step files that one async
engine runs against every inventory integration that has the adapter, writing bench records on a full pass.
The format must cover every planned action: timed on/off; `move`/`stop` ramps; `set_attributes`/`get_attributes`
while off; `set_scene`; and group targets, where every member is checked
(hue_dimmer `../hue-smooth-dimming/tests/RELEASE_CHECKLIST.md` §2–5). It lands before slice 6's rig test.

## Decisions

- **Engine: plain async interpreter, no pytest.** `scripts/rig.py` calls it, and 9b's one-file tester runner
  imports it unchanged. `-k` filters by test name, and the engine prints its own pass/fail table, which is also
  the bench table.
- **One file per action** (`tests/rig/steps/<action>.yaml`), run against every inventory integration with that
  adapter. The registry supplies the expected status (`confirmable` → `confirmed`, else `sent`), the tolerance
  (`TOLERANCE_S`) and the fields in scope (`AdapterScope.fields`). The only per-test escape hatch is
  `only: [<integration>]`. If `only:` blocks pile up, split the file.
- **Fixed step vocabulary, no Jinja.** Durations take `duration`, `tol` and `+ - *` arithmetic, parsed by a small
  safe evaluator (an AST walk over numbers, names and those operators). A new need means a new step in Python.
- **`observe:` y/N steps** handle visual checks such as "climbs smoothly, no flashes". The engine prints the
  prompt and waits, and N fails the test. `--unattended` skips them and reports them as `not observed`, and a
  record never lists a capability or field whose test had an unobserved step.
- **A full pass writes bench records.** When every test for an adapter passes, the engine writes
  `docs/bench/<integration>/<action>.md`: fingerprint, HA version, device model and firmware, date, the
  capabilities and fields exercised, and the table. Jason reviews and commits the diff. A partial or failed run
  writes nothing.
- **Fingerprint code is new, and the Shelly records are regenerated.** `scripts/fingerprint.py` defines the hash
  (AST of the adapter module with docstrings and the `AdapterScope(...)` assignment removed, sha256, first 16
  hex). Nobody tries to reproduce `c0e28e7223fe3e2f`/`a9d2084b2c700e20`. The rig run that accepts 9a rewrites
  both Shelly records.
- **Device model and firmware come from `config/device_registry/list`.** A non-admin token can call it (it has
  no `require_admin`, checked in HA source), mapped through the entity's `device_id` from
  `config/entity_registry/list_for_display` or `get_states` context. `render_template` isn't needed.

## Format sketch

```yaml
# tests/rig/steps/turn_on_for.yaml
action: turn_on_for
rig_seconds: 35                  # replaces the AST-read RIG_SECONDS
tests:
  - name: on_then_off
    roles: [switch_plug, light_onoff, light_wrapped]
    steps:
      - set: {state: off}
      - call: {duration: 6}
      - expect_response: {status: expected, integration: self}
      - expect_state: {state: on, within: tol}
      - wait: duration - tol
      - expect_state: {state: on}
      - expect_state: {state: off, within: 2 * tol}
  - name: refuses_brightness_out_of_scope
    roles: [light_onoff]
    steps:
      - call: {duration: 6, brightness_pct: 50}
      - expect_error: {key: all_targets_failed, summary: fields_not_tested}
```

Vocabulary: `set` (state and attributes, via plain HA services), `call` (the file's action,
`return_response`), `expect_response`, `expect_error`, `expect_state` (immediate, or `within:` a timeout via
`HAClient.wait_for`), `wait`, `sample` (poll an attribute for N seconds and assert monotonic / stopped / within
range, for `move`/`stop`), `observe`, `restore`. On a `group` role, `expect_state` checks every member.
`restore` runs automatically in a `finally` (the current `Snapshot` logic). The names above are a starting point:
they ship only once they can express hue_dimmer §2–5. Prove that by writing those checklist items as a
`tests/rig/steps/examples/` fixture that only the parser tests load (no adapter exists for them yet).

## Changes

1. **`tests/rig/engine.py`**: load and validate the step files (a schema error names the file, test and step),
   pick targets (inventory roles × registry adapters, honoring `only:`), run them in order on one `HAClient`,
   snapshot and restore, print the table, return a result model. It has no pytest import. Move `Snapshot` out
   of `conftest.py` and into here.
2. **`tests/rig/steps/turn_on_for.yaml`, `turn_off_for.yaml`**: port both Shelly modules test for test,
   including the refusal tests (`fields_not_tested`, `fields_not_supported`, `capability_not_tested`).
3. **`scripts/fingerprint.py`**: `fingerprint(path) -> str`, plus a CLI that prints every adapter's hash.
4. **Bench writer** (in the engine, or `scripts/bench.py` if it outgrows it): renders the record from the
   result model and the device registry. It fixes the record format that `check_tiers` (9c) will parse later.
5. **`scripts/rig.py`**: replace `run_pytest` with an engine call. `plan_lines`/`select` read `roles`/
   `rig_seconds` from YAML in place of `RigModule`'s AST read. Keep the lock, preflight, gate, deploy and
   `--dry-run`/`--no-deploy`/`--no-restart`/`--integration`. `-k` filters test names. Add `--unattended`.
6. **Delete** `tests/rig/test_shelly_*.py`, `tests/rig/conftest.py` and the `RigModule`/`rig_modules` AST code
   in `inventory.py`. Keep `client.py` and `inventory.py`'s roles, paths and env loading.
7. **Unit tests** (`tests/scripts/`, CI-safe, no HA): `test_rig_engine.py` runs the engine against a fake
   `HAClient` (state machine plus scripted responses), covering pass, a timeout fail, an expect_error mismatch,
   restore after a failure, `observe` under `--unattended`, `only:`, and group member checks.
   `test_rig_steps.py` parses every shipped step file plus the hue_dimmer example fixture. `test_fingerprint.py`
   checks that a docstring or `AdapterScope` edit leaves the hash alone and a code edit changes it. Extend
   `test_rig.py` for the new selection and plan lines.
8. **Docs**: in `docs/contributing/testing.md`, the token comes from a dedicated non-admin HA user. Note the ZHA
   exception: if an adapter needs admin context, the rig uses an admin token for that adapter only, and the doc
   says why. Also: how to write a step file and what `observe:` asks of the person running it. Update the repo
   plan's 9a row and Testing → Rig section to match.

No adapter changes, so no `experimental` flag. The Shelly fingerprints are newly defined, not changed.

## Verification

- `.venv/bin/pytest` (full suite, coverage) and `pre-commit run --all-files` pass in the worktree.
- `scripts/rig.py --dry-run` lists the Shelly tests from YAML with the same roles and time estimate as before.
- **Rig run (ask Jason first)**: `scripts/rig.py --integration shelly`. Every ported test passes, and the run
  rewrites both `docs/bench/shelly/*.md` with the new fingerprints, then Jason reviews them. Lights are restored.
- Self-merge per `CLAUDE.local.md` once `ci-green` passes. The regenerated Shelly records may ride the same PR or
  a follow-up, as Jason prefers.
