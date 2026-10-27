# Rig: clean up after an aborted run

## Context

The rig already tears down after itself: every case puts back the snapshot it took (`_CaseRun.run` → `Snapshot.restore`,
`tests/rig/engine.py`), `run()` puts device_side's options back (`EntryOptions.restore`), and `run_rig` turns
`RIG_PAUSE` automations back on (`resume`, `scripts/rig.py`). All of it hangs off `finally` blocks, so it only runs
when the process gets to unwind:

- **SIGTERM / SIGHUP** (a background run stopped by its session, a closed terminal): Python's default handler exits
  at once. No `finally` runs, so bulbs stay moved and automations stay off. This is the usual way an abort goes wrong.
- **Second Ctrl-C** during cleanup: `KeyboardInterrupt` cuts teardown off part-way.
- **SIGKILL, a crash, a sleeping laptop, a dropped HA connection**: nothing inside the process can survive these.

Aim: any abort gets cleaned up, either straight away or, at worst, by the next rig run.

## Approach (agreed: signals + journal, replayed automatically by the next run)

### 1. Signals behave like Ctrl-C (`scripts/rig.py`)

In `run_rig`, `loop.add_signal_handler` for SIGTERM and SIGHUP cancels the main task, which is what asyncio.run already
does for SIGINT. The existing `finally` chain then runs unchanged. On the first signal print
`Aborting: putting devices back (signal again to leave it to the next run).` A second signal is allowed to kill the
process: the journal (step 2) makes that safe, so cleanup needs no shielding.

`_CaseRun.steps` catches `Exception`, not `BaseException`, so `CancelledError` already gets through to the `finally`
in `_CaseRun.run`. Leave that as it is.

**Check: Ctrl-C at an observed prompt.** `answer()` runs `input` via `asyncio.to_thread` (engine.py:830, 859). Once
the task is cancelled, that thread stays blocked in `input()`, and `asyncio.run`'s executor shutdown can wait on it.
If a manual test hangs there, read prompts with `loop.add_reader(sys.stdin)` and drop the thread.

### 2. Write-ahead journal (new `tests/rig/journal.py`)

`Journal(path)`: a JSON file at `<git common dir>/device_side-rig.journal.json`, next to `LOCK_NAME`. That keeps it
shared by every worktree and out of the repo, which matters because it holds household entity IDs. Each write goes
to a temp file first and is moved into place with `os.replace`.

Contents, each written **before** the change it guards:

| Section | Written by | Before |
|---|---|---|
| `paused: [entity_id]` | `pause` | its `turn_off` call |
| `options: {...}` | `EntryOptions.apply` | the first save (the original values) |
| `taken`, `stored`, `power` | `Snapshot.take` | the case's first command to that entity |

`Snapshot.restore` clears `taken`/`stored` when it finishes, `run()`'s `finally` clears `options` and `resume` clears
`paused`. On a clean finish the file is deleted. The journal is an optional constructor argument (default `None`), so
the existing unit tests and fakes don't change.

### 3. Recovery (`scripts/rig.py`)

`recover(ha, admin, journal)` works through the journal in the order the `finally` chain uses:
`Snapshot(ha, power, device_side=…, taken=…, stored=…).restore()`, then `EntryOptions(admin).apply(original)`, then
`resume(ha, paused)`. It reuses the existing restore code, prints each thing it puts back and deletes the journal
once every step has been tried. A step that fails is printed, as `resume` does now. Restoring options needs
`HA_ADMIN_TOKEN`; without it, say so and leave that section in the journal.

- **Automatically:** in `main`, once `lock_rig` returns, the previous holder is dead (flock drops when its process
  dies). If a journal exists, connect, run `recover`, then carry on to the plan and gate. Recovery runs before the
  gate because it only puts the house back the way it was.
- **`--recover`:** take the lock, recover, exit without running tests.
- `--dry-run` takes no lock, so it only reports that a journal exists.

## Files

- `scripts/rig.py`: signal handlers, `--recover`, recovery in `main`, journal passed to `pause`/`resume`/`run`
- `tests/rig/journal.py` (new); `tests/rig/engine.py`: `Snapshot`, `EntryOptions`, `run()` take the journal
- `tests/scripts/test_rig.py`, `tests/scripts/test_rig_engine.py`, new `tests/scripts/test_rig_journal.py`
- `docs/contributing/testing.md` (or wherever rig.py usage is documented): one line on `--recover` and on the
  automatic replay

## Verification

- Unit tests (fake `HAClient`, as in `test_pause_turns_off_only_what_is_on_and_resumes_it`):
  - the journal is written before each mutation, cleared when the matching restore runs, and deleted on a clean run
  - a run cancelled mid-case restores the snapshot, the options and the paused automations, and leaves no journal
  - `recover` on a hand-written journal makes the same calls a normal teardown would
  - a SIGTERM sent to the running loop cancels it and the `finally` chain runs
- `.venv/bin/pytest`, `pre-commit run --all-files`, rig coverage at ≥95% where CI checks it.
- On the rig (one short action, e.g. `--action turn_on_for --unattended`, in the background):
  1. SIGTERM it mid-case: the light goes back and the `RIG_PAUSE` automations come back on; no journal is left.
  2. SIGKILL it mid-case: the journal stays. `rig.py --recover` puts everything back and deletes it.
  3. SIGKILL again, then start a normal run: it recovers before the gate.
  4. Ctrl-C at an observed prompt (watched, briefed first): it exits without hanging.
