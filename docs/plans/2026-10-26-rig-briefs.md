# Rig runner: brief each attended test before it runs

## Context

An `observe` step asks its question only after the test has run (`tests/rig/engine.py` `_observe`), so the
person at the lights learns what to watch for once it is over. During the 7b run it wasn't clear when each test
started or what to look for. Decided with Jason, 2026-10-26: brief every attended test first and wait for Enter.

## Design

- **Steps YAML:** a test with an `observe` step needs a `brief:` mapping with `see` (what the lights will do,
  setup included) and `watch` (the moment or detail to watch). `brief` on a test without `observe` is a schema
  error, as is a missing one. `_parse_test` accepts the key; `RigTest` gains a `brief` field.
- **Runner** (`run` in `engine.py`): before an attended case (it has an `observe`, `ask` is set, not skipped),
  print the brief and wait on `ask("Press Enter to start... ")`; the next case never starts on its own:

  ```
  --- move / raise on light_ct (3 of 12) ---
  You'll see: the light at 20 %, then a 5 s climb to full.
  Watch for: steps or flashes on the way up.
  You'll be asked: Did brightness climb smoothly to 100%, with no steps or flashes?
  Press Enter to start...
  ```

  "You'll be asked" lists every `observe` question in the test, in order. The count is attended cases in this
  run, after `-k` and skips. EOF at the prompt runs the case unattended (`NOT_OBSERVED`), as `--unattended`
  does. With `ask=None` nothing is printed or awaited.
- **Briefs** for every attended test on the release branch: `set_attributes.yaml` (1), `set_scene.yaml` (3
  tests, 4 questions; `no_stale_snapshot`'s brief says you'll be asked to edit the scene in the Hue app first),
  `examples/move.yaml` (5, parser examples, so they stay valid).
- **Tests** (`tests/scripts/test_rig_engine.py`, `test_rig_steps.py`): brief parsed; missing or stray brief
  rejected; the brief is printed and Enter awaited before the case's first step (fake `ask` records call order);
  EOF at the gate gives `NOT_OBSERVED`; unattended prints nothing. Every real step file loads.
- `docs/contributing/testing.md`, where `observe` is documented: one line on `brief`.

## After merge

The `hue-move` session rebases PR #48 onto it and writes briefs for its `move.yaml` and `stop.yaml` tests
before Jason's rig run.

## Steps

1. Worktree `wt/rig-briefs` off `release/v0.0.2` (this file is in it).
2. Implement, `.venv/bin/pytest`, `pre-commit run --all-files`, `/audit-code` on the diff.
3. PR into `release/v0.0.2`, `ci-green wt/rig-briefs` in the background, squash-merge, remove the worktree and
   branch. No adapter module changes, so no fingerprint moves.
