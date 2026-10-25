# Slice 9c: release gates

Agreed 2026-10-25. Implement in a fresh session, in worktree `wt/release-gates` off `release/v0.0.2`. First commit:
this plan saved as `docs/plans/2026-10-25-release-gates.md`. Two PRs into `release/v0.0.2`, in order: **A (tiers)**
then **B (tags)**.

## Context

Repo plan row 9c: release gates land before `v0.0.2rc1`. 9a is done: `tests/rig/engine.py` writes bench records
(`render_record`, `write_records`) and `scripts/fingerprint.py` defines the hash. Nothing yet computes tiers:
`scripts/rig.py:plan_lines` guesses (`bench.exists()` → beta), `core/models.py:Tier` is unused, coverage isn't
measured, and any tag can be pushed by hand. 9c makes tiers computed and checked in CI, and makes every `v*` tag
come from a workflow that checks its gates.

## Decisions

- **Strictness.** PR/push CI fails only on hard errors and prints the tier table. "Every adapter beta" is enforced
  only by `check_tiers --require-beta` inside `cut-release`. An untested adapter on a release branch is normal.
- **Records are sibling files.** The rig writes `docs/bench/<integration>/<action>.md`; a tester report is
  `<action>-issue-<N>.md`. `check_tiers` unions all of an adapter's records, so a rig run never clobbers a
  tester's proof.
- **`AdapterScope.bench` is dropped**; records are found by that convention. (It sits in the scope declaration,
  so no fingerprint changes.)
- **Capabilities carry forward, fields don't.** A capability listed in any passing record of the adapter (any
  fingerprint) stays covered while at least one current-fingerprint record exists. A field needs a
  current-fingerprint record listing it. Why: the rig tests regressions in our call pattern; the field-less
  on/off call is the same call for every capability once first proven, and vendor behavior between them doesn't
  drift. Light fields do vary by call, so they re-prove.
- **Both `vX.Y.ZrcN` and `vX.Y.Z` tags come from workflows** (`cut-release-candidate`, `cut-release`); a tag ruleset on `v*`
  lets only GitHub Actions create, update or delete them. Jason dispatches both.
- **Hotfixes have exactly two paths, neither with a gate exception:**
  1. rig-testable: fix on `main`, rig run writes a current record, `cut-release`;
  2. needs a tester: fix on `main`, `cut-release-candidate` a hotfix RC, tester report becomes a record, `cut-release`.
  Either way `--require-beta` passes on its own; the release is stable immediately.
- **No soak check in `cut-release`.** Soak stays Jason's judgment.

## PR A: computed tiers

1. **`scripts/check_tiers.py`** (no `hass`; imports `AdapterRegistry.discover()` as `fingerprint.py:main` does,
   reuses `fingerprint()` and `adapter_path()`).
   - `parse_record(path) -> Record(fingerprint, capabilities: frozenset | ALL | none, fields, result)` from the
     key/value table `engine.render_record` writes. Error on a missing key or `Result` other than `pass`.
   - `compute(registry, bench_dir) -> list[AdapterTier]`: `experimental` if declared; else `beta` when every
     `scope.capabilities` entry and every `scope.fields` entry is covered by the rules above, else `untested`
     with the uncovered items listed. `capabilities=None` needs a current record saying "every capability the
     adapter addresses". Domains aren't checked: proof follows the call. `stable` isn't computed (it means "on
     `main`").
   - Hard errors (exit 1): malformed record; a record file with no matching adapter; with `--coverage
     coverage.json`, a non-experimental adapter module under 95% line coverage.
   - `--require-beta`: also fail on any `untested`.
   - Prints `integration / action  tier  fingerprint  uncovered…`; appends the same as a Markdown table to
     `$GITHUB_STEP_SUMMARY` when set.
2. **`scripts/rig.py:plan_lines`**: replace the `bench.exists()` guess with `check_tiers.compute`.
3. **`core/scope.py`**: drop `bench`. **`core/models.py:Tier`**: keep; `check_tiers` uses it.
4. **`.github/workflows/tests.yml`**: `pytest -q tests/ --cov=custom_components/device_side --cov-report=json`,
   then `.venv/bin/python scripts/check_tiers.py --coverage coverage.json`. (`pytest-cov` already comes with
   `pytest-homeassistant-custom-component`.) Add `coverage.json` to `.gitignore`.
