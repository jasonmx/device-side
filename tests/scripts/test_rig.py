"""scripts/rig.py's preflight and gate. Nothing here touches the rig: no ssh, no HA."""

import asyncio
import importlib.util
import itertools
import os
import signal
import types
from pathlib import Path

import pytest

from custom_components.device_side.core.registry import AdapterRegistry
from tests.rig import engine
from tests.rig.engine import load_step_file, load_step_files
from tests.rig.inventory import Inventory, load_env, main_checkout
from tests.rig.journal import Journal
from tests.scripts import rig_fakes as fakes

REPO = Path(__file__).parents[2]
_spec = importlib.util.spec_from_file_location("rig", REPO / "scripts" / "rig.py")
rig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rig)
real_workspace_color = rig.workspace_color  # the autouse fixture swaps the module's for a recorder


@pytest.fixture(autouse=True)
def workspace_colors(monkeypatch) -> list[str | None]:
    """Record the cmux workspace colors a run sets, so no test reaches the real cmux."""
    colors: list[str | None] = []
    monkeypatch.setattr(rig, "workspace_color", colors.append)
    return colors


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


@pytest.fixture
def inventory(tmp_path) -> Inventory:
    return Inventory.load(
        write(
            tmp_path,
            "inventory.yaml",
            "shelly:\n  - entity_id: switch.plug\n    roles: [switch_plug]\nhue:\n  - entity_id: light.lamp\n"
            "    roles: [light_color]\n",
        )
    )


def test_inventory_rejects_unknown_role(tmp_path):
    path = write(tmp_path, "inventory.yaml", "shelly:\n  - entity_id: switch.plug\n    roles: [plug]\n")
    with pytest.raises(ValueError, match="unknown roles"):
        Inventory.load(path)


def test_inventory_rejects_unknown_integration(tmp_path):
    path = write(tmp_path, "inventory.yaml", "z2m:\n  - entity_id: switch.plug\n    roles: [switch_plug]\n")
    with pytest.raises(ValueError, match="unknown integration 'z2m'"):
        Inventory.load(path)


def test_inventory_maps_each_powered_entity_to_its_supply(tmp_path):
    path = write(
        tmp_path,
        "inventory.yaml",
        "zha:\n  - entity_id: light.bulb\n    roles: [light_ct]\n    powered_by: switch.plug\n"
        "  - entity_id: switch.plug\n    roles: [switch_plug]\n",
    )
    assert Inventory.load(path).power() == {"light.bulb": "switch.plug"}


def test_inventory_rejects_an_unlisted_supply(tmp_path):
    path = write(
        tmp_path, "inventory.yaml", "zha:\n  - entity_id: light.bulb\n    roles: [light_ct]\n    powered_by: switch.x\n"
    )
    with pytest.raises(ValueError, match="powered_by switch.x, which the inventory doesn't list"):
        Inventory.load(path)


def test_inventory_reads_a_groups_members(tmp_path):
    path = write(
        tmp_path,
        "inventory.yaml",
        "zigbee2mqtt:\n  - entity_id: light.g\n    roles: [group]\n    members: [light.a, light.b]\n",
    )
    inventory = Inventory.load(path)
    assert inventory.members("zigbee2mqtt", "light.g") == ("light.a", "light.b")
    assert inventory.members("zigbee2mqtt", "light.other") == ()


def test_inventory_rejects_members_without_the_group_role(tmp_path):
    path = write(
        tmp_path, "inventory.yaml", "zha:\n  - entity_id: light.a\n    roles: [light_ct]\n    members: [light.b]\n"
    )
    with pytest.raises(ValueError, match="lists members but has no group role"):
        Inventory.load(path)


def test_inventory_rejects_members_given_as_one_string(tmp_path):
    path = write(tmp_path, "inventory.yaml", "zha:\n  - entity_id: light.g\n    roles: [group]\n    members: light.a\n")
    with pytest.raises(ValueError, match="members must be a list of entity IDs"):
        Inventory.load(path)


def test_inventory_entity_by_role(inventory):
    assert inventory.entity("shelly", "switch_plug") == "switch.plug"
    assert inventory.entity("shelly", "light_dimmable") is None
    assert inventory.entity("zha", "switch_plug") is None


def test_load_env_reads_file_and_env_overrides(tmp_path, monkeypatch):
    monkeypatch.delenv("HA_URL", raising=False)
    monkeypatch.delenv("RIG_SYNC_CMD", raising=False)
    monkeypatch.delenv("RIG_STATUS_CMD", raising=False)
    monkeypatch.delenv("RIG_RESTART_CMD", raising=False)
    monkeypatch.setenv("HA_TOKEN", "from-env")
    env = load_env(write(tmp_path, ".env.rig", "# comment\nHA_URL='http://ha:8123'\nHA_TOKEN=from-file\n"))
    assert env == {"HA_URL": "http://ha:8123", "HA_TOKEN": "from-env"}


def test_load_env_reads_command_vars(tmp_path, monkeypatch):
    for key in ("HA_URL", "HA_TOKEN", "RIG_SYNC_CMD", "RIG_STATUS_CMD", "RIG_RESTART_CMD"):
        monkeypatch.delenv(key, raising=False)
    env = load_env(
        write(
            tmp_path,
            ".env.rig",
            "HA_URL=http://ha:8123\nHA_TOKEN=tok\nRIG_SYNC_CMD=ssh myhost sync\nRIG_STATUS_CMD=ssh myhost status\n",
        )
    )
    assert env["RIG_SYNC_CMD"] == "ssh myhost sync"
    assert env["RIG_STATUS_CMD"] == "ssh myhost status"
    assert "RIG_RESTART_CMD" not in env


