# RC audit gate

Goal: no `vX.Y.ZrcN` tag exists unless `/audit-code` has been run over the code it ships and no
Critical or High finding is left open. Lands as part of slice 10 of
`2026-10-23-device-side-repo-plan.md` (it owns the tag-format check this reuses).

## Decisions

| Question | Decision |
|---|---|
| Where the audit runs | Locally, by Jason's Claude session. CI only checks a committed record. No API key in CI, no vendored copy of the skill to drift from `~/.claude-ensio/skills/audit-code`. |
| What blocks | Any Critical or High whose status is `open`. `waived` needs a `reason`. Medium/Low never block. |
| Range | Previous RC tag of the same `vX.Y.Z` to the RC head; for `rc1`, merge-base with `main` (or the root commit while `main` has no code) to the RC head. |
| Timing | A `workflow_dispatch` job checks the record, then creates the tag. A failed audit means no tag. |

## Record: `docs/audits/vX.Y.ZrcN.md`

YAML frontmatter, then the skill's six-section report (pass 1, then each later pass under its own
heading).

```yaml
rc: v0.0.1rc1
base: 4e4b6da            # previous RC tag's sha, or the rc1 base above
passes:                  # contiguous: pass[0].from == base, pass[i].from == pass[i-1].to
  - from: 4e4b6da
    to: 9c1e2f0          # the sha audited
findings:                # Critical and High only; Medium/Low stay in the prose
  - id: H1
    severity: high       # critical | high
    status: fixed        # open | fixed | waived
    fixed_in: a1b2c3d    # required when fixed; must lie inside a later pass's range
    reason: ""           # required when waived
```

Fixing a finding changes code after the audit, so the fix commits get their own pass
(`/audit-code <prev to>..HEAD`). That keeps every shipped line audited without re-running the
whole range.

## `scripts/check_audit.py <rc> <head-sha>`

Fails (non-zero, one line per problem) when:

1. the record is missing, or `rc` doesn't match the filename;
2. `base` isn't what the range rule above computes;
3. passes don't chain from `base`, or any `to` isn't an ancestor of `<head-sha>`;
4. `git diff --name-only <last to>..<head-sha>` touches anything outside `docs/audits/` (code
   changed after the last pass);
5. a finding is `open`, a `fixed` lacks a `fixed_in` inside a later pass, or a `waived` lacks a
   `reason`.

Stdlib plus PyYAML (already pulled in by the HA test deps). Tests in `tests/scripts/` build a
throwaway git repo in `tmp_path` and cover each failure plus the passing case. The script is not
a cell module, so the 95% cell-coverage bar doesn't apply, but cover every branch anyway.

## `.github/workflows/cut-rc.yml`

- `on: workflow_dispatch` with input `rc`; refuses to run unless `github.ref` is `release/**` and
  `rc` matches `^v\d+\.\d+\.\d+rc\d+$` and its `X.Y.Z` matches the branch.
- Steps: checkout with `fetch-depth: 0` → require every check run on `HEAD` concluded `success`
  (same rule as `ci-green`: none attached is a failure) → `python scripts/check_audit.py "$RC"
  "$GITHUB_SHA"` → `git tag "$RC" && git push origin "$RC"` → `gh release create "$RC"
  --prerelease --generate-notes`.
- `permissions: contents: write` on this job only.
- Tags pushed with `GITHUB_TOKEN` don't trigger other workflows, so anything that must run on an
  RC (HACS release asset, slice 11) runs inside this job, not on `push: tags`.

## Bypass protection

A tag ruleset on `v*rc*` restricting creation to GitHub Actions, so a manual `git push --tags`
can't skip the gate. Check at implementation time whether rulesets are available on this private
repo's plan; if not, note it as a step for the day the repo goes public (slice 11).

## Local helper: `.claude/skills/rc-audit/SKILL.md`

`/rc-audit vX.Y.ZrcN [--fix-pass]`: computes the range by the rule above, invokes `/audit-code
<range>`, writes or appends the record (frontmatter + report), and lists the Critical/High it
recorded as `open`. Jason then fixes or waives each, runs `--fix-pass`, commits the record, and
dispatches `cut-rc`. Thin wrapper: all audit logic stays in the global skill.

## CLAUDE.md change (Releases section)

Replace "RCs are tagged `vX.Y.ZrcN` from it and run every tier." with:

> RCs are tagged only by the `cut-rc` workflow, which requires `docs/audits/vX.Y.ZrcN.md`
> (`/rc-audit`) covering every commit since the previous RC with no open Critical/High. Every
> tier runs on each RC.

## Done when

- `check_audit.py` tests green; `cut-rc` dry-run on a scratch `release/v0.0.0` branch refuses a
  missing record, an open High, and a post-audit code commit, then tags once fixed.
- Slice 10 row in the repo plan and the CLAUDE.md Releases line point at this gate.
- `v0.0.1rc1` is the first real RC cut through it.
