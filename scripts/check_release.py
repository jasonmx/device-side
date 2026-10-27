#!/usr/bin/env python3
"""Check the adapters against the release gates: the coverage bar, and no experimental adapter in a release.

`experimental=True` on an adapter's scope means it is not in a stable release yet. It is cleared by a PR citing a
passing bench record or tester issue that covers the scope.

Exits 1 on any adapter module under 95% line coverage (with --coverage), or any experimental adapter (with
--release).

Usage: scripts/check_release.py [--coverage coverage.json] [--release]
"""

import argparse
import inspect
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from custom_components.device_side.core.registry import AdapterRegistry  # noqa: E402

COVERAGE_BAR = 95.0


def adapters(registry: AdapterRegistry) -> list[tuple[str, object]]:
    """Every adapter, named `integration / action`."""
    return [
        (f"{integration} / {action}", adapter)
        for action, integration, adapter in registry.matrix()
        if adapter is not None
    ]


def coverage_errors(registry: AdapterRegistry, coverage: dict) -> list[str]:
    """An adapter module under the bar, or absent from the report, is an error."""
    percent = {}
    for name, entry in coverage["files"].items():
        summary = entry["summary"]
        statements = summary["num_statements"]
        percent[(REPO / name).resolve()] = 100.0 * summary["covered_lines"] / statements if statements else 100.0
    errors = []
    for name, adapter in adapters(registry):
        path = Path(inspect.getsourcefile(type(adapter))).resolve()
        covered = percent.get(path, 0.0)
        if covered < COVERAGE_BAR:
            errors.append(
                f"{name}: {covered:.1f}% line coverage of {path.relative_to(REPO)}, under {COVERAGE_BAR:.0f}%"
            )
    return errors


def main(argv: list[str] | None = None, registry: AdapterRegistry | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coverage", type=Path, help="coverage.json from pytest --cov-report=json")
    parser.add_argument("--release", action="store_true", help="fail on any experimental adapter")
    args = parser.parse_args(argv)

    registry = registry or AdapterRegistry.discover()
    found = adapters(registry)
    errors = coverage_errors(registry, json.loads(args.coverage.read_text())) if args.coverage else []
    if args.release:
        errors += [
            f"{name} is experimental; a release has none" for name, adapter in found if adapter.scope.experimental
        ]

    width = max((len(name) for name, _ in found), default=0)
    for name, adapter in found:
        print(f"{name:{width}}  {'experimental' if adapter.scope.experimental else ''}".rstrip())
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        rows = [f"| {name} | {'yes' if adapter.scope.experimental else ''} |" for name, adapter in found]
        with open(summary, "a") as handle:
            handle.write("## Adapters\n\n| Adapter | Experimental |\n|---|---|\n" + "\n".join(rows) + "\n")
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
