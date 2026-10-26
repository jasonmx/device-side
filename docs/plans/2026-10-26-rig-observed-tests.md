# Rig: observed tests judge only what needs eyes

## Context

Jason finds attended rig runs confusing, for two reasons:

1. **The brief comes before the setup.** `_brief` (`tests/rig/engine.py`) runs before `_CaseRun.run()`, and a
   test's `set` steps are its first steps. So Enter is pressed while the light is wherever it was, and the move
   to the start state looks like part of the test.
2. **A machine check can end the case before the question.** In `_CaseRun.run`, a `StepFailure` from any
   `expect_*` or `sample` step aborts the case, so the `observe` step never runs: the person watched and is
   never asked, and the runner moves on to the next brief.

The principle agreed with Jason: **an observed test asks only what needs human judgment.** Whatever a machine can
check runs first, unattended, as its own test.

Agreed (AskUserQuestion, 2026-10-26):
- **One definition, run twice.** A test has `setup:`, `steps:` and an `observe:` block. The engine derives an
  automated case (setup + steps, every check) and an observed case (setup, then brief, Enter, the steps with
  checks turned into plain waits, then the question).
- **All automated cases first**, then one prompt saying how many tests need you, then the observed cases back to
  back.
- **An observed case whose automated case failed is skipped**, with that failure as the reason.
- **A failure in the observed run says so.** A setup failure fails the case before the brief, so the person is
  never told to watch. A call that raises after Enter prints `nothing to observe: <reason>` and waits for Enter
  before the next test.

## Step-file format

```yaml
- name: raise  # §2.1
  roles: [light_ct, group]
  setup:                      # runs before the brief, checks and all; never shown as the test
    - set: {state: on, brightness_pct: 20}
  steps:
    - call: {brightness: up, sweep_time: 5}
    - expect_response: {status: expected, integration: self}
    - sample: {attribute: brightness, for: 3, expect: rising}
    - expect_state: {brightness: 255, within: 2 + tol}
  observe:
    see: The light at 20 %, climbing to full over 5 s.   # what happens after Enter
    watch: Steps or flashes on the way up.
    ask: Did it climb smoothly to full?
```

Parser rules (`_parse_test`, `load_step_file`):
- `observe:` is a mapping with `see`, `watch` and `ask`, all non-empty strings. It replaces the old `brief:` key
  and the `observe` step kind. Both old forms are refused with a message pointing at the new one.
- `setup:` is optional, but **required when `observe:` is present**: the brief describes a known start state.
- `steps` may not contain `do` or `observe`. `setup` may contain any step kind except `observe`.
- New step `do: "<instruction>"`, allowed only in `setup` and only in a test with `observe:`. It prints the
  instruction and waits for Enter. It replaces `no_stale_snapshot`'s first question ("Change one light's color…
  Done?"), which is an action for the person, not a judgment.

Which cases a test yields (`cases()`):
- **Automated case**: `setup` + `steps` with every check. Only when `steps` holds at least one check
  (`expect_response`, `expect_error`, `expect_state`, `sample`) and `setup` has no `do`. Otherwise the test is
  observed only.
- **Observed case**: only for a test with `observe:`. Its id is `<name>[<role>] observed`, as a row of its own in
  the table and the record.

## Engine (`tests/rig/engine.py`)

- **`_CaseRun` mode.** `observed=False` runs as today. With `observed=True`:
  - setup steps run with their checks, then the brief prints and the runner waits for Enter. This moves `_brief`
    from `run()` into `_CaseRun.run`, between setup and steps.
  - Steps run with checks relaxed, so the timing the person sees stays the same:
    - `sample` becomes a wait of its `for`.
    - `expect_state` with `within` waits until the state holds or `within` elapses, and never fails. Without
      `within` it is skipped.
    - `expect_response` is skipped.
    - `expect_error` is skipped. The `call` before it still treats an error as expected, through the existing
      `following` argument.
  - A step error after Enter: print `nothing to observe: <step>: <reason>`, wait for Enter, then fail the case.
  - Otherwise ask `observe.ask` [y/N]. A no fails the case, as `_observe` does today.