5. **`.github/ISSUE_TEMPLATE/test-report.yml`**: text fields RC, HA version, integration, action, capability,
   device model, firmware (`sw_version`), per-test checklist, result, notes; the "Already tested by someone
   else? Still worth sending" line; label `test-report`. 9b will prefill it via URL params, so field `id`s are
   stable snake_case.
6. **Docs**: `docs/contributing/testing.md` gets how a passing report becomes `<action>-issue-<N>.md` (same table
   as a rig record, `Source` cites the issue, fingerprint from `scripts/fingerprint.py` at the RC tag).
   `CLAUDE.md` Tiers: the carry-forward rule replaces "existing records survive because…" wording where it
   conflicts, and records are `<action>*.md`. Repo plan: 9c row and "Tier computation" section to match
   (no `bench` path check).
7. **Tests** `tests/scripts/test_check_tiers.py`: a fake registry plus records in `tmp_path` covering
   experimental, beta, untested-by-field, carry-forward capability, `capabilities=None`, sibling union,
   malformed record, orphan record, coverage under 95%, `--require-beta`. Cover every branch.
8. **Records**: run `check_tiers` on the branch; if a Shelly record is stale, ask Jason for a rig run
   (`scripts/rig.py --integration shelly`) before `v0.0.2rc1`.

## PR B: tag gates

Per `docs/plans/2026-10-23-rc-audit-gate.md`, with these changes (edit that plan to match):

- **Range rule for rc1**: base = the latest `vX.Y.Z` release tag that is an ancestor of the head (root commit if
  none). Same as merge-base with `main` for a release branch, and also right for a hotfix RC on `main`.
- **The workflow is `cut-release-candidate`** (renamed from `cut-rc` everywhere: the gate plan, the repo plan, the proposed `CLAUDE.local.md` line).
- **`cut-release-candidate` runs on `release/**` or `main`.** On a release branch, `X.Y.Z` must match the branch; on `main`,
  it must be one patch above the latest release (hotfix RC).

Files:

1. **`scripts/check_audit.py`** + `tests/scripts/test_check_audit.py` (throwaway git repo in `tmp_path`), as in
   the gate plan.
2. **`scripts/require_green.sh <sha>`**: every check run on the sha except the calling workflow's own concluded
   `success`, and at least one exists (the `ci-green` rule; that tool is personal, so not reused).
3. **`.github/workflows/cut-release-candidate.yml`**: as in the gate plan, plus the branch rule above; `--prerelease`.
4. **`.github/workflows/cut-release.yml`**: `workflow_dispatch` input `version`; only on `main`; version
   matches `^v\d+\.\d+\.\d+$` and is above the latest release tag; `require_green.sh`; `uv sync --locked`;
   `check_tiers.py --require-beta`; tag, push, `gh release create` (full release). `contents: write` on that
   job only.
5. **Tag ruleset** on `refs/tags/v*` (creation, update, deletion), bypass only GitHub Actions (integration
   15368), no admin bypass. Created with `gh api` after PR B merges; verify a `git push` of a test tag is
   refused and a `cut-release-candidate` dispatch on a scratch tag succeeds. The repo is public, so rulesets are available.
6. **`.claude/skills/rc-audit/SKILL.md`**: `/rc-audit vX.Y.ZrcN [--fix-pass]`, thin wrapper over the project's
   `audit-code` skill, as in the gate plan.
7. **Docs**: `CLAUDE.local.md` Releases (Jason's file; propose the diff, don't edit unasked): RC line per the
   gate plan; release line "Jason dispatches `cut-release`"; hotfix line replaced by the two paths above.
   `CLAUDE.md` Pull requests: none. Repo plan 9c row points at this plan.

## Verification

- `.venv/bin/pytest` and `pre-commit run --all-files` in the worktree; CI's step summary shows the tier table
  with Shelly `beta` (or `untested` with the stale items named) and Z2M/Matter `experimental`.
- Mutate a Shelly adapter's code in a scratch commit: `check_tiers` reports it `untested` (no current record, so
  nothing carries forward) and `--require-beta` exits 1. The carry-forward case itself is covered by unit tests.
- PR B: dispatch `cut-release-candidate` on a scratch `release/v0.0.0` branch: refuses a missing record, an open High, a
  post-audit code commit, then tags once fixed; delete the scratch tag and branch afterwards. Dispatch
  `cut-release` from a non-`main` ref: refused. Manual `git push origin v0.0.0-test`: refused by the ruleset.
- Self-merge each PR per `CLAUDE.local.md` once `ci-green` passes. `v0.0.2rc1` is the first real RC through it.