def test_select_plan_lines_and_estimate(inventory):
    step_files = [step_file for step_file in load_step_files() if step_file.action in ("turn_off_for", "turn_on_for")]
    suites = rig.select(step_files, inventory, None)
    assert [(suite.integration, suite.action) for suite in suites] == [
        ("shelly", "turn_off_for"),
        ("hue", "turn_off_for"),
        ("shelly", "turn_on_for"),
        ("hue", "turn_on_for"),
    ]
    assert [suite.integration for suite in rig.select(step_files, inventory, ["hue"])] == ["hue", "hue"]
    narrowed = rig.select(step_files, inventory, ["hue"], ["turn_on_for"])
    assert [(suite.integration, suite.action) for suite in narrowed] == [("hue", "turn_on_for")]

    registry = AdapterRegistry.discover()
    shelly_on = [suite for suite in suites if suite.integration == "shelly" and suite.action == "turn_on_for"]
    assert rig.plan_lines(shelly_on + suites[1:2], inventory, registry) == [
        "shelly / turn_on_for -> switch.plug",
        "    on_then_off[switch_plug]: switch.plug",
        "    on_then_off[light_onoff]: no light_onoff entity in inventory",
        "    on_then_off[light_wrapped]: no light_wrapped entity in inventory",
        "    drops_brightness_on_a_wrapper[light_wrapped]: no light_wrapped entity in inventory",
        "    drops_brightness_on_a_relay_light[light_onoff]: no light_onoff entity in inventory",
        "    bulb_on_then_off[light_dimmable]: no light_dimmable entity in inventory",
        "    bulb_brightness_then_off[light_dimmable]: no light_dimmable entity in inventory",
        "    bulb_color_temp_then_off[light_ct]: no light_ct entity in inventory",
        "    bulb_transition_then_off[light_dimmable]: no light_dimmable entity in inventory",
        "    rgbcct_bulb_rgb_then_off[light_color]: no light_color entity in inventory",
        "    rgbcct_bulb_rgb_then_off[light_color] observed: no light_color entity in inventory",
        "hue / turn_off_for (no adapter, will skip)",
    ]
    assert rig.plan_lines(shelly_on, inventory, registry, "on_then") == [
        "shelly / turn_on_for -> switch.plug",
        "    on_then_off[switch_plug]: switch.plug",
        "    on_then_off[light_onoff]: no light_onoff entity in inventory",
        "    on_then_off[light_wrapped]: no light_wrapped entity in inventory",
        "    bulb_on_then_off[light_dimmable]: no light_dimmable entity in inventory",
        "    bulb_transition_then_off[light_dimmable]: no light_dimmable entity in inventory",
    ]

    shelly_seconds = sum(step_file.rig_seconds for step_file in step_files)
    assert rig.estimate(suites, registry, restarting=False) == shelly_seconds
    assert rig.estimate(suites, registry, restarting=True) == shelly_seconds + rig.RESTART_ESTIMATE_S


@pytest.mark.parametrize(("answer", "approved"), [("y", True), ("YES", True), ("", False), ("n", False)])
def test_gate_needs_an_explicit_yes(monkeypatch, answer, approved):
    monkeypatch.delenv("DEVICE_SIDE_RIG_APPROVED", raising=False)
    assert rig.gate(lambda _: answer) is approved


def test_gate_refuses_without_a_terminal(monkeypatch):
    monkeypatch.delenv("DEVICE_SIDE_RIG_APPROVED", raising=False)

    def no_tty(_):
        raise EOFError

    assert rig.gate(no_tty) is False


def test_gate_env_approval_skips_the_prompt(monkeypatch):
    monkeypatch.setenv("DEVICE_SIDE_RIG_APPROVED", "1")
    assert rig.gate(lambda _: pytest.fail("prompted")) is True


def fake_ha(monkeypatch, replies):
    """Each _get call pops the next reply; an exception instance is raised instead of returned."""

    def _get(url, token):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(rig, "_get", _get)


def fake_clock(monkeypatch):
    """rig's own clock ticks 10 s per read; patching time.monotonic itself would break the event loop."""
    ticks = itertools.count(0, 10)
    monkeypatch.setattr(rig, "time", types.SimpleNamespace(monotonic=lambda: next(ticks)))


def test_wait_until_ready_returns_once_the_service_is_listed(monkeypatch):
    services = [{"domain": "device_side", "services": {"turn_on_for": {}}}]
    running = {"state": "RUNNING"}
    fake_ha(monkeypatch, [rig.urllib.error.URLError("down"), running, None, running, services])
    rig.wait_until_ready("http://ha", "token", timeout=60, sleep=lambda _: None)


def test_wait_until_ready_reports_a_crash_after_running_as_not_running(monkeypatch):
    fake_clock(monkeypatch)
    fake_ha(monkeypatch, [{"state": "RUNNING"}, [], *[OSError("refused")] * 5])
    with pytest.raises(SystemExit, match="did not report RUNNING"):
        rig.wait_until_ready("http://ha", "token", timeout=35, sleep=lambda _: None)


