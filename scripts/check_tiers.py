#!/usr/bin/env python3
"""Compute every adapter's tier from its bench records and check the records and coverage behind it.

Records are `docs/bench/<integration>/<action>.md` (a rig run) and `<action>-issue-<N>.md` (a tester report); an
adapter's tier draws on all of them. A capability listed by any passing record stays covered while the adapter has
at least one record with its current fingerprint that reached the device; a field needs a current-fingerprint
record listing it.

Exits 1 on a malformed record, a record with no adapter, a non-experimental adapter module under 95% line coverage
(with --coverage), or, with --require-beta, any adapter that is not beta or experimental.

Usage: scripts/check_tiers.py [--coverage coverage.json] [--require-beta]
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from custom_components.device_side.core.models import Tier  # noqa: E402
from custom_components.device_side.core.registry import AdapterRegistry  # noqa: E402
from scripts.fingerprint import adapter_path, fingerprint  # noqa: E402

BENCH_DIR = REPO / "docs" / "bench"
COVERAGE_BAR = 95.0
ALL_CAPABILITIES = "every capability the adapter addresses"
_KEYS = ("Result", "Fingerprint", "Capabilities", "Fields")
_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|$")
_NAME = re.compile(r"`([^`]+)`")
_HASH = re.compile(r"`([0-9a-f]{16})`")


class RecordError(ValueError):
    """A bench record check_tiers cannot read; the message names the file."""


@dataclass(frozen=True, slots=True)
class Record:
    path: Path
    fingerprint: str
    # None: every capability the adapter addresses, as AdapterScope.capabilities=None means.
    capabilities: frozenset[str] | None
    fields: frozenset[str]


@dataclass(frozen=True, slots=True)
class AdapterTier:
    integration: str
    action: str
    tier: Tier
    fingerprint: str
    uncovered: tuple[str, ...] = ()


def _names(path: Path, key: str, value: str) -> frozenset[str]:
    if value == "none":
        return frozenset()
    if not (names := _NAME.findall(value)):
        raise RecordError(f"{path}: {key} is neither `none` nor a list of `names`: {value!r}")
    return frozenset(names)


def parse_record(path: Path) -> Record:
    """The key/value table engine.render_record writes; raises RecordError on a missing key or a non-pass result."""
    rows = {}
    for line in path.read_text().splitlines():
        if line.startswith("## "):
            break
        if (match := _ROW.match(line.strip())) and not match[1].startswith("-"):
            rows[match[1]] = match[2]
    if missing := [key for key in _KEYS if key not in rows]:
        raise RecordError(f"{path}: missing {', '.join(missing)}")
    if rows["Result"] != "pass":
        raise RecordError(f"{path}: Result is {rows['Result']!r}, not pass")
    if not (fp := _HASH.match(rows["Fingerprint"])):
        raise RecordError(f"{path}: Fingerprint does not start with a 16-digit `hash`")
    capabilities = rows["Capabilities"]
    return Record(
        path=path,
        fingerprint=fp[1],
        capabilities=None if capabilities == ALL_CAPABILITIES else _names(path, "Capabilities", capabilities),
        fields=_names(path, "Fields", rows["Fields"]),
    )


def read_records(registry: AdapterRegistry, bench_dir: Path) -> tuple[dict[tuple[str, str], list[Record]], list[str]]:
    """Every record under bench_dir by (action, integration), and an error per unreadable or orphaned file."""
    records: dict[tuple[str, str], list[Record]] = {}
    errors = []
    for path in sorted(bench_dir.glob("*/*.md")):
        # Actions use underscores, so the action is the stem up to any `-issue-<N>` suffix.
        key = (path.stem.split("-", 1)[0], path.parent.name)
        if registry.adapter(*key) is None:
            errors.append(f"{path}: no {key[1]} adapter for {key[0]}")
            continue
        try:
            records.setdefault(key, []).append(parse_record(path))
        except RecordError as err:
            errors.append(str(err))
    return records, errors


def uncovered(scope, current_hash: str, records: list[Record]) -> list[str]:
    """What in the scope no record covers, by the carry-forward rule in the module docstring."""
    # A record that reached nothing (every test unattended or skipped) proves no call, so it carries nothing forward.
    current = [
        record
        for record in records
        if record.fingerprint == current_hash and (record.capabilities is None or record.capabilities or record.fields)
    ]
    if not current:
        return ["no record with the current fingerprint that reached the device"]
    missing = []
    if scope.capabilities is None:
        if not any(record.capabilities is None for record in current):
            missing.append(ALL_CAPABILITIES)
    else:
        proven = set()
        for record in records:
            proven |= scope.capabilities if record.capabilities is None else record.capabilities
        missing += [f"capability `{name}`" for name in sorted(scope.capabilities - proven)]
    fields = frozenset().union(*(record.fields for record in current))
    missing += [f"field `{name}`" for name in sorted(scope.fields - fields)]
    return missing


def compute(registry: AdapterRegistry, bench_dir: Path = BENCH_DIR) -> tuple[list[AdapterTier], list[str]]:
    """Each adapter's tier (never stable: that means on `main`), and the errors read_records found."""
    records, errors = read_records(registry, bench_dir)
    tiers = []
    for action, integration, adapter in registry.matrix():
        if adapter is None:
            continue
        current_hash = fingerprint(adapter_path(adapter))
        if adapter.scope.experimental:
            tiers.append(AdapterTier(integration, action, Tier.EXPERIMENTAL, current_hash))
            continue
        missing = uncovered(adapter.scope, current_hash, records.get((action, integration), []))
        tier = Tier.UNTESTED if missing else Tier.BETA
        tiers.append(AdapterTier(integration, action, tier, current_hash, tuple(missing)))
    return tiers, errors


