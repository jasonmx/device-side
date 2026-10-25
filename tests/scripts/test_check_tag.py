"""scripts/check_tag.py: which tag may be cut from which branch."""

import pytest

from scripts import check_tag


@pytest.fixture
def released(repo):
    repo.commit()
    repo.git("tag", "v0.0.1")
    repo.git("tag", "v0.0.10rc1")  # an RC never counts as the latest release
    repo.commit()
    return repo


@pytest.mark.parametrize(
    ("tag", "branch"),
    [
        ("v0.0.2rc1", "release/v0.0.2"),
        ("v0.0.2rc3", "main"),
        ("v0.0.2", "main"),
        ("v0.1.0", "main"),
    ],
)
def test_allowed(released, tag, branch):
    assert check_tag.errors(released.path, tag, branch) == []


@pytest.mark.parametrize(
    ("tag", "branch", "error"),
    [
        ("v0.0.2rc1", "release/v0.0.3", "v0.0.2rc1 must be cut from release/v0.0.2 or, as a hotfix, from main"),
        ("v0.0.2rc1", "wt/topic", "must be cut from release/v0.0.2"),
        ("v0.0.3rc1", "main", "a hotfix RC from main must be v0.0.2rcN, not v0.0.3rc1"),
        ("v0.0.2", "release/v0.0.2", "a release is cut from main only, not release/v0.0.2"),
        ("v0.0.1", "main", "v0.0.1 is not above the latest release, v0.0.1"),
        ("v0.0.2-test", "main", "matches neither"),
        ("v0.0.10rc1", "release/v0.0.10", "v0.0.10rc1 already exists"),
    ],
)
def test_refused(released, tag, branch, error):
    assert any(error in problem for problem in check_tag.errors(released.path, tag, branch))


def test_first_release_needs_no_earlier_tag(repo):
    repo.commit()
    assert check_tag.errors(repo.path, "v0.0.1", "main") == []
    assert check_tag.errors(repo.path, "v0.0.1rc1", "main") == []


def test_main(released, capsys):
    assert check_tag.main(["v0.0.2rc1", "release/v0.0.2"], released.path) == 0
    assert check_tag.main(["v0.0.2rc1", "main", "extra"], released.path) == 2
    assert check_tag.main(["v0.0.1", "main"], released.path) == 1
    assert "error: v0.0.1 already exists" in capsys.readouterr().err