def test_wait_until_ready_says_why_the_service_is_missing(monkeypatch):
    fake_clock(monkeypatch)
    fake_ha(monkeypatch, [{"state": "RUNNING"}, []] * 5)

    async def config_entries(url, token):
        assert token == "admin"
        return [{"domain": "device_side", "state": "not_loaded"}, {"domain": "mqtt", "state": "setup_in_progress"}]

    monkeypatch.setattr(rig, "config_entries", config_entries)
    with pytest.raises(SystemExit, match="entry is not_loaded; it waits for mqtt"):
        rig.wait_until_ready("http://ha", "token", "admin", timeout=35, sleep=lambda _: None)


def test_wait_until_ready_says_why_ha_is_still_starting(monkeypatch):
    fake_clock(monkeypatch)
    fake_ha(monkeypatch, [{"state": "NOT_RUNNING"}] * 5)
    monkeypatch.setattr(rig, "diagnose", lambda url, admin_token: "zha (setup_in_progress).")
    with pytest.raises(SystemExit, match=r"still starting after 35s \(NOT_RUNNING\)\. zha \(setup_in_progress\)"):
        rig.wait_until_ready("http://ha", "token", "admin", timeout=35, sleep=lambda _: None)


WAITS_FOR = ["hue", "zha"]


@pytest.mark.parametrize(
    ("entries", "says"),
    [
        ([], "On a first load, add the integration"),
        (
            [
                {"domain": "device_side", "state": "not_loaded"},
                {"domain": "hue", "state": "loaded"},
                {"domain": "zha", "state": "setup_in_progress"},
                {"domain": "zha", "state": "not_loaded", "disabled_by": "user"},
                {"domain": "met", "state": "setup_error"},
            ],
            "device_side's entry is not_loaded; it waits for zha (setup_in_progress). "
            "device_side actions are unavailable in the house until this is fixed.",
        ),
        (
            [{"domain": "device_side", "state": "setup_error"}, {"domain": "hue", "state": "loaded"}],
            "device_side's entry is setup_error; none of the integrations it waits for (hue, zha) is stuck; "
            "check HA's logs.",
        ),
    ],
)
def test_explain_a_missing_service(entries, says):
    assert says in rig.explain(entries, WAITS_FOR)


def test_diagnose_without_an_admin_token_says_what_it_could_not_check():
    assert "Without HA_ADMIN_TOKEN" in rig.diagnose("http://ha", None)


def test_diagnose_says_when_it_cannot_read_the_entries(monkeypatch):
    async def config_entries(url, token):
        raise OSError("refused")

    monkeypatch.setattr(rig, "config_entries", config_entries)
    assert rig.diagnose("http://ha", "admin").startswith("Could not read config entries")


@pytest.mark.parametrize(
    ("output", "code", "trees"),
    [
        ("synced aaa\nloaded bbb\n", 0, ("aaa", "bbb")),
        ("synced aaa\n", 0, ("aaa", None)),
        ("aaa\n", 0, ("aaa", "aaa")),
        ("", 91, (None, None)),
    ],
)
def test_deployed_trees_reads_both_formats(tmp_path, output, code, trees):
    script = write(tmp_path, "status.sh", f"printf '{output}'\nexit {code}\n")
    assert rig.deployed_trees(f"sh {script}") == trees


def test_deployed_trees_stops_on_a_failing_status_command(tmp_path):
    script = write(tmp_path, "status.sh", "echo boom >&2\nexit 2\n")
    with pytest.raises(SystemExit, match="failed \\(2\\): boom"):
        rig.deployed_trees(f"sh {script}")


def fake_git(monkeypatch, *, dirty="", remote="abc refs/heads/b", remote_tree="tree1", deployed=("old", "old")):
    replies = {
        "rev-parse --abbrev-ref HEAD": "b",
        "rev-parse HEAD": "c1",
        f"rev-parse c1:{rig.COMPONENT}": "tree1",
        f"status --porcelain -- {rig.COMPONENT}": dirty,
        "ls-remote origin refs/heads/b": remote,
        f"rev-parse --quiet --verify abc:{rig.COMPONENT}": remote_tree,
    }
    monkeypatch.setattr(rig, "git", lambda *args, check=True: replies[" ".join(args)])
    monkeypatch.setattr(rig, "deployed_trees", lambda status_cmd: deployed)


@pytest.mark.parametrize(
    ("kwargs", "needed", "blocker"),
    [
        ({}, True, None),
        ({"deployed": ("tree1", "tree1")}, False, None),
        ({"deployed": ("tree1", "old")}, True, None),  # synced but never loaded: a failed restart
        ({"deployed": (None, None)}, True, None),
        ({"dirty": " M x.py"}, True, "uncommitted changes"),
        ({"remote": ""}, True, "not on origin"),
        ({"remote_tree": "tree0"}, True, "does not match HEAD"),
    ],
)
def test_deploy_state(monkeypatch, kwargs, needed, blocker):
    fake_git(monkeypatch, **kwargs)
    state = rig.deploy_state("ssh myhost status")
    assert (state.commit, state.local_tree) == ("c1", "tree1")
    assert state.needed is needed
    assert (state.blocker is None) if blocker is None else (blocker in state.blocker)


