#!/usr/bin/env python3
"""Run the rig tests against the live HA, behind a human approval gate.

The rig is the household's own Home Assistant and its in-use lights. Nothing changes state before the gate:
preflight reads the inventory, the adapter registry and the deployed tree hash, prints what will run, then asks.
DEVICE_SIDE_RIG_APPROVED=1 answers the gate for a non-interactive caller that already has a human's yes.

Usage: scripts/rig.py [--dry-run] [--no-deploy] [--no-restart] [--platform KEY ...] [-k EXPR]
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from custom_components.device_side.core.registry import AdapterRegistry  # noqa: E402
from tests.rig.inventory import INVENTORY, Inventory, RigModule, load_env, rig_modules  # noqa: E402

COMPONENT = "custom_components/device_side"
SERVICE = ("device_side", "turn_on_for")
READY_TIMEOUT_S = 180
RESTART_ESTIMATE_S = 90


@dataclass(slots=True)
class Deploy:
    local_tree: str
    deployed_tree: str | None
    branch: str
    blocker: str | None = None

    @property
    def needed(self) -> bool:
        return self.local_tree != self.deployed_tree


def git(*args: str, check: bool = True) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], check=check, capture_output=True, text=True).stdout.strip()


def select(modules: list[RigModule], inventory: Inventory, platforms: list[str] | None) -> list[RigModule]:
    return [
        module
        for module in modules
        if module.platform in inventory.platforms and (not platforms or module.platform in platforms)
    ]


def plan_lines(modules: list[RigModule], inventory: Inventory, registry: AdapterRegistry) -> list[str]:
    """One line per adapter about to run: which household entities it will move, and the adapter's declared tier."""
    lines = []
    for module in modules:
        adapter = registry.adapter(module.feature, module.platform)
        if adapter is None:
            tier = "no adapter, will skip"
        else:
            # A hand-written bench record counts as beta; slice 9 checks it against the adapter's fingerprint.
            bench = REPO / "docs" / "bench" / module.platform / f"{module.feature}.md"
            if adapter.capabilities.experimental:
                tier = "experimental"
            else:
                tier = "beta" if bench.exists() else "untested"
        entities = [entity for role in module.roles if (entity := inventory.entity(module.platform, role))]
        targets = ", ".join(entities) or "no entity, will skip"
        lines.append(f"{module.platform} / {module.feature} -> {targets} ({tier})")
    return lines


