"""scripts/check_tiers.py: tiers from bench records, the carry-forward rule, and the hard errors."""

import json
from pathlib import Path

import pytest

from custom_components.device_side.core.models import Tier
from custom_components.device_side.core.scope import AdapterScope
from scripts import check_tiers as ct
from scripts.fingerprint import fingerprint

# Every fake adapter is defined here, so this file's fingerprint is each one's current fingerprint.
CURRENT = fingerprint(Path(__file__))
STALE = "0000000000000000"
THIS_FILE = str(Path(__file__).relative_to(ct.REPO))


class FakeAdapter:
    def __init__(self, scope: AdapterScope):
        self.scope = scope


class FakeRegistry:
    def __init__(self, adapters: dict[tuple[str, str], AdapterScope]):
        self._adapters = {key: FakeAdapter(scope) for key, scope in adapters.items()}

    def adapter(self, action: str, integration: str) -> FakeAdapter | None:
        return self._adapters.get((action, integration))

    def matrix(self):
        yield "turn_off_for", "shelly", None
        for (action, integration), adapter in sorted(self._adapters.items()):
            yield action, integration, adapter


SHELLY = AdapterScope(domains=frozenset({"switch"}), capabilities=frozenset({"Switch", "Light"}))
ZHA = AdapterScope(fields=frozenset({"brightness"}))


def record(fp: str = CURRENT, capabilities: str = "`Switch`", fields: str = "none", result: str = "pass") -> str:
    return (
        "# Shelly · turn_on_for\n\n| | |\n|---|---|\n"
        f"| Result | {result} |\n| Date | 2026-10-25 |\n| Fingerprint | `{fp}` (`turn_on_for.py`) |\n"
        f"| Capabilities | {capabilities} |\n| Fields | {fields} |\n\n## Tests\n\n| Test | Target | Result |\n"
        "|---|---|---|\n| `on` | `switch` (switch_plug) | pass |\n"
    )


@pytest.fixture
def bench(tmp_path: Path):
    def _write(name: str, text: str) -> Path:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    _write.dir = tmp_path
    return _write


def tiers(registry: FakeRegistry, bench_dir: Path) -> dict[str, ct.AdapterTier]:
    found, errors = ct.compute(registry, bench_dir)
    assert errors == []
    return {f"{tier.integration}/{tier.action}": tier for tier in found}


def test_parse_record_reads_the_rig_table(bench):
    # A tester's record may stop after the key/value table.
    text = record(capabilities="`Light`, `Switch`").partition("\n## ")[0]
    parsed = ct.parse_record(bench("shelly/turn_on_for.md", text))
    assert parsed.fingerprint == CURRENT
    assert parsed.capabilities == {"Light", "Switch"}
    assert parsed.fields == frozenset()
    every = ct.parse_record(
        bench("zha/turn_on_for.md", record(capabilities=ct.ALL_CAPABILITIES, fields="`brightness`"))
    )
    assert every.capabilities is None
    assert every.fields == {"brightness"}


def test_parse_record_reads_the_repos_own_records():
    for path in ct.BENCH_DIR.glob("*/*.md"):
        assert len(ct.parse_record(path).fingerprint) == 16


@pytest.mark.parametrize(
    ("text", "error"),
    [
        (record().replace("| Fields | none |\n", ""), "missing Fields"),
        (record(result="fail"), "Result is 'fail', not pass"),
        (record(fp="abc"), "Fingerprint does not start"),
        (record(capabilities="Switch"), "Capabilities is neither"),
        (record(fields="brightness"), "Fields is neither"),
    ],
)
def test_parse_record_refuses_a_malformed_record(bench, text, error):
    with pytest.raises(ct.RecordError, match=error):
        ct.parse_record(bench("shelly/turn_on_for.md", text))


def test_experimental_needs_no_record(bench):
    registry = FakeRegistry({("turn_on_for", "matter"): AdapterScope(experimental=True)})
    [tier] = tiers(registry, bench.dir).values()
    assert (tier.tier, tier.fingerprint, tier.uncovered) == (Tier.EXPERIMENTAL, CURRENT, ())


def test_beta_when_current_records_cover_the_scope(bench):
    bench("shelly/turn_on_for.md", record(capabilities="`Light`, `Switch`"))
    bench("zha/turn_on_for.md", record(capabilities=ct.ALL_CAPABILITIES, fields="`brightness`"))
    registry = FakeRegistry({("turn_on_for", "shelly"): SHELLY, ("turn_on_for", "zha"): ZHA})
    found = tiers(registry, bench.dir)
    assert found["shelly/turn_on_for"].tier is Tier.BETA
    assert found["zha/turn_on_for"].tier is Tier.BETA


def test_untested_without_a_current_record(bench):
    bench("shelly/turn_on_for.md", record(fp=STALE, capabilities="`Light`, `Switch`"))
    [tier] = tiers(FakeRegistry({("turn_on_for", "shelly"): SHELLY}), bench.dir).values()
    assert tier.tier is Tier.UNTESTED
    assert tier.uncovered == ("no record with the current fingerprint that reached the device",)


def test_a_field_needs_a_current_record(bench):
    bench("zha/turn_on_for.md", record(capabilities=ct.ALL_CAPABILITIES))
    bench("zha/turn_on_for-issue-4.md", record(fp=STALE, capabilities=ct.ALL_CAPABILITIES, fields="`brightness`"))
    [tier] = tiers(FakeRegistry({("turn_on_for", "zha"): ZHA}), bench.dir).values()
    assert tier.tier is Tier.UNTESTED
    assert tier.uncovered == ("field `brightness`",)


