#!/usr/bin/env -S uv run python
"""Run the rig tests against the live HA, behind a human approval gate.

The rig is the household's own Home Assistant and its in-use lights. Nothing changes state before the gate:
preflight reads the inventory, the adapter registry and the deployed tree hash, prints what will run, then asks.
DEVICE_SIDE_RIG_APPROVED=1 answers the gate for a non-interactive caller that already has a human's yes.

One run at a time: a lock in the git common dir, shared by every worktree; a second run waits for it. The tests are the
step files in tests/rig/steps, run by tests/rig/engine.py; a full pass of an adapter rewrites its bench record.

Ctrl-C, SIGTERM and SIGHUP stop a run, putting the devices back; a second one leaves them. What a run changes is
journaled first (next to the lock), so whatever a killed run leaves changed, the next run puts back before its gate, or
--recover alone does.

Usage: scripts/rig.py [--dry-run] [--no-deploy] [--no-restart] [--unattended] [--integration KEY ...]
                      [--action NAME ...] [-k TEXT]
       scripts/rig.py --recover
"""

import argparse
import asyncio
import datetime
import fcntl
import getpass
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from custom_components.device_side.core.registry import AdapterRegistry  # noqa: E402
from tests.rig.bridge import HueBridge  # noqa: E402
from tests.rig.client import HAClient  # noqa: E402
from tests.rig.engine import (  # noqa: E402
    ADMIN_INTEGRATIONS,
    EntryOptions,
    Snapshot,
    StepFile,
    Suite,
    cases,
    load_step_files,
    run,
    write_records,
    write_report,
)
from tests.rig.inventory import INVENTORY, Inventory, load_env  # noqa: E402
from tests.rig.journal import Journal  # noqa: E402

COMPONENT = "custom_components/device_side"
BENCH_DIR = REPO / "docs" / "bench"
SERVICE = ("device_side", "turn_on_for")
READY_TIMEOUT_S = 180
RESTART_ESTIMATE_S = 90
LOCK_NAME = "device_side-rig.lock"
LOCK_POLL_S = 2.0  # how often a waiting run retries the lock
JOURNAL_NAME = "device_side-rig.journal.json"
ABORT_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
# Run reports go where the OS clears old files: they are for reviewing a run, not for keeping.
REPORT_DIR = Path(tempfile.gettempdir()) / "device_side-rig"


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


def select(
    step_files: list[StepFile], inventory: Inventory, integrations: list[str] | None, actions: list[str] | None = None
) -> list[Suite]:
    """Every step file on every inventory integration, narrowed to --integration and --action. An action takes every
    step file for it (move and move-predicted_state), whole, so each still writes its record."""
    return [
        Suite(step_file, integration)
        for step_file in step_files
        if not actions or step_file.action in actions
        for integration in inventory.integrations
        if not integrations or integration in integrations
    ]


def plan_lines(
    suites: list[Suite],
    inventory: Inventory,
    registry: AdapterRegistry,
    keyword: str | None = None,
) -> list[str]:
    """Per adapter about to run: the household entities it will move, then each test case."""
    lines = []
    for suite in suites:
        if registry.adapter(suite.action, suite.integration) is None:
            lines.append(f"{suite.integration} / {suite.action} (no adapter, will skip)")
            continue
        roles = suite.file.roles
        entities = [entity for role in roles if (entity := inventory.entity(suite.integration, role))]
        targets = ", ".join(dict.fromkeys(entities)) or "no entity, will skip"
        lines.append(f"{suite.integration} / {suite.name} -> {targets}")
        for case in cases(suite, inventory, keyword):
            lines.append(f"    {case.id}: {case.skip or ', '.join(dict.fromkeys(case.entities.values()))}")
    return lines


def estimate(suites: list[Suite], registry: AdapterRegistry, restarting: bool) -> int:
    seconds = sum(suite.file.rig_seconds for suite in suites if registry.adapter(suite.action, suite.integration))
    return seconds + (RESTART_ESTIMATE_S if restarting else 0)