def deployed_tree(ssh: str) -> str | None:
    """The tree hash ha-shim's ds-sync last installed, or None if it never has (exit 91)."""
    result = subprocess.run(["ssh", ssh, "ds-status"], capture_output=True, text=True)
    if result.returncode == 91:
        return None
    if result.returncode != 0:
        raise SystemExit(f"ssh {ssh} ds-status failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout.strip()


def deploy_state(ssh: str) -> Deploy:
    """Whether HA runs this checkout's integration, and if not, whether origin has it to deploy.

    ds-sync installs a branch tip from GitHub, never the working tree, so a deploy needs the change pushed.
    """
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    state = Deploy(local_tree=git("rev-parse", f"HEAD:{COMPONENT}"), deployed_tree=deployed_tree(ssh), branch=branch)
    if git("status", "--porcelain", "--", COMPONENT):
        state.blocker = f"uncommitted changes under {COMPONENT}; commit and push them first"
        return state
    if not state.needed:
        return state
    remote = git("ls-remote", "origin", f"refs/heads/{branch}").split()
    if not remote:
        state.blocker = f"{branch} is not on origin; push it first"
    elif git("rev-parse", "--quiet", "--verify", f"{remote[0]}:{COMPONENT}", check=False) != state.local_tree:
        state.blocker = f"origin/{branch} does not match HEAD under {COMPONENT}; push first"
    return state


def gate(prompt: Callable[[str], str] = input) -> bool:
    if os.environ.get("DEVICE_SIDE_RIG_APPROVED") == "1":
        print("Approved by DEVICE_SIDE_RIG_APPROVED=1.")
        return True
    try:
        return prompt("Proceed? [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _get(url: str, token: str) -> Any:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def wait_until_ready(
    url: str, token: str, timeout: float = READY_TIMEOUT_S, sleep: Callable[[float], None] = time.sleep
) -> None:
    """Until HA reports RUNNING and lists device_side.turn_on_for; exits the runner on timeout."""
    deadline = time.monotonic() + timeout
    running = False
    while time.monotonic() < deadline:
        running = False  # only the last poll counts: HA that was RUNNING may have crashed since
        try:
            running = _get(f"{url}/api/config", token).get("state") == "RUNNING"
            if running:
                services = {entry["domain"]: entry["services"] for entry in _get(f"{url}/api/services", token)}
                if SERVICE[1] in services.get(SERVICE[0], {}):
                    return
        except (urllib.error.URLError, OSError, ValueError, TypeError, KeyError, AttributeError):
            pass
        sleep(3)
    if running:
        raise SystemExit(
            f"HA is running but has no {'.'.join(SERVICE)}. On a first load, add the integration "
            "(Settings > Devices & services > Add integration > Device Side), then rerun with --no-deploy."
        )
    raise SystemExit(f"HA did not report RUNNING within {timeout:.0f}s; check `ssh ha err`.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print the plan and stop before the gate")
    parser.add_argument("--no-deploy", action="store_true", help="test whatever HA already runs")
    parser.add_argument("--no-restart", action="store_true", help="sync the integration but do not restart HA")
    parser.add_argument("--platform", action="append", help="limit to a platform key (repeatable)")
    parser.add_argument("-k", dest="keyword", help="passed to pytest -k")
    args = parser.parse_args(argv)

    env = load_env()
    if not args.dry_run and not (env.get("HA_URL") and env.get("HA_TOKEN")):
        raise SystemExit("HA_URL and HA_TOKEN must be set in .env.rig (see tests/rig/env.example)")
    if not INVENTORY.exists():
        raise SystemExit(f"{INVENTORY.relative_to(REPO)} is absent; copy inventory.example.yaml and fill it in")
    inventory = Inventory.load()
    modules = select(rig_modules(), inventory, args.platform)
    if not modules:
        raise SystemExit("No rig test matches the inventory's platforms.")
    deploy = deploy_state(env["RIG_SSH"])
    deploying = deploy.needed and not args.no_deploy
    restarting = deploying and not args.no_restart
    print_plan(inventory, modules, deploy, deploying, restarting)

    if deploying and deploy.blocker:
        raise SystemExit(f"Cannot deploy: {deploy.blocker}.")
    if args.dry_run:
        return 0
    if not gate():
        print("Not approved; nothing changed.")
        return 1

    if deploying:
        command = ["sh", str(REPO / "scripts" / "deploy.sh"), deploy.branch]
        if args.no_restart:
            command.append("--no-restart")
        subprocess.run(command, check=True, env={**os.environ, "RIG_SSH": env["RIG_SSH"]})
    wait_until_ready(env["HA_URL"].rstrip("/"), env["HA_TOKEN"], READY_TIMEOUT_S if restarting else 15)
    return run_pytest(modules, args.keyword)


def print_plan(
    inventory: Inventory, modules: list[RigModule], deploy: Deploy, deploying: bool, restarting: bool
) -> None:
    print(f"Inventory ({INVENTORY.relative_to(REPO)}):")
    for platform, entities in inventory.platforms.items():
        for entity in entities:
            print(f"  {platform:8} {entity.entity_id:40} {', '.join(sorted(entity.roles))}")
    print("Adapters:")
    for line in plan_lines(modules, inventory, AdapterRegistry.discover()):
        print(f"  {line}")
    print(f"Integration: local {deploy.local_tree[:12]}, deployed {(deploy.deployed_tree or 'none')[:12]}")
    if deploying:
        print(f"Deploy: ds-sync {deploy.branch}" + (", then restart Home Assistant" if restarting else ", no restart"))
    elif deploy.needed:
        print("Deploy: skipped (--no-deploy); the tests exercise the deployed tree, not this checkout")
    else:
        print("Deploy: not needed, no restart")
    estimate = sum(module.seconds for module in modules) + (RESTART_ESTIMATE_S if restarting else 0)
    print(f"Estimated duration: {estimate} s. These are in-use household devices; they will visibly change state.")


def run_pytest(modules: list[RigModule], keyword: str | None) -> int:
    args = [sys.executable, "-m", "pytest", *(str(module.path) for module in modules)]
    # The HA test plugin blocks sockets and fakes hass; the unit conftest above tests/rig needs that plugin.
    args += ["--confcutdir", str(REPO / "tests" / "rig"), "-p", "no:homeassistant", "-p", "no:cacheprovider"]
    args += ["-v", "-rs", *(["-k", keyword] if keyword else [])]
    rig_env = {**os.environ, "DEVICE_SIDE_RIG": "1", "DEVICE_SIDE_RIG_APPROVED": "1"}
    return subprocess.run(args, cwd=REPO, env=rig_env).returncode


if __name__ == "__main__":
    sys.exit(main())