def coverage_errors(registry: AdapterRegistry, coverage: dict) -> list[str]:
    """A non-experimental adapter module under the bar, or absent from the report, is an error."""
    percent = {}
    for name, entry in coverage["files"].items():
        summary = entry["summary"]
        statements = summary["num_statements"]
        percent[(REPO / name).resolve()] = 100.0 * summary["covered_lines"] / statements if statements else 100.0
    errors = []
    for action, integration, adapter in registry.matrix():
        if adapter is None or adapter.scope.experimental:
            continue
        path = adapter_path(adapter).resolve()
        covered = percent.get(path, 0.0)
        if covered < COVERAGE_BAR:
            errors.append(
                f"{integration} / {action}: {covered:.1f}% line coverage of {path.relative_to(REPO)}, "
                f"under {COVERAGE_BAR:.0f}%"
            )
    return errors


def report(tiers: list[AdapterTier]) -> tuple[list[str], list[str]]:
    """The tier table as terminal lines and as Markdown for the GitHub step summary."""
    width = max((len(f"{tier.integration} / {tier.action}") for tier in tiers), default=0)
    text, markdown = [], ["| Adapter | Tier | Fingerprint | Uncovered |", "|---|---|---|---|"]
    for tier in tiers:
        name = f"{tier.integration} / {tier.action}"
        text.append(f"{name:{width}}  {tier.tier:12}  {tier.fingerprint}  {', '.join(tier.uncovered)}".rstrip())
        markdown.append(f"| {name} | {tier.tier} | `{tier.fingerprint}` | {', '.join(tier.uncovered)} |")
    return text, markdown


def main(argv: list[str] | None = None, registry: AdapterRegistry | None = None, bench_dir: Path = BENCH_DIR) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coverage", type=Path, help="coverage.json from pytest --cov-report=json")
    parser.add_argument("--require-beta", action="store_true", help="fail on any untested adapter")
    args = parser.parse_args(argv)

    registry = registry or AdapterRegistry.discover()
    tiers, errors = compute(registry, bench_dir)
    if args.coverage:
        errors += coverage_errors(registry, json.loads(args.coverage.read_text()))
    if args.require_beta:
        errors += [
            f"{tier.integration} / {tier.action} is untested; a release needs every adapter beta"
            for tier in tiers
            if tier.tier is Tier.UNTESTED
        ]

    text, markdown = report(tiers)
    print("\n".join(text))
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a") as handle:
            handle.write("## Adapter tiers\n\n" + "\n".join(markdown) + "\n")
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
