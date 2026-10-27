# Simplify adapter tiers to a release flag

## Context

Tiers today are computed by `scripts/check_tiers.py` from bench records: an AST fingerprint per adapter
(`scripts/fingerprint.py`), capability carry-forward, per-field and per-option on/off proof, "reached the device"
filtering. It's the most edge-case-heavy part of the pipeline (PR #88 was another round of it), and it barely
earns its keep: 8 of the ~10 adapters carry `experimental=True`, so the computed `untested`/`beta` path only
judges Shelly. Goal: a faster pipeline with fewer surprising states, while releases still ship only
hardware-proven code.

## Your proposal: two hand-set flags (`experimental`, `untested`)

**Pros**
- Deletes the fingerprint and every carry-forward rule. No more "a refactor silently reset us to untested",
  no fingerprint lookup at an RC tag for tester reports, no surprise state from a record that "reached nothing".
- State lives in the code where you can see it: `rg experimental=True` is the whole picture, and a PR diff shows
  each change of state.
- Records go back to being evidence for people, not something a parser reads. The rig engine stops tracking
  fields and capabilities.
- Faster: refactors and perf work no longer need a rig run just to get beta back.

**Cons**
- **No automatic invalidation.** Right now, changing a tested adapter forces a retest. With flags, that's down to
  whoever opens the PR (usually an agent) remembering to set the flag. For rig-testable adapters the rig run you
  already do before every RC covers this. The real gap is scope only testers can reach: a refactor there would
  ship untested unless someone sets the flag.
- No machine-checked proof per capability, field or option. "Proof follows the call" stays as a review rule,
  and reviewers can miss things.
- Clearing a flag takes its own small PR that cites the record or issue. That's a step, but an explicit one.

## Recommendation: go one step simpler, with one flag

Both of your flags block the release. The only difference between them is the coverage waiver. I'd merge them:

- **`experimental=True`** means *not in a stable release*. `cut-release` fails while any adapter has it.
- **The 95% per-module coverage bar applies to every adapter**, with no waiver. RCs ship experimental code to
  testers, so it ought to be tested. And with agents writing the tests, the waiver doesn't buy much speed.
- **Clearing the flag** takes a PR that cites a passing rig record or tester issue covering the scope.
- **Process rule in place of the fingerprint:** a behavior change to a released adapter that the rig can't
  exercise sets `experimental` again. Anything the rig can reach is covered by the rig run before each RC, which
  must be the full suite, not the per-action filtered runs used day to day.
- Hotfix paths don't change; "rig run writes a current record" becomes "rig run passes".

That leaves one boolean with one meaning, and no state that a computer works out for you. If you'd rather keep
the waiver for outside contributors, your two-flag version is the next-best choice. It adds about 10 lines.

## Changes

- `custom_components/device_side/core/models.py`: delete `Tier`.
- `scripts/check_tiers.py` → rename `scripts/check_release.py` (~40 lines): coverage bar on every adapter module
  (`--coverage`), and `--release` fails on any `experimental` adapter. Prints the flag table to the step summary.
- Delete `scripts/fingerprint.py` and `tests/scripts/test_fingerprint.py`.
- `tests/rig/engine.py`: drop the Fingerprint/Capabilities/Fields/Options rows and the field/capability
  tracking (`render_record`, ~L568–591, ~L1007–1017). Keep the per-test table, the HA version and the devices.
  Keep the "capability the adapter can't address fails the case" check if it guards the rig itself.
- `scripts/rig.py`: drop the tier column from the run preview (L35, L93–104).
- Tests: shrink `test_check_tiers.py` to coverage and release-gate cases. Delete the record-bookkeeping tests in
  `test_rig_engine.py` (L752, L948, the Options-row part of L1352).
- Workflows: `tests.yml` and `cut-release.yml` call the new script.
- Docs: replace the CLAUDE.md "Tiers" section with ~5 lines. Update `CLAUDE.local.md` (release and hotfix
  bullets), `CONTRIBUTING.md` L30, `docs/contributing/testing.md` (~L130–148) and the repo plan's tier section.
  Existing bench records stay as they are.

## Lines freed (approx.)

| Area | Now | After |
|---|---|---|
| check_tiers + tests | 500 | ~110 |
| fingerprint + tests | 236 | 0 |
| rig engine + tests (record bookkeeping) | — | −150 to −200 |
| models, rig.py, test_rig | — | −25 |
| **Code + tests** | | **≈ −800** |
| Docs (CLAUDE.md, testing.md, plan, local) | | ≈ −60 |

## Verification

- `.venv/bin/pytest --cov --cov-report=json` and then `scripts/check_release.py --coverage coverage.json`. The
  first real check: do the 8 experimental adapters already clear 95%? If any don't, add tests in the same PR.
- `scripts/check_release.py --release` fails while any adapter is experimental, and passes on a branch with
  none.
- A rig run with `-k` on one suite writes a record without the removed rows.
- `pre-commit run --all-files`; `rg -i "fingerprint|tier|beta|untested"` comes back clean apart from history.
