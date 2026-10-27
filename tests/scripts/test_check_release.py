"""scripts/check_release.py: the coverage bar on every adapter, and no experimental adapter in a release."""

import json
from pathlib import Path

from custom_components.device_side.core.scope import AdapterScope
from scripts import check_release as cr

# Every fake adapter is defined here, so this file is each one's module.
THIS_FILE = str(Path(__file__).relative_to(cr.REPO))


class FakeAdapter:
    def __init__(self, scope: AdapterScope):
        self.scope = scope


class FakeRegistry:
    def __init__(self, adapters: dict[tuple[str, str], AdapterScope]):
        self._adapters = {key: FakeAdapter(scope) for key, scope in adapters.items()}

    def matrix(self):
        yield "turn_off_for", "shelly", None
        for (action, integration), adapter in sorted(self._adapters.items()):
            yield action, integration, adapter


REGISTRY = FakeRegistry(
    {("turn_on_for", "shelly"): AdapterScope(), ("turn_on_for", "matter"): AdapterScope(experimental=True)}
)


def coverage(tmp_path: Path, covered: int, statements: int = 100) -> Path:
    path = tmp_path / "coverage.json"
    summary = {"covered_lines": covered, "num_statements": statements}
    path.write_text(json.dumps({"files": {THIS_FILE: {"summary": summary}}}))
    return path


def test_coverage_under_the_bar_is_an_error_experimental_or_not(tmp_path):
    data = json.loads(coverage(tmp_path, 94).read_text())
    assert cr.coverage_errors(REGISTRY, data) == [
        f"matter / turn_on_for: 94.0% line coverage of {THIS_FILE}, under 95%",
        f"shelly / turn_on_for: 94.0% line coverage of {THIS_FILE}, under 95%",
    ]
    assert cr.coverage_errors(REGISTRY, json.loads(coverage(tmp_path, 95).read_text())) == []
    assert cr.coverage_errors(REGISTRY, json.loads(coverage(tmp_path, 0, statements=0).read_text())) == []


def test_a_module_missing_from_coverage_is_an_error():
    [error] = cr.coverage_errors(FakeRegistry({("turn_on_for", "shelly"): AdapterScope()}), {"files": {}})
    assert "0.0% line coverage" in error


def test_main_prints_the_table_and_the_step_summary(tmp_path, monkeypatch, capsys):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert cr.main(["--coverage", str(coverage(tmp_path, 100))], REGISTRY) == 0
    assert capsys.readouterr().out.splitlines() == ["matter / turn_on_for  experimental", "shelly / turn_on_for"]
    assert summary.read_text().splitlines()[-2:] == ["| matter / turn_on_for | yes |", "| shelly / turn_on_for |  |"]


def test_release_fails_on_an_experimental_adapter(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert cr.main([], REGISTRY) == 0
    assert cr.main(["--release"], REGISTRY) == 1
    assert "matter / turn_on_for is experimental" in capsys.readouterr().err
    assert cr.main(["--release"], FakeRegistry({("turn_on_for", "shelly"): AdapterScope()})) == 0
    assert cr.main(["--coverage", str(coverage(tmp_path, 50))], REGISTRY) == 1


def test_main_reads_the_real_registry(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert cr.main([]) == 0
    assert "shelly / turn_on_for" in capsys.readouterr().out
