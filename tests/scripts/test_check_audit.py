"""scripts/check_audit.py: an RC's audit record covers every commit to its head, with no open Critical or High."""

import pytest
import yaml

from scripts import check_audit

RC = "v0.0.2rc1"


@pytest.fixture
def audited(repo):
    """v0.0.1 on main, one code commit on top, audited in one pass. Returns (repo, base, audited sha)."""
    base = repo.commit()
    repo.git("tag", "v0.0.1")
    return repo, base, repo.commit()


def record(repo, rc=RC, base=None, passes=(), findings=(), **extra) -> str:
    """Commit docs/audits/<rc>.md and return the new head."""
    data = {"rc": rc, "base": base, "passes": [{"from": start, "to": end} for start, end in passes], **extra}
    data["findings"] = list(findings)
    return repo.commit(f"docs/audits/{rc}.md", f"---\n{yaml.safe_dump(data)}---\n\n# Audit\n")


def errors(repo, head, rc=RC) -> list[str]:
    return check_audit.errors(repo.path, rc, head)


def test_one_clean_pass_passes(audited):
    repo, base, end = audited
    assert errors(repo, record(repo, base=base[:7], passes=[(base, end)])) == []


def test_a_fix_pass_covers_the_fix(audited):
    repo, base, end = audited
    fix = repo.commit()
    findings = [
        {"id": "H1", "severity": "high", "status": "fixed", "fixed_in": fix[:7]},
        {"id": "C1", "severity": "critical", "status": "waived", "reason": "not reachable from HA"},
    ]
    assert errors(repo, record(repo, base=base, passes=[(base, end), (end, fix)], findings=findings)) == []


def test_rc2_starts_at_rc1(audited):
    repo, base, end = audited
    repo.git("tag", RC, record(repo, base=base, passes=[(base, end)]))
    rc1 = repo.git("rev-parse", RC)
    later = repo.commit()
    assert errors(repo, record(repo, "v0.0.2rc2", base=rc1, passes=[(rc1, later)]), "v0.0.2rc2") == []
    head = record(repo, "v0.0.2rc2", base=base, passes=[(base, later)])
    assert errors(repo, head, "v0.0.2rc2") == [
        f"base is {base!r}, not {rc1[:7]}",
        f"pass 1 starts at {base!r}, not {rc1[:7]}",
    ]


def test_with_no_release_rc1_starts_at_the_root(repo):
    root = repo.commit()
    end = repo.commit()
    assert errors(repo, record(repo, rc="v0.0.1rc1", base=root, passes=[(root, end)]), "v0.0.1rc1") == []


def test_a_missing_record_is_refused(audited):
    repo, _, end = audited
    assert errors(repo, end) == [f"docs/audits/{RC}.md is missing; run /rc-audit {RC}"]


@pytest.mark.parametrize(
    ("rc", "head", "error"),
    [("v0.0.2", "HEAD", "v0.0.2 is not vX.Y.ZrcN"), (RC, "nope", "the head is not a commit")],
)
def test_bad_arguments(audited, rc, head, error):
    assert check_audit.errors(audited[0].path, rc, head) == [error]


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("# Audit\n", "has no YAML frontmatter"),
        ("---\n- a list\n---\n", "is not a mapping"),
        ("---\nrc: [unclosed\n---\n", "while parsing"),
    ],
)
def test_unreadable_frontmatter(audited, text, error):
    repo = audited[0]
    [problem] = errors(repo, repo.commit(f"docs/audits/{RC}.md", text))
    assert error in problem


def test_an_all_digit_sha_stays_a_string(tmp_path):
    path = tmp_path / "record.md"
    path.write_text("---\nbase: 0123456\npasses: [{from: 0123456, to: 1e10}]\n---\n")
    assert check_audit.frontmatter(path) == {"base": "0123456", "passes": [{"from": "0123456", "to": "1e10"}]}


def test_the_record_must_name_its_rc_and_base(audited):
    repo, base, end = audited
    assert errors(repo, record(repo, base=end, passes=[(base, end)])) == [f"base is {end!r}, not {base[:7]}"]
    head = repo.commit(
        f"docs/audits/{RC}.md", f"---\nrc: v0.0.2rc9\nbase: {base}\npasses: [{{from: {base}, to: {end}}}]\n---\n"
    )
    assert errors(repo, head) == [f"rc is 'v0.0.2rc9', not {RC}"]


def test_no_passes(audited):
    repo, base, _ = audited
    assert errors(repo, record(repo, base=base)) == ["no passes"]


def test_passes_must_chain_and_end_under_the_head(audited):
    repo, base, end = audited
    fix = repo.commit()
    head = record(repo, base=base, passes=[(base, end), (fix, fix)])
    assert errors(repo, head) == [f"pass 2 starts at {fix!r}, not {end[:7]}"]

    repo.git("checkout", "-q", "-b", "other", base)
    elsewhere = repo.commit("other.py")
    repo.git("checkout", "-q", "main")
    head = record(repo, base=base, passes=[(base, elsewhere)])
    assert f"pass 1 ends at {elsewhere!r}, not an ancestor of the head" in errors(repo, head)


def test_code_after_the_last_pass_is_refused(audited):
    repo, base, end = audited
    record(repo, base=base, passes=[(base, end)])
    head = repo.commit("code.py")
    assert errors(repo, head) == [f"changed after the last pass: code.py; run /rc-audit {RC} --fix-pass"]


@pytest.mark.parametrize(
    ("finding", "error"),
    [
        ({"id": "H1", "severity": "high", "status": "open"}, "finding H1 (high) is open"),
        ({"id": "H2", "severity": "high", "status": "waived", "reason": " "}, "finding H2 is waived without a reason"),
        ({"id": "M1", "severity": "medium", "status": "open"}, "finding M1: severity 'medium' is not critical or high"),
        ({"id": "H3", "severity": "high", "status": "done"}, "finding H3: status 'done' is not open, fixed or waived"),
        ({"severity": "high", "status": "fixed"}, "finding ?: fixed_in None is not inside a pass after the first"),
    ],
)
def test_findings_that_block(audited, finding, error):
    repo, base, end = audited
    assert errors(repo, record(repo, base=base, passes=[(base, end)], findings=[finding])) == [error]


def test_a_fix_inside_the_first_pass_is_not_a_fix(audited):
    repo, base, end = audited
    fix = repo.commit()
    finding = {"id": "H1", "severity": "high", "status": "fixed", "fixed_in": end}
    head = record(repo, base=base, passes=[(base, end), (end, fix)], findings=[finding])
    assert errors(repo, head) == [f"finding H1: fixed_in {end!r} is not inside a pass after the first"]


def test_main(audited, capsys):
    repo, base, end = audited
    assert check_audit.main([RC], repo.path) == 2
    assert check_audit.main(["--base", "v0.0.2"], repo.path) == 2
    assert check_audit.main(["--base", RC], repo.path) == 0
    assert capsys.readouterr().out.strip() == base
    assert check_audit.main([RC, end], repo.path) == 1
    assert "error: docs/audits" in capsys.readouterr().err
    head = record(repo, base=base, passes=[(base, end)])
    assert check_audit.main([RC, head], repo.path) == 0
    assert "no open Critical or High" in capsys.readouterr().out
