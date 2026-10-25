#!/usr/bin/env python3
"""Check an RC's audit record: every commit since the previous RC audited, no Critical or High left open.

The record is `docs/audits/<rc>.md`: YAML frontmatter (rc, base, passes, findings), then the audit-code report.
- `base` is the previous RC tag of the same version, or for rc1 the latest release tag that is an ancestor of the
  head (the root commit if none): the merge-base with main for a release branch, and right for a hotfix RC on main.
- Passes chain from it (`passes[0].from == base`, each `from` the previous `to`); each `to` is an ancestor of the head.
- Nothing outside `docs/audits/` changed after the last pass.
- A Critical or High finding is `fixed` (`fixed_in` inside a pass after the first) or `waived` (with a `reason`).
See docs/plans/2026-10-23-rc-audit-gate.md.

Usage: scripts/check_audit.py <rc> <head-sha>
       scripts/check_audit.py --base <rc>   (print the base /rc-audit starts rc1 or a new RC from)
"""

import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.check_tag import RC, git, name, releases  # noqa: E402

AUDITS = Path("docs") / "audits"
SEVERITIES = frozenset({"critical", "high"})


def sha(repo: Path, rev: str) -> str | None:
    return git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}", check=False) or None


def is_ancestor(repo: Path, ancestor: str, head: str) -> bool:
    command = ["git", "-C", str(repo), "merge-base", "--is-ancestor", ancestor, head]
    return subprocess.run(command, capture_output=True).returncode == 0


def expected_base(repo: Path, rc: str, head: str) -> str:
    """The previous RC tag of the same version, else the latest release tag under head, else the root commit."""
    match = RC.match(rc)
    version, number = tuple(map(int, match.groups()[:3])), int(match[4])
    earlier = [
        (int(found[4]), tag)
        for tag in git(repo, "tag", "--list", f"{name(version)}rc*", "--merged", head).split()
        if (found := RC.match(tag)) and int(found[4]) < number
    ]
    if earlier:
        return sha(repo, max(earlier)[1])
    if ancestors := releases(repo, merged_into=head):
        return sha(repo, ancestors[-1][1])
    return git(repo, "rev-list", "--max-parents=0", head).split()[-1]


def frontmatter(path: Path) -> dict:
    text = path.read_text()
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError(f"{path} has no YAML frontmatter between --- lines")
    data = yaml.safe_load(text[4:].split("\n---\n", 1)[0])
    if not isinstance(data, dict):
        raise ValueError(f"{path}'s frontmatter is not a mapping")
    return data


def errors(repo: Path, rc: str, head: str) -> list[str]:
    if not RC.match(rc):
        return [f"{rc} is not vX.Y.ZrcN"]
    if (head := sha(repo, head)) is None:
        return ["the head is not a commit"]
    path = repo / AUDITS / f"{rc}.md"
    if not path.exists():
        return [f"{AUDITS / path.name} is missing; run /rc-audit {rc}"]
    try:
        record = frontmatter(path)
    except (ValueError, yaml.YAMLError) as err:
        return [str(err)]

    problems = []
    if record.get("rc") != rc:
        problems.append(f"rc is {record.get('rc')!r}, not {rc}")
    base = expected_base(repo, rc, head)
    if sha(repo, str(record.get("base"))) != base:
        problems.append(f"base is {record.get('base')!r}, not {base[:7]}")

    passes = record.get("passes") or []
    if not passes:
        return [*problems, "no passes"]
    ranges = pass_ranges(repo, passes, base, head, problems)
    if code := unaudited(repo, ranges[-1][1], head):
        problems.append(f"changed after the last pass: {', '.join(code)}; run /rc-audit {rc} --fix-pass")

    for finding in record.get("findings") or []:
        problems += finding_errors(repo, finding, ranges[1:])
    return problems


def unaudited(repo: Path, last: str | None, head: str) -> list[str]:
    """Files outside docs/audits/ changed between the last pass and the head; nothing to say if the chain is broken."""
    if not last or not is_ancestor(repo, last, head):
        return []
    changed = git(repo, "diff", "--name-only", last, head).splitlines()
    return [file for file in changed if not file.startswith(f"{AUDITS.as_posix()}/")]


def pass_ranges(repo: Path, passes: list[dict], base: str, head: str, problems: list[str]) -> list[tuple]:
    """Each pass as (from, to) full shas (None where unresolvable), appending a problem per broken link."""
    ranges = []
    previous = base
    for index, audit_pass in enumerate(passes, 1):
        start, end = sha(repo, str(audit_pass.get("from"))), sha(repo, str(audit_pass.get("to")))
        if start != previous:
            problems.append(f"pass {index} starts at {audit_pass.get('from')!r}, not {(previous or '?')[:7]}")
        if end is None or not is_ancestor(repo, end, head):
            problems.append(f"pass {index} ends at {audit_pass.get('to')!r}, not an ancestor of the head")
        ranges.append((start, end))
        previous = end
    return ranges


def finding_errors(repo: Path, finding: dict, later: list[tuple[str | None, str | None]]) -> list[str]:
    label = f"finding {finding.get('id', '?')}"
    severity, status = finding.get("severity"), finding.get("status")
    if severity not in SEVERITIES:
        return [f"{label}: severity {severity!r} is not critical or high"]
    if status == "open":
        return [f"{label} ({severity}) is open"]
    if status == "waived":
        return [] if str(finding.get("reason") or "").strip() else [f"{label} is waived without a reason"]
    if status != "fixed":
        return [f"{label}: status {status!r} is not open, fixed or waived"]
    fixed_in = sha(repo, str(finding.get("fixed_in")))
    inside = fixed_in is not None and any(
        start and end and fixed_in != start and is_ancestor(repo, start, fixed_in) and is_ancestor(repo, fixed_in, end)
        for start, end in later
    )
    return [] if inside else [f"{label}: fixed_in {finding.get('fixed_in')!r} is not inside a pass after the first"]


def main(argv: list[str] | None = None, repo: Path = REPO) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] == "--base" and RC.match(argv[1]):
        print(expected_base(repo, argv[1], "HEAD"))
        return 0
    if len(argv) != 2 or argv[0] == "--base":
        print(__doc__.split("Usage: ", 1)[1].strip(), file=sys.stderr)
        return 2
    problems = errors(repo, *argv)
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if not problems:
        print(f"{argv[0]}: audit record covers every commit to the head; no open Critical or High.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
