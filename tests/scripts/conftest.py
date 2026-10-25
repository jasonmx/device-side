import subprocess
from pathlib import Path

import pytest


class GitRepo:
    """A throwaway repository for the tag and audit checks: commits, tags and audit records."""

    def __init__(self, path: Path):
        self.path = path
        self.git("init", "-q", "-b", "main")

    def git(self, *args: str) -> str:
        command = ["git", "-C", str(self.path), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "tag.gpgsign=false"]
        command += ["-c", "commit.gpgsign=false", *args]
        return subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, file: str = "code.py", text: str | None = None) -> str:
        path = self.path / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text if text is not None else f"{path.read_text() if path.exists() else ''}x\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", f"change {file}")
        return self.git("rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> GitRepo:
    return GitRepo(tmp_path)