def deployed_tree(status_cmd: str) -> str | None:
    """The tree hash the deploy sync command last installed, or None if unset or not yet deployed (exit 91)."""
    if not status_cmd:
        return None
    result = subprocess.run(status_cmd.split(), capture_output=True, text=True)
    if result.returncode == 91:
        return None
    if result.returncode != 0:
        raise SystemExit(f"{status_cmd} failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout.strip()


def deploy_state(status_cmd: str) -> Deploy:
    """Whether HA runs this checkout's integration, and if not, whether origin has it to deploy.

    The deploy sync command installs a branch tip from GitHub, never the working tree, so a
    deploy needs the change pushed.
    """
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    state = Deploy(
        local_tree=git("rev-parse", f"HEAD:{COMPONENT}"),
        deployed_tree=deployed_tree(status_cmd),
        branch=branch,
    )
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


def check_deploy(env: dict, no_restart: bool, deploy: Deploy) -> None:
    """Raise SystemExit if the deploy cannot proceed: missing commands or a git blocker."""
    if not env.get("RIG_SYNC_CMD"):
        raise SystemExit("RIG_SYNC_CMD must be set in .env.rig to deploy (see tests/rig/env.example)")
    if not no_restart and not env.get("RIG_RESTART_CMD"):
        raise SystemExit("RIG_RESTART_CMD must be set in .env.rig to restart (see tests/rig/env.example)")
    if deploy.blocker:
        raise SystemExit(f"Cannot deploy: {deploy.blocker}.")


def lock_entry(holder: str) -> str:
    """What a run writes into the lock: `holder` and its pid, then how to reach whoever started it.

    Under Claude Code that is the path of the session's registry file, which the reader resolves to the session's
    current name (sessions can be renamed mid-run). Run from a terminal, it is the user and tty instead.
    """
    claude_pid = os.environ.get("CLAUDE_PID")
    if claude_pid:
        config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser()
        return f"{holder} (pid {os.getpid()})\n{config / 'sessions' / f'{claude_pid}.json'}\n"
    who = f"user {getpass.getuser()}"
    try:
        who += f" on {os.ttyname(0).removeprefix('/dev/')}"
    except OSError:  # stdin is not a tty
        pass
    return f"{holder} (pid {os.getpid()}, {who})\n"


def lock_holder(entry: str) -> str:
    """Describe the lock's holder from its `lock_entry`, naming the Claude Code session that holds it, if any.

    The registry file is Claude Code's own, undocumented: when it is gone or unreadable, the holder line stands alone.
    """
    line, _, session_file = entry.strip().partition("\n")
    held_by = line or "an unnamed process"
    if not session_file:
        return held_by
    try:
        name = json.loads(Path(session_file).read_text())["name"]
    except (OSError, ValueError, KeyError, TypeError):
        return held_by
    return f'{held_by}, Claude Code session "{name}" (SendMessage reaches it)'


def lock_rig(path: Path, holder: str, out: Callable[[str], None] = print) -> TextIO:
    """Hold an exclusive lock on `path` for the process's life, waiting while another run has it.

    One lock in the git common dir covers every worktree. flock drops when the process dies, so nothing goes stale.
    A waiting run says who holds the lock (with its Claude Code session, so a waiting agent can message it), and again
    whenever that changes. Waiting runs poll rather than queue, so when several wait, whichever polls first after a
    release goes next.
    """
    handle = path.open("a+")
    waiting_on = None
    while True:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            handle.seek(0)
            held_by = lock_holder(handle.read())
            if held_by != waiting_on:
                out(f"Another rig run holds the lock: {held_by}. Waiting for it to finish (Ctrl-C to give up)...")
                waiting_on = held_by
            time.sleep(LOCK_POLL_S)
    if waiting_on is not None:
        out("Rig lock acquired.")
    handle.truncate(0)
    handle.write(lock_entry(holder))
    handle.flush()
    return handle


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
        except urllib.error.URLError, OSError, ValueError, TypeError, KeyError, AttributeError:
            pass
        sleep(3)
    if running:
        raise SystemExit(
            f"HA is running but has no {'.'.join(SERVICE)}. On a first load, add the integration "
            "(Settings > Devices & services > Add integration > Device Side), then rerun with --no-deploy."
        )
    raise SystemExit(f"HA did not report RUNNING within {timeout:.0f}s; check HA logs for errors.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print the plan and stop before the gate")
    parser.add_argument("--no-deploy", action="store_true", help="test whatever HA already runs")
    parser.add_argument("--no-restart", action="store_true", help="sync the integration but do not restart HA")
    parser.add_argument("--integration", action="append", help="limit to an integration key (repeatable)")
    parser.add_argument("--action", action="append", help="limit to an action's step files (repeatable)")
    parser.add_argument("-k", dest="keyword", help="run only test cases whose id contains this text")
    parser.add_argument("--unattended", action="store_true", help="skip observed tests, reporting them not observed")
    parser.add_argument("--recover", action="store_true", help="put back what an aborted run left changed, then stop")
    args = parser.parse_args(argv)

    _held, journal = hold_rig(args.dry_run)  # the lock is held until exit
    env = load_env()
    replay(env, journal, args.dry_run, args.recover)
    if args.recover:
        return 1 if journal else 0
    if not INVENTORY.exists():
        raise SystemExit(f"{INVENTORY} is absent; copy inventory.example.yaml and fill it in")
    inventory = Inventory.load()
    registry = AdapterRegistry.discover()
    suites = select(load_step_files(), inventory, args.integration, args.action)
    if not args.dry_run:
        check_tokens(env, suites, registry)
    if not any(registry.adapter(suite.action, suite.integration) for suite in suites):
        raise SystemExit("No rig test matches the inventory's integrations.")
    deploy = deploy_state(env.get("RIG_STATUS_CMD", ""))
    deploying = deploy.needed and not args.no_deploy
    restarting = deploying and not args.no_restart
    print_plan(inventory, suites, registry, args.keyword, deploy, deploying, restarting)

    if deploying:
        check_deploy(env, args.no_restart, deploy)
    if args.dry_run:
        return 0
    if not gate():
        print("Not approved; nothing changed.")
        return 1

    if deploying:
        command = ["sh", str(REPO / "scripts" / "deploy.sh"), deploy.branch]
        if args.no_restart:
            command.append("--no-restart")
        deploy_env = {
            **os.environ,
            "RIG_SYNC_CMD": env["RIG_SYNC_CMD"],
            "RIG_RESTART_CMD": env.get("RIG_RESTART_CMD", ""),
        }
        subprocess.run(command, check=True, env=deploy_env)
    wait_until_ready(env["HA_URL"].rstrip("/"), env["HA_TOKEN"], READY_TIMEOUT_S if restarting else 15)
    return run_tests(run_rig(env, suites, inventory, registry, args.keyword, args.unattended, journal))


def hold_rig(dry_run: bool) -> tuple[TextIO | None, Journal]:
    """The rig lock, unless it is a dry run, and the journal, read once the lock is held: whoever last held it has
    exited, so the journal is what it left."""
    common_dir = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir"))
    lock = None if dry_run else lock_rig(common_dir / LOCK_NAME, git("rev-parse", "--abbrev-ref", "HEAD"))
    return lock, Journal(common_dir / JOURNAL_NAME)


def run_tests(rig_run: Coroutine[Any, Any, int]) -> int:
    """Run run_rig, ending on one line rather than a traceback when a signal stops it (cancel_on_signals)."""
    try:
        return asyncio.run(rig_run)
    except asyncio.CancelledError:
        print("Aborted.")
    except KeyboardInterrupt:  # a second Ctrl-C, mid-cleanup
        print("Aborted before putting everything back; the next run puts back the rest.")
    return 1


def replay(env: dict, journal: Journal, dry_run: bool, asked: bool) -> None:
    """Put back what an aborted run left changed. A dry run holds no lock, so the run may still be going: it only says
    the journal is there."""
    if not journal:
        if asked:
            print("No aborted run left anything to put back.")
    elif dry_run:
        print(f"An aborted run left changes in {journal.path}; the next run puts them back before its gate.")
    else:
        asyncio.run(recover_rig(env, journal))


def check_tokens(env: dict, suites: list[Suite], registry: AdapterRegistry) -> None:
    """Stop before the gate when .env.rig lacks a token the run needs: ADMIN_INTEGRATIONS and any adapter with
    options (they are set through device_side's options flow) need HA_ADMIN_TOKEN; a Hue file with a bridge step
    needs the bridge's host and key."""
    if not (env.get("HA_URL") and env.get("HA_TOKEN")):
        raise SystemExit("HA_URL and HA_TOKEN must be set in .env.rig (see tests/rig/env.example)")
    if any(suite.integration == "hue" and suite.file.uses_bridge for suite in suites) and not (
        env.get("HUE_BRIDGE_HOST") and env.get("HUE_APP_KEY")
    ):
        raise SystemExit("HUE_BRIDGE_HOST and HUE_APP_KEY must be set in .env.rig for the bridge step")
    if env.get("HA_ADMIN_TOKEN"):
        return
    with_options = {
        suite.integration
        for suite in suites
        if (adapter := registry.adapter(suite.action, suite.integration)) is not None and adapter.scope.options
    }
    if admin_only := sorted(({suite.integration for suite in suites} & ADMIN_INTEGRATIONS) | with_options):
        raise SystemExit(
            f"{', '.join(admin_only)} needs HA_ADMIN_TOKEN in .env.rig (an admin user's token), "
            "or leave it out with --integration"
        )


def print_plan(
    inventory: Inventory,
    suites: list[Suite],
    registry: AdapterRegistry,
    keyword: str | None,
    deploy: Deploy,
    deploying: bool,
    restarting: bool,
) -> None:
    print(f"Inventory ({INVENTORY}):")
    for integration, entities in inventory.integrations.items():
        for entity in entities:
            print(f"  {integration:8} {entity.entity_id:40} {', '.join(sorted(entity.roles))}")
    print("Adapters:")
    for line in plan_lines(suites, inventory, registry, keyword):
        print(f"  {line}")
    print(f"Integration: local {deploy.local_tree[:12]}, deployed {(deploy.deployed_tree or 'none')[:12]}")
    if deploying:
        print(f"Deploy: sync {deploy.branch}" + (", then restart Home Assistant" if restarting else ", no restart"))
    elif deploy.needed:
        print("Deploy: skipped (--no-deploy); the tests exercise the deployed tree, not this checkout")
    else:
        print("Deploy: not needed, no restart")
    seconds = estimate(suites, registry, restarting)
    print(f"Estimated duration: {seconds} s. These are in-use household devices; they will visibly change state.")


async def run_rig(
    env: dict,
    suites: list[Suite],
    inventory: Inventory,
    registry: AdapterRegistry,
    keyword: str | None,
    unattended: bool,
    journal: Journal | None = None,
) -> int:
    """Run the step files, then write a bench record for each adapter whose every test passed."""
    cancel_on_signals()
    ha, admin = await connect(env)
    bridge = None
    if env.get("HUE_BRIDGE_HOST") and env.get("HUE_APP_KEY"):
        bridge = HueBridge(env["HUE_BRIDGE_HOST"], env["HUE_APP_KEY"])
    paused: list[str] = []
    try:
        await pause(ha, pause_list(env), paused, journal)
        result = await run(
            suites,
            inventory,
            registry,
            ha,
            admin=admin,
            keyword=keyword,
            ask=None if unattended else input,
            bridge=bridge,
            journal=journal,
        )
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\nReport: {write_report(result, REPORT_DIR, f'rig run {stamp}')}")
        source = f"rig run (`scripts/rig.py`), commit `{git('rev-parse', '--short', 'HEAD')}`"
        today = datetime.date.today().isoformat()
        for path in await write_records(result, ha, registry, BENCH_DIR, today, source):
            print(f"Wrote {path.relative_to(REPO)}; review the diff before committing it.")
    finally:
        await resume(ha, paused, journal)
        if bridge:
            await bridge.close()
        await ha.close()
        if admin:
            await admin.close()
    return 1 if result.failed else 0


def cancel_on_signals() -> None:
    """Have Ctrl-C, SIGTERM and SIGHUP cancel the running task, so its finally blocks put the devices back. The first
    one restores the default handlers: a second kills the process (Ctrl-C: interrupts it), leaving the journal."""
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()

    def abort() -> None:
        for signum in ABORT_SIGNALS:
            loop.remove_signal_handler(signum)
        print("\nAborting: putting devices back.")
        task.cancel()

    for signum in ABORT_SIGNALS:
        loop.add_signal_handler(signum, abort)


async def connect(env: dict) -> tuple[HAClient, HAClient | None]:
    """The HA connection, and the admin one when .env.rig has HA_ADMIN_TOKEN."""
    ha = HAClient(env["HA_URL"], env["HA_TOKEN"])
    admin = HAClient(env["HA_URL"], env["HA_ADMIN_TOKEN"]) if env.get("HA_ADMIN_TOKEN") else None
    await ha.connect()
    if admin:
        await admin.connect()
    return ha, admin


async def recover_rig(env: dict, journal: Journal) -> None:
    if not (env.get("HA_URL") and env.get("HA_TOKEN")):
        raise SystemExit("HA_URL and HA_TOKEN must be set in .env.rig to put back what an aborted run left changed")
    ha, admin = await connect(env)
    try:
        await recover(ha, admin, journal)
    finally:
        await ha.close()
        if admin:
            await admin.close()


async def recover(ha: HAClient, admin: HAClient | None, journal: Journal, out: Callable[[str], None] = print) -> None:
    """Put back what an aborted run left changed, in the order its finally blocks would have: the case's entities,
    device_side's options, the paused automations. A step that fails is printed and dropped from the journal;
    options stay in it while there is no admin connection to set them."""
    out(f"An aborted rig run left changes in {journal.path}; putting them back.")
    if taken := journal.get("taken"):
        for entity_id, state in taken.items():
            if state is not None and state["state"] in ("on", "off"):
                out(f"Putting {entity_id} back {state['state']}.")
        power, stored = journal.get("power", {}), journal.get("stored", {})
        await Snapshot(ha, power, taken=taken, stored=stored, journal=journal).restore()
    if (options := journal.get("options")) is not None:
        if admin is None:
            out("Putting device_side's options back needs HA_ADMIN_TOKEN in .env.rig; they stay in the journal.")
        else:
            try:
                await EntryOptions(admin).apply(options)
                out("Put device_side's options back.")
            except Exception as err:  # noqa: BLE001 - as resume: say so, and go on to the automations
                out(f"Could not put device_side's options back; set them in HA: {err}")
            journal.clear("options")
    if paused := journal.get("paused"):
        await resume(ha, paused, journal)


PAUSABLE = ("automation", "switch")


def pause_list(env: dict) -> list[str]:
    """RIG_PAUSE: comma-separated automations and switches that must be off while the rig runs."""
    entity_ids = [entity_id.strip() for entity_id in env.get("RIG_PAUSE", "").split(",") if entity_id.strip()]
    if other := [entity_id for entity_id in entity_ids if entity_id.partition(".")[0] not in PAUSABLE]:
        raise SystemExit(f"RIG_PAUSE takes automations and switches only, got {', '.join(other)}")
    return entity_ids


async def pause(ha: HAClient, entity_ids: list[str], paused: list[str], journal: Journal | None = None) -> None:
    """Turn off each listed automation or switch that is on, appending it to `paused` (and the journal, first) as it
    goes.

    For automations that would fight the tests: motion lighting turning a light on as someone walks past, or an
    Adaptive Lighting instance resetting a light's color temperature whenever it turns on. One that is already off
    stays off and is left alone after the run. One HA doesn't know stops the run before any test.
    """
    for entity_id in entity_ids:
        if (state := await ha.get_state(entity_id)) is None:
            raise SystemExit(f"{entity_id} in RIG_PAUSE has no state in Home Assistant")
        if state["state"] == "on":
            if journal is not None:
                journal.update(paused=[*paused, entity_id])
            await ha.call_service(entity_id.partition(".")[0], "turn_off", {"entity_id": entity_id})
            paused.append(entity_id)
            print(f"Paused {entity_id} for the run.")


async def resume(ha: HAClient, paused: list[str], journal: Journal | None = None) -> None:
    """Turn back on what pause turned off; a failure is printed, so it can be turned on by hand."""
    for entity_id in paused:
        try:
            await ha.call_service(entity_id.partition(".")[0], "turn_on", {"entity_id": entity_id})
            print(f"Resumed {entity_id}.")
        except Exception as err:  # noqa: BLE001 - try every one, and say which stayed off
            print(f"Could not turn {entity_id} back on: {err}. Turn it on by hand.")
    if journal is not None:
        journal.clear("paused")


if __name__ == "__main__":
    # Line by line even when stdout is a file, so a background caller sees "waiting for the lock" and each result
    # as they happen rather than when the buffer fills.
    sys.stdout.reconfigure(line_buffering=True)
    sys.exit(main())