- **`run()` ordering.**
  - Phase 1 runs every automated case of every planned suite, as today, with no briefs.
  - Phase 2, unless `--unattended`: print `N tests need you`. For each observed case whose automated twin
    passed (or which has none), run it in observed mode. Skip it if the twin failed, with detail
    `automated case failed`. EOF at a brief still makes that case unattended.
  - With `--unattended` (`ask=None`), observed cases are reported `not observed` without running.
  - Results stay grouped by suite for the table and records. Each `SuiteResult` collects both phases' cases.
- **Records.** A test with `observe:` proves its fields and capabilities only when both of its cases pass. Today
  an unobserved case already proves nothing, so a test whose observed case is `not observed` or skipped
  contributes nothing to `proven`. Implement it in `SuiteResult.proven` by pairing the cases by test name and
  role. `recordable` stays as is: a skipped observed case isn't a FAIL, but its automated twin's FAIL is.
- Remove the `observe` step kind (`_parse_observe`, `_observe`, `RigTest.questions`) and `Brief`. The new
  `Observe` dataclass holds see/watch/ask.

## Migration (14 observed tests in 4 files)

`tests/rig/steps/{move,stop,set_attributes,set_scene}.yaml`. Each test's leading `set` steps move to `setup:`,
the brief and the last `observe` become the `observe:` block, and `see` loses its "the light at X %, then" lead-in
where the setup now shows that. Cases that need care:
- `move.raise_after_soft_off`: setup is the set to 60 %, the move down, `expect_state off` and the wait. Steps
  are the move up, a 3 s wait and the stop. There's no check in the steps, so it is observed only.
- `set_scene.no_stale_snapshot`: setup is `do: Change one light's color in this scene in the Hue app.` Steps
  are the group off, the call and the group on. Observed only.
- `set_attributes.sets_color_while_off` and `set_scene.sets_while_off`: the final `set: on` stays in `steps`, and
  in observed mode the checks before it relax.

#48's `move.yaml` and `stop.yaml` are the newest of these files. Migrate them in #48 after this PR merges (a
rebase plus a format pass); `release/v0.0.2`'s copies are the other two files.

## Docs

`docs/contributing/testing.md`: the step table (adds `setup`, `do`; drops `observe`), "Observe steps" rewritten
around the two cases and the order of a run, and `--unattended`. Keep it brief, per the docs memory.

## Landing

- Its own PR into `release/v0.0.2`, from a new worktree, implemented in a **fresh session** (CLAUDE.md
  Planning). Save this plan to `docs/plans/2026-10-26-rig-observed-tests.md` in that worktree first.
- No adapter changes, so no fingerprints change and no bench records go stale.
- Then rebase #48, migrate its `move.yaml`/`stop.yaml`, and do the attended Hue rig run on the new format.

## Verification

- `tests/scripts/test_rig_engine.py`, with the fake HA client and fake `ask` already used there:
  - setup runs before the brief: the order of HA calls and prompts is setup, then the brief, then the first step.
  - an observed case relaxes checks: a `sample` that would fail doesn't, and the question is still asked.
  - a failed automated case skips its observed twin, with the reason.
  - a call that raises in observed mode prints `nothing to observe` and waits for Enter before the next case.
  - order: every automated case of every suite before the first brief, and the `N tests need you` count.
  - `--unattended`: observed cases `not observed` and no prompts; a test proves its scope only with both cases
    passing.
  - `do` waits for Enter. The parser refuses an old `brief:` key and an `observe` step, `do` in steps, and
    `observe:` without `setup:`.
- `tests/scripts/test_rig_steps.py`: every shipped step file parses in the new format.
- `.venv/bin/pytest`, `pre-commit run --all-files`, `/audit-code`, `ci-green`.
- On the rig, attended: `.venv/bin/python scripts/rig.py --integration hue`. Expect an unattended stretch, then
  `N tests need you`, then each brief appearing with the light already at its start.