def test_a_capability_carries_forward_from_a_stale_record(bench):
    bench("shelly/turn_on_for.md", record(capabilities="`Switch`"))
    bench("shelly/turn_on_for-issue-7.md", record(fp=STALE, capabilities="`Light`"))
    [tier] = tiers(FakeRegistry({("turn_on_for", "shelly"): SHELLY}), bench.dir).values()
    assert tier.tier is Tier.BETA


def test_a_stale_every_capability_record_carries_forward_every_capability(bench):
    bench("shelly/turn_on_for.md", record(capabilities="`Switch`"))
    bench("shelly/turn_on_for-issue-7.md", record(fp=STALE, capabilities=ct.ALL_CAPABILITIES))
    [tier] = tiers(FakeRegistry({("turn_on_for", "shelly"): SHELLY}), bench.dir).values()
    assert tier.tier is Tier.BETA


def test_a_current_record_that_reached_nothing_carries_nothing_forward(bench):
    bench("shelly/turn_on_for.md", record(capabilities="none"))
    bench("shelly/turn_on_for-issue-7.md", record(fp=STALE, capabilities="`Light`, `Switch`"))
    [tier] = tiers(FakeRegistry({("turn_on_for", "shelly"): SHELLY}), bench.dir).values()
    assert tier.uncovered == ("no record with the current fingerprint that reached the device",)


def test_an_unproven_capability_is_named(bench):
    bench("shelly/turn_on_for.md", record(capabilities="`Switch`"))
    [tier] = tiers(FakeRegistry({("turn_on_for", "shelly"): SHELLY}), bench.dir).values()
    assert (tier.tier, tier.uncovered) == (Tier.UNTESTED, ("capability `Light`",))


def test_every_capability_scope_needs_a_current_every_capability_record(bench):
    bench("zha/turn_on_for.md", record(capabilities="`OnOff`", fields="`brightness`"))
    bench("zha/turn_on_for-issue-2.md", record(fp=STALE, capabilities=ct.ALL_CAPABILITIES))
    [tier] = tiers(FakeRegistry({("turn_on_for", "zha"): ZHA}), bench.dir).values()
    assert tier.uncovered == (ct.ALL_CAPABILITIES,)


def test_sibling_records_union(bench):
    bench("zha/turn_on_for.md", record(capabilities=ct.ALL_CAPABILITIES))
    bench("zha/turn_on_for-issue-9.md", record(capabilities="none", fields="`brightness`"))
    [tier] = tiers(FakeRegistry({("turn_on_for", "zha"): ZHA}), bench.dir).values()
    assert tier.tier is Tier.BETA


def test_malformed_and_orphan_records_are_errors(bench):
    bench("shelly/turn_on_for.md", record(result="fail"))
    bench("shelly/move.md", record())
    bench("hue/turn_on_for-issue-3.md", record())
    _, errors = ct.compute(FakeRegistry({("turn_on_for", "shelly"): SHELLY}), bench.dir)
    assert [error.rpartition(": ")[2] for error in errors] == [
        "no hue adapter for turn_on_for",
        "no shelly adapter for move",
        "Result is 'fail', not pass",
    ]


def coverage(tmp_path: Path, covered: int, statements: int = 100) -> Path:
    path = tmp_path / "coverage.json"
    summary = {"covered_lines": covered, "num_statements": statements}
    path.write_text(json.dumps({"files": {THIS_FILE: {"summary": summary}}}))
    return path


def test_coverage_under_the_bar_is_an_error(tmp_path):
    registry = FakeRegistry(
        {("turn_on_for", "shelly"): SHELLY, ("turn_on_for", "matter"): AdapterScope(experimental=True)}
    )
    data = json.loads(coverage(tmp_path, 94).read_text())
    [error] = ct.coverage_errors(registry, data)
    assert error == f"shelly / turn_on_for: 94.0% line coverage of {THIS_FILE}, under 95%"
    assert ct.coverage_errors(registry, json.loads(coverage(tmp_path, 95).read_text())) == []
    assert ct.coverage_errors(registry, json.loads(coverage(tmp_path, 0, statements=0).read_text())) == []


def test_a_module_missing_from_coverage_is_an_error():
    [error] = ct.coverage_errors(FakeRegistry({("turn_on_for", "shelly"): SHELLY}), {"files": {}})
    assert "0.0% line coverage" in error


def test_main_prints_the_table_and_the_step_summary(bench, tmp_path, monkeypatch, capsys):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    bench("shelly/turn_on_for.md", record(capabilities="`Switch`"))
    registry = FakeRegistry(
        {("turn_on_for", "shelly"): SHELLY, ("turn_on_for", "matter"): AdapterScope(experimental=True)}
    )
    assert ct.main(["--coverage", str(coverage(tmp_path, 100))], registry, bench.dir) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"matter / turn_on_for  experimental  {CURRENT}",
        f"shelly / turn_on_for  untested      {CURRENT}  capability `Light`",
    ]
    assert (
        summary.read_text().splitlines()[-1]
        == f"| shelly / turn_on_for | untested | `{CURRENT}` | capability `Light` |"
    )


def test_main_fails_on_errors_and_on_untested_with_require_beta(bench, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    registry = FakeRegistry({("turn_on_for", "shelly"): SHELLY})
    assert ct.main([], registry, bench.dir) == 0
    assert ct.main(["--require-beta"], registry, bench.dir) == 1
    assert "shelly / turn_on_for is untested" in capsys.readouterr().err
    assert ct.main(["--coverage", str(coverage(tmp_path, 50))], registry, bench.dir) == 1
    bench("shelly/move.md", record())
    assert ct.main([], registry, bench.dir) == 1


def test_main_reads_the_real_registry_and_records(capsys):
    assert ct.main([]) == 0
    assert "shelly / turn_on_for" in capsys.readouterr().out