@pytest.mark.parametrize(
    ("deployed", "deploying", "loaded_after", "commit"),
    [
        (("tree1", "tree1"), False, None, "c1"),  # HA already runs this checkout
        (("old", "old"), False, None, None),  # --no-deploy: HA runs another tree
        (("old", "old"), True, "tree1", "c1"),
        (("old", "old"), True, "tree2", None),  # origin moved between the plan and the deploy
        (("old", "old"), True, None, "c1"),  # the status command can't say what HA loaded
    ],
)
def test_tested_commit_names_the_tree_ha_loaded(monkeypatch, deployed, deploying, loaded_after, commit):
    fake_git(monkeypatch, deployed=deployed)
    deploy = rig.deploy_state("ssh myhost status")
    monkeypatch.setattr(rig, "deployed_trees", lambda status_cmd: (loaded_after, loaded_after))
    assert rig.tested_commit("ssh myhost status", deploy, deploying) == commit


def test_tested_commit_trusts_a_deploy_without_a_status_command(monkeypatch):
    fake_git(monkeypatch, deployed=(None, None))
    assert rig.tested_commit("", rig.deploy_state(""), deploying=True) == "c1"


def run_git(*args: str) -> None:
    rig.subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
    )


def test_main_checkout_from_a_linked_worktree(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    main, linked = tmp_path / "main", tmp_path / "linked"
    run_git("init", "-q", str(main))
    run_git("-C", str(main), "commit", "-q", "--allow-empty", "-m", "root")
    run_git("-C", str(main), "worktree", "add", "-q", str(linked))
    assert main_checkout(linked).resolve() == main.resolve()
    assert main_checkout(main).resolve() == main.resolve()


def test_main_checkout_falls_back_outside_a_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    assert main_checkout(tmp_path) == tmp_path
    monkeypatch.setenv("PATH", "")
    assert main_checkout(tmp_path) == tmp_path


def claude_session(tmp_path, monkeypatch, name):
    """Run as if under a Claude Code session called `name`, with its registry file under a fake config dir."""
    (tmp_path / "sessions").mkdir()
    (tmp_path / "sessions" / "4242.json").write_text(f'{{"pid": 4242, "name": "{name}"}}')
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("CLAUDE_PID", "4242")
    return tmp_path / "sessions" / "4242.json"


def test_a_held_rig_lock_makes_a_second_run_wait_naming_the_holder(tmp_path, monkeypatch):
    claude_session(tmp_path, monkeypatch, "rig-agent-1a")
    path = tmp_path / rig.LOCK_NAME
    held = rig.lock_rig(path, "wt/first")
    printed: list[str] = []
    polls: list[float] = []

    def release_on_second_poll(seconds):
        if len(polls) == 1:
            held.close()
        polls.append(seconds)

    monkeypatch.setattr(rig.time, "sleep", release_on_second_poll)
    rig.lock_rig(path, "wt/second", out=printed.append).close()

    assert len(polls) == 2
    assert printed == [
        f'Another rig run holds the lock: wt/first (pid {rig.os.getpid()}), Claude Code session "rig-agent-1a" '
        "(SendMessage reaches it). Waiting for it to finish (Ctrl-C to give up)...",
        "Rig lock acquired.",
    ]
    assert path.read_text().startswith("wt/second ")


def test_the_holder_is_named_as_its_session_is_called_now(tmp_path, monkeypatch):
    session_file = claude_session(tmp_path, monkeypatch, "rig-agent-1a")
    entry = rig.lock_entry("wt/first")
    session_file.write_text('{"name": "renamed"}')
    assert rig.lock_holder(entry).endswith('Claude Code session "renamed" (SendMessage reaches it)')


def test_a_holder_whose_session_file_is_gone_or_unreadable_is_named_by_its_line_alone(tmp_path, monkeypatch):
    session_file = claude_session(tmp_path, monkeypatch, "rig-agent-1a")
    entry = rig.lock_entry("wt/first")
    line = f"wt/first (pid {rig.os.getpid()})"
    for contents in ("not json", '{"pid": 4242}', "[]"):
        session_file.write_text(contents)
        assert rig.lock_holder(entry) == line
    session_file.unlink()
    assert rig.lock_holder(entry) == line
    assert rig.lock_holder("") == "an unnamed process"


def test_a_terminal_run_is_named_by_user_and_tty(monkeypatch):
    monkeypatch.delenv("CLAUDE_PID", raising=False)
    monkeypatch.setattr(rig.getpass, "getuser", lambda: "tester")
    monkeypatch.setattr(rig.os, "ttyname", lambda _fd: "/dev/ttys003")
    assert rig.lock_holder(rig.lock_entry("wt/first")) == f"wt/first (pid {rig.os.getpid()}, user tester on ttys003)"

    def no_tty(_fd):
        raise OSError

    monkeypatch.setattr(rig.os, "ttyname", no_tty)
    assert rig.lock_entry("wt/first") == f"wt/first (pid {rig.os.getpid()}, user tester)\n"


def test_a_waiting_run_names_each_new_holder_once(tmp_path, monkeypatch):
    path = tmp_path / rig.LOCK_NAME
    held = [rig.lock_rig(path, "wt/first")]
    printed: list[str] = []

    def hand_over(_seconds):
        if len(printed) == 1:  # the first holder finishes and a third run takes the lock before us
            held[0].close()
            held[0] = rig.lock_rig(path, "wt/third")
        elif len(printed) == 2:
            held[0].close()

    monkeypatch.setattr(rig.time, "sleep", hand_over)
    rig.lock_rig(path, "wt/second", out=printed.append).close()

    assert [line.split(" (pid")[0] for line in printed[:2]] == [
        "Another rig run holds the lock: wt/first",
        "Another rig run holds the lock: wt/third",
    ]
    assert printed[2] == "Rig lock acquired."


def test_an_uncontested_lock_says_nothing(tmp_path):
    printed: list[str] = []
    rig.lock_rig(tmp_path / rig.LOCK_NAME, "wt/first", out=printed.append).close()
    assert printed == []


def test_a_run_colors_its_workspace_amber_while_it_waits_and_green_once_it_holds_the_lock(
    tmp_path, monkeypatch, workspace_colors
):
    path = tmp_path / rig.LOCK_NAME
    held = rig.lock_rig(path, "wt/first")
    assert workspace_colors == [rig.WORKSPACE_HELD]
    workspace_colors.clear()

    def release_on_second_poll(_seconds):
        assert workspace_colors == [rig.WORKSPACE_QUEUED]
        held.close()

    monkeypatch.setattr(rig.time, "sleep", release_on_second_poll)
    rig.lock_rig(path, "wt/second", out=lambda _line: None).close()

    assert workspace_colors == [rig.WORKSPACE_QUEUED, rig.WORKSPACE_HELD]


def test_main_clears_the_workspace_color_when_the_run_ends_but_not_after_a_dry_run(monkeypatch, workspace_colors):
    monkeypatch.setattr(rig, "hold_rig", lambda _dry_run: (None, None))
    monkeypatch.setattr(rig, "run_held", lambda *_args: 0)
    rig.main(["--dry-run"])
    assert workspace_colors == []
    rig.main([])
    assert workspace_colors == [None]


def test_main_clears_the_workspace_color_when_a_wait_is_given_up(monkeypatch, workspace_colors):
    def interrupted(_dry_run):
        raise KeyboardInterrupt

    monkeypatch.setattr(rig, "hold_rig", interrupted)
    with pytest.raises(KeyboardInterrupt):
        rig.main([])
    assert workspace_colors == [None]


def test_main_clears_the_workspace_color_after_a_wait_free_dry_run(monkeypatch, workspace_colors):
    monkeypatch.setattr(rig, "wait_free", lambda _path: None)
    monkeypatch.setattr(rig, "common_dir", lambda: Path("."))
    assert rig.main(["--wait-free", "--dry-run"]) == 0
    assert workspace_colors == [None]


def test_a_sigterm_while_queued_for_the_lock_still_clears_the_workspace_color(monkeypatch, workspace_colors):
    def queued(_dry_run):
        os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr(rig, "hold_rig", queued)
    with pytest.raises(SystemExit) as stopped:
        rig.main([])
    assert stopped.value.code == 128 + signal.SIGTERM
    assert workspace_colors == [None]


def test_workspace_color_calls_cmux_only_inside_a_cmux_workspace(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(rig.subprocess, "run", lambda command, **_kw: calls.append(command))
    monkeypatch.setattr(rig.shutil, "which", lambda _name: "/bin/cmux")
    monkeypatch.delenv("CMUX_WORKSPACE_ID", raising=False)
    real_workspace_color("Green")
    assert calls == []

    monkeypatch.setenv("CMUX_WORKSPACE_ID", "workspace:7")
    real_workspace_color("Green")
    real_workspace_color(None)
    assert calls == [
        ["cmux", "workspace-action", "--workspace", "workspace:7", "--action", "set-color", "--color", "Green"],
        ["cmux", "workspace-action", "--workspace", "workspace:7", "--action", "clear-color"],
    ]

    monkeypatch.setattr(rig.shutil, "which", lambda _name: None)
    calls.clear()
    real_workspace_color("Green")
    assert calls == []


def test_workspace_color_swallows_a_cmux_failure(monkeypatch):
    def fail(*_args, **_kwargs):
        raise rig.subprocess.TimeoutExpired("cmux", 5)

    monkeypatch.setattr(rig.subprocess, "run", fail)
    monkeypatch.setattr(rig.shutil, "which", lambda _name: "/bin/cmux")
    monkeypatch.setenv("CMUX_WORKSPACE_ID", "workspace:7")
    real_workspace_color("Amber")


def test_wait_free_returns_at_once_when_no_run_holds_the_lock(tmp_path, monkeypatch):
    def no_sleep(_seconds):
        raise AssertionError("wait_free polled a free lock")

    monkeypatch.setattr(rig.time, "sleep", no_sleep)
    printed: list[str] = []
    rig.wait_free(tmp_path / rig.LOCK_NAME, out=printed.append)
    assert printed == ["The rig lock is free."]


def test_wait_free_names_the_holder_and_returns_once_it_releases_without_taking_the_lock(tmp_path, monkeypatch):
    path = tmp_path / rig.LOCK_NAME
    held = rig.lock_rig(path, "wt/first")
    printed: list[str] = []
    monkeypatch.setattr(rig.time, "sleep", lambda _seconds: held.close())

    rig.wait_free(path, out=printed.append)

    assert [line.split(" (pid")[0] for line in printed] == [
        "Another rig run holds the lock: wt/first",
        "The rig lock is free.",
    ]
    rig.lock_rig(path, "wt/second", out=printed.append).close()  # wait_free kept no hold
    assert printed[-1] == "The rig lock is free."


def test_main_wait_free_stops_before_the_journal_and_env(tmp_path, monkeypatch):
    def untouched(*_args):
        raise AssertionError("--wait-free went past the lock")

    monkeypatch.setattr(rig, "common_dir", lambda: tmp_path)
    monkeypatch.setattr(rig, "hold_rig", untouched)
    monkeypatch.setattr(rig, "load_env", untouched)
    assert rig.main(["--wait-free"]) == 0


def test_check_tokens_stops_a_zha_run_without_an_admin_token():
    registry = AdapterRegistry.discover()
    step_file = next(f for f in load_step_files() if f.action == "turn_on_for")
    zha, shelly = rig.Suite(step_file, "zha"), rig.Suite(step_file, "shelly")
    env = {"HA_URL": "http://ha:8123", "HA_TOKEN": "tok"}
    with pytest.raises(SystemExit, match="HA_URL and HA_TOKEN"):
        rig.check_tokens({}, [shelly], registry)
    with pytest.raises(SystemExit, match="zha needs HA_ADMIN_TOKEN"):
        rig.check_tokens(env, [shelly, zha], registry)
    rig.check_tokens(env, [shelly], registry)
    rig.check_tokens({**env, "HA_ADMIN_TOKEN": "admin"}, [zha], registry)


class PauseHA:
    """States and turn_on/turn_off calls, for pause and resume."""

    def __init__(self, states: dict[str, str], failing: str | None = None):
        self.states, self.failing, self.calls = states, failing, []

    async def get_state(self, entity_id):
        return {"state": self.states[entity_id]} if entity_id in self.states else None

    async def call_service(self, domain, service, data):
        self.calls.append((domain, service, data["entity_id"]))
        if service == "turn_on" and data["entity_id"] == self.failing:
            raise RuntimeError("refused")


async def test_pause_turns_off_only_what_is_on_and_resumes_it(capsys):
    states = {"switch.al_office": "on", "automation.motion_hall": "off", "automation.motion_den": "on"}
    ha = PauseHA(states, failing="automation.motion_den")
    env = {"RIG_PAUSE": " switch.al_office, automation.motion_hall ,automation.motion_den,"}
    paused: list[str] = []

    await rig.pause(ha, rig.pause_list(env), paused)
    await rig.resume(ha, paused)

    assert paused == ["switch.al_office", "automation.motion_den"]
    assert ha.calls == [
        ("switch", "turn_off", "switch.al_office"),
        ("automation", "turn_off", "automation.motion_den"),
        ("switch", "turn_on", "switch.al_office"),
        ("automation", "turn_on", "automation.motion_den"),
    ]
    assert "Could not turn automation.motion_den back on" in capsys.readouterr().out


async def test_pause_stops_on_an_unknown_entity():
    ha = PauseHA({"switch.al_office": "on"})
    paused: list[str] = []

    with pytest.raises(SystemExit, match="switch.typo in RIG_PAUSE"):
        await rig.pause(ha, ["switch.al_office", "switch.typo"], paused)

    assert paused == ["switch.al_office"]


def test_pause_list_refuses_other_domains():
    with pytest.raises(SystemExit, match="automations and switches only, got light.hall"):
        rig.pause_list({"RIG_PAUSE": "switch.al_office, light.hall"})


def test_check_tokens_stops_a_hue_bridge_step_without_the_bridge_settings(tmp_path):
    registry = AdapterRegistry.discover()
    path = tmp_path / "steps.yaml"
    path.write_text(
        "action: set_scene\nrig_seconds: 5\ntests:\n  - name: t\n    roles: [light_onoff]\n"
        "    steps:\n      - bridge: {put: {on: {on: true}}}\n"
    )
    step_file = load_step_file(path)
    env = {"HA_URL": "http://ha:8123", "HA_TOKEN": "tok", "HA_ADMIN_TOKEN": "admin"}
    with pytest.raises(SystemExit, match="HUE_BRIDGE_HOST and HUE_APP_KEY"):
        rig.check_tokens(env, [rig.Suite(step_file, "hue")], registry)
    with pytest.raises(SystemExit, match="HUE_BRIDGE_HOST and HUE_APP_KEY"):
        rig.check_tokens({**env, "HUE_BRIDGE_HOST": "bridge"}, [rig.Suite(step_file, "hue")], registry)
    ready = {**env, "HUE_BRIDGE_HOST": "bridge", "HUE_APP_KEY": "key"}
    rig.check_tokens(ready, [rig.Suite(step_file, "hue")], registry)
    rig.check_tokens(env, [rig.Suite(step_file, "shelly")], registry)


def test_check_tokens_stops_a_run_of_an_adapter_with_options_without_an_admin_token():
    # Its options are pinned through device_side's options flow, which is admin only.
    registry = AdapterRegistry.discover()
    step_file = next(f for f in load_step_files() if f.action == "move")
    env = {"HA_URL": "http://ha:8123", "HA_TOKEN": "tok", "HUE_BRIDGE_HOST": "bridge", "HUE_APP_KEY": "key"}
    with pytest.raises(SystemExit, match="hue needs HA_ADMIN_TOKEN"):
        rig.check_tokens(env, [rig.Suite(step_file, "hue")], registry)
    rig.check_tokens({**env, "HA_ADMIN_TOKEN": "admin"}, [rig.Suite(step_file, "hue")], registry)


async def test_pause_journals_each_entity_before_turning_it_off(tmp_path):
    journal = Journal(tmp_path / rig.JOURNAL_NAME)
    ha = PauseHA({"switch.al_office": "on", "automation.motion_den": "on"})
    seen = []  # what the journal held as each call was sent
    call_service = ha.call_service

    async def journaled(domain, service, data):
        seen.append((service, journal.get("paused")))
        await call_service(domain, service, data)

    ha.call_service = journaled
    paused: list[str] = []
    await rig.pause(ha, list(ha.states), paused, journal)
    await rig.resume(ha, paused, journal)

    both = ["switch.al_office", "automation.motion_den"]
    assert seen == [("turn_off", both[:1]), ("turn_off", both), ("turn_on", both), ("turn_on", both)]
    assert not journal.path.exists()


class RigHA(fakes.FakeAdmin):
    async def close(self):
        pass


def rig_ha(monkeypatch, light: str, opt: bool, automation: str) -> RigHA:
    """One fake for both connections, with a light, device_side's options and a RIG_PAUSE automation."""
    monkeypatch.setattr(engine, "OPTIONS_RELOAD_S", 0)
    ha = RigHA(
        {"light.a": {"state": light, "attributes": {"brightness": 200}}, "automation.motion": {"state": automation}},
        options={"opt": opt},
    )
    ha.respond = lambda ha, action, data: {data["entity_id"]: {"status": "sent", "integration": "shelly"}}

    async def connect(env):
        return ha, ha

    monkeypatch.setattr(rig, "connect", connect)
    return ha


def put_back(ha: RigHA) -> bool:
    return (
        ha.states["light.a"] == {"entity_id": "light.a", "state": "on", "attributes": {"brightness": 200}}
        and ha.states["automation.motion"]["state"] == "on"
        and ha.options == {"opt": True, "other": False}
    )


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
async def test_a_signal_mid_case_puts_everything_back_and_leaves_no_journal(tmp_path, monkeypatch, capsys, signum):
    ha = rig_ha(monkeypatch, light="on", opt=True, automation="on")
    journal = Journal(tmp_path / rig.JOURNAL_NAME)
    steps = write(tmp_path, "steps.yaml", fakes.WAITING_MIDWAY)
    run_rig = rig.run_rig(
        {"RIG_PAUSE": "automation.motion"},
        [rig.Suite(load_step_file(steps), "shelly")],
        fakes.inventory("shelly", light_ct="light.a"),
        fakes.OPTION_REGISTRY,
        None,
        True,
        "c1",
        journal,
    )
    task = asyncio.create_task(run_rig)
    while ha.states["light.a"]["state"] != "off":
        await asyncio.sleep(0.005)
    assert set(journal.sections) == {"paused", "options", "taken", "stored", "power"}

    os.kill(os.getpid(), signum)
    with pytest.raises(asyncio.CancelledError):
        await task

    assert "Aborting: putting devices back" in capsys.readouterr().out
    assert put_back(ha)
    assert not journal.path.exists()


@pytest.mark.parametrize(("commit", "sources"), [("c1", ["rig run (`scripts/rig.py`), commit `c1short`"]), (None, [])])
async def test_records_cite_the_commit_ha_loaded_not_head_at_the_end(tmp_path, monkeypatch, capsys, commit, sources):
    rig_ha(monkeypatch, light="on", opt=True, automation="on")
    head = {"HEAD": "c1short"}
    monkeypatch.setattr(rig, "git", lambda *args, check=True: head.get(args[-1], f"{args[-1]}short"))

    async def run(*args, **kwargs):
        head["HEAD"] = "c2short"  # the session commits mid-run
        return engine.RunResult([])

    written = []

    async def write_records(result, ha, registry, bench_dir, date, source):
        written.append(source)
        return []

    monkeypatch.setattr(rig, "run", run)
    monkeypatch.setattr(rig, "write_report", lambda result, directory, title: tmp_path / "report.md")
    monkeypatch.setattr(rig, "write_records", write_records)

    assert await rig.run_rig({}, [], fakes.inventory("shelly"), fakes.OPTION_REGISTRY, None, True, commit) == 0
    assert written == sources
    assert ("No bench records" in capsys.readouterr().out) is (commit is None)


def aborted_journal(path: Path) -> Journal:
    """What a run killed mid-case leaves: the light it turned off, the option it saved and the automation it paused."""
    journal = Journal(path)
    journal.update(
        paused=["automation.motion"],
        options={"opt": True, "other": False},
        taken={"light.a": {"entity_id": "light.a", "state": "on", "attributes": {"brightness": 200}}},
        stored={},
        power={},
    )
    return journal


async def test_recover_puts_back_what_an_aborted_run_left(tmp_path, monkeypatch):
    ha = rig_ha(monkeypatch, light="off", opt=False, automation="off")
    printed = []

    await rig.recover(ha, ha, aborted_journal(tmp_path / rig.JOURNAL_NAME), out=printed.append)

    assert put_back(ha)
    assert [call[:2] for call in ha.calls] == [("light", "turn_on"), ("automation", "turn_on")]
    assert "Putting light.a back on." in printed
    assert not (tmp_path / rig.JOURNAL_NAME).exists()


async def test_recover_without_an_admin_token_leaves_the_options_in_the_journal(tmp_path, monkeypatch):
    ha = rig_ha(monkeypatch, light="off", opt=False, automation="off")
    journal = aborted_journal(tmp_path / rig.JOURNAL_NAME)

    await rig.recover(ha, None, journal, out=lambda _: None)

    assert ha.options == {"opt": False, "other": False}
    assert Journal(journal.path).sections == {"options": {"opt": True, "other": False}}


def test_main_recovers_before_the_plan_and_recover_alone_stops_there(tmp_path, monkeypatch, capsys):
    ha = rig_ha(monkeypatch, light="off", opt=False, automation="off")
    aborted_journal(tmp_path / rig.JOURNAL_NAME)
    monkeypatch.setattr(rig, "git", lambda *args, check=True: str(tmp_path) if "--git-common-dir" in args else "wt/x")
    monkeypatch.setattr(rig, "load_env", lambda: {"HA_URL": "http://ha:8123", "HA_TOKEN": "tok"})

    assert rig.main(["--dry-run", "--recover"]) == 1
    assert "the next run puts them back before its gate" in capsys.readouterr().out
    assert rig.main(["--recover"]) == 0
    assert put_back(ha)
    assert rig.main(["--recover"]) == 0
    assert "No aborted run left anything to put back." in capsys.readouterr().out


@pytest.mark.parametrize(
    ("error", "line"),
    [
        (asyncio.CancelledError, "Aborted."),
        (KeyboardInterrupt, "Aborted before putting everything back; the next run puts back the rest."),
    ],
)
def test_a_stopped_run_ends_on_one_line_not_a_traceback(capsys, error, line):
    async def stopped():
        raise error

    assert rig.run_tests(stopped()) == 1
    assert capsys.readouterr().out == f"{line}\n"


DEPLOY_ENV = {"RIG_SYNC_CMD": "sync", "RIG_RESTART_CMD": "restart", "HA_URL": "http://ha/", "HA_TOKEN": "tok"}


def fake_deploy(monkeypatch, signals: int = 0, returncode: int = 0) -> list[str]:
    """deploy.sh, receiving `signals` SIGTERMs as it runs, and wait_until_ready; returns what ran, in order."""
    ran = []

    def run(command, check, env, start_new_session):
        assert start_new_session  # a terminal Ctrl-C must not reach it
        for _ in range(signals):
            os.kill(os.getpid(), signal.SIGTERM)
        ran.append("deploy")
        if returncode:
            raise rig.subprocess.CalledProcessError(returncode, command)

    monkeypatch.setattr(rig.subprocess, "run", run)
    monkeypatch.setattr(rig, "wait_until_ready", lambda url, token, admin_token, timeout: ran.append(f"wait {timeout}"))
    return ran


def test_a_signal_mid_deploy_stops_the_run_once_ha_is_back(monkeypatch, capsys):
    ran = fake_deploy(monkeypatch, signals=1)
    before = signal.getsignal(signal.SIGTERM)
    with pytest.raises(rig.Aborted, match="after the deploy"):
        rig.deploy_and_wait(DEPLOY_ENV, "b")
    assert ran == ["deploy", f"wait {rig.READY_TIMEOUT_S}"]
    assert "Stopping once the deploy and HA's restart finish" in capsys.readouterr().out
    assert signal.getsignal(signal.SIGTERM) is before


def test_a_second_signal_mid_deploy_stops_at_once(monkeypatch):
    ran = fake_deploy(monkeypatch, signals=2)
    with pytest.raises(rig.Aborted, match="mid-deploy"):
        rig.deploy_and_wait(DEPLOY_ENV, "b")
    assert ran == []


def test_a_failed_deploy_ends_on_one_line(monkeypatch):
    fake_deploy(monkeypatch, returncode=3)
    with pytest.raises(SystemExit, match=r"^Deploy failed \(exit 3\); HA may be mid-restart"):
        rig.deploy_and_wait(DEPLOY_ENV, "b")


def test_without_a_deploy_it_waits_briefly_and_a_signal_stops_at_once(monkeypatch):
    ran = fake_deploy(monkeypatch)
    rig.deploy_and_wait(DEPLOY_ENV, None)
    assert ran == ["wait 15"]

    def wait(url, token, admin_token, timeout):
        os.kill(os.getpid(), signal.SIGTERM)
        pytest.fail("not stopped")

    monkeypatch.setattr(rig, "wait_until_ready", wait)
    with pytest.raises(rig.Aborted, match="^Aborted.$"), rig.end_on_signals():
        rig.deploy_and_wait(DEPLOY_ENV, None)


def test_a_signal_before_the_tests_ends_the_run_on_one_line():
    before = signal.getsignal(signal.SIGHUP)
    with pytest.raises(rig.Aborted, match="^Aborted.$"), rig.end_on_signals():
        os.kill(os.getpid(), signal.SIGHUP)
    assert signal.getsignal(signal.SIGHUP) is before
