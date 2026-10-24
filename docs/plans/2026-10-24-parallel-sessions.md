# Parallel sessions: one worktree per session

Agreed 2026-10-24. Implement in a fresh session, in its own worktree on `wt/parallel-sessions`, PR into
`release/v0.0.1`. It is the first change to follow its own rule.

## Decisions

- **Every session works in its own worktree**, including a lone one. The main checkout stays clean on the
  current `release/vX.Y.Z` and is never edited.
- **Branch per session, PR per session, merged by the session.** A session branches `wt/<topic>` off the
  release branch, opens a PR into it, and once `ci-green` passes merges it itself with
  `gh pr merge --squash --delete-branch`: one commit per session, so `git revert` rolls a session back. If the
  release branch moved meanwhile, rebase, push, `ci-green` again, then merge. PRs here isolate sessions and
  give rollback, not review; nothing reaches the live system until a tag. This replaces the repo plan's
  "no per-slice PRs" rule, which only held while sessions ran one at a time.
- **Local checks before every push.** `.venv/bin/pytest` and `pre-commit run --all-files` in the worktree, so
  failures surface in seconds and GitHub CI, which stays the merge gate (clean checkout, hassfest, HACS
  validate), usually goes green first time.
- **Jason's calls stay his**: the release PR into `main`, and every tag (RC or release).
- **No GitHub auto-merge.** `gh pr merge --auto` waits only on *required* checks; with none configured on
  `release/**` it merges at once. `ci-green` then a plain merge needs no repo settings.
- **The ignored household files live once, in the main checkout**, and every worktree reads them from there.
- **One rig run at a time**, enforced by a lock rather than a rule.

## Changes

1. **Household files resolve to the main checkout.** `tests/rig/inventory.py` gains `MAIN_CHECKOUT`: the parent
   of `git rev-parse --path-format=absolute --git-common-dir`, falling back to `REPO` when git fails (no repo,
   no git binary). `INVENTORY` and `ENV_FILE` hang off it; so does `check_private.PRIVATE_TERMS`. Without this
   the check finds no terms in a worktree and passes everything, which is how it behaves in CI.
   Tests: from a throwaway repo with a linked worktree (`git worktree add` in `tmp_path`), `MAIN_CHECKOUT`
   resolves to the main checkout; outside a repo it falls back to `REPO`.
2. **Rig lock.** `scripts/rig.py` takes a non-blocking `fcntl.flock` on `<git-common-dir>/device_side-rig.lock`
   at the start of `main`, before preflight reads the deployed tree, and holds it for the run. It writes the
   holder's branch and pid into the file; a second run exits non-zero naming them. `--dry-run` moves nothing and
   skips the lock. `flock` drops on crash, so no stale-lock cleanup. Test: a held lock makes a second acquire fail with the holder named.
3. **CI on `wt/**` pushes.** `lint.yml` and `tests.yml` run on push only for `main` and `release/**`, so a
   `wt/` push gets only hassfest and validate until the PR's `pull_request` runs attach, and a `ci-green` racing
   them passes on two of four workflows. Add `"wt/**"` to both push filters so the pushed sha carries all four.
4. **Faster CI installs.** In `tests.yml` and `lint.yml`, replace `setup-python`'s pip cache and `pip install`
   with `astral-sh/setup-uv` (pinned, cache on) and `uv pip install --system`, keeping `requirements_test.txt`
   as the tests' source. Compare install-step times on the PR against a prior run, and say so in its body.
5. **`.gitignore`**: add `.claude/worktrees/` (where `claude --worktree` and EnterWorktree put them).
6. **`uv.lock` and the `pyproject.toml` ruff dev group** (committed with this plan). Each worktree runs
   `uv sync` for its own `.venv`.
7. **Committed `.claude/settings.json`** for the allow rules every worktree needs: the two `WebFetch` domains
   now in `settings.local.json`, and relative `Bash(.venv/bin/pytest *)`. Drop the absolute-path pytest rules
   from `settings.local.json`: from a worktree they test the main checkout's code.
8. **Repo plan** (`docs/plans/2026-10-23-device-side-repo-plan.md`, the "Each slice is a commit…" paragraph):
   slices land by PR into the release branch, one per session; drop "no per-slice PRs" and the
   rule-evidence-points-at-a-sha workaround, since PR bodies now exist to hold it.
9. **CLAUDE.md**, within its editing rules (rule in the file, evidence in this PR):
   - **Parallel sessions**: worktree per session; main checkout clean on the release branch; pytest and
     `pre-commit run --all-files` locally before each push; `wt/<topic>` branch, PR into `release/vX.Y.Z`, merged by the session (squash) once `ci-green` passes, rebasing first
     if the base moved; release PRs into `main` and all tags are Jason's; `uv sync` in a new worktree; household files are read
     from the main checkout, never copied into a worktree; one rig run at a time (the lock refuses a second);
     remove the worktree and its branch once the PR merges.
   - **Layout**: about six lines naming directories, not files: `core/`, `features/`, `platforms/<platform>/`,
     `tests/{core,features,platforms,rig}`, `scripts/`, `docs/bench/`. Design detail stays in the repo plan.
   - **Conventions**: async throughout; `_LOGGER = logging.getLogger(__name__)`; services registered once in
     `async_setup`; American English matching HA; version lives in `manifest.json`.
   - **Development**: pytest from `.venv` (`uv sync`); pre-commit runs ruff and the household check; wait on CI
     with `ci-green`.
   - **Releases**: before tagging any RC, point Jason at a rig run (`scripts/rig.py`) and don't tag until he
     confirms it passed. Work lands on `release/vX.Y.Z` by self-merged PR.

Changes 1 and 2 are tooling: no `experimental`, and no adapter fingerprint moves.

## Done when

- From a linked worktree, `scripts/check_private.py` on a file naming an inventory entity fails.
- While one `scripts/rig.py` holds the lock (sitting at its approval gate), a second refuses, naming the first.
- Full test suite and coverage pass in the worktree; `ci-green` on the PR, then the session merges it.
