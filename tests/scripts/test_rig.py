"""scripts/rig.py's preflight and gate. Nothing here touches the rig: no ssh, no HA."""

import importlib.util
import itertools
import types
from pathlib import Path

import pytest

from custom_components.device_side.core.registry import AdapterRegistry
from tests.rig.inventory import Inventory, RigModule, load_env, rig_modules

REPO = Path(__file__).parents[2]
_spec = importlib.util.spec_from_file_location("rig", REPO / "scripts" / "rig.py")
rig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rig)


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


def test_inventory_entity_by_role(inventory):
    assert inventory.entity("shelly", "switch_plug") == "switch.plug"
    assert inventory.entity("shelly", "light_dimmable") is None
    assert inventory.entity("zha", "switch_plug") is None


def test_load_env_reads_file_and_defaults_ssh(tmp_path, monkeypatch):
    monkeypatch.delenv("HA_URL", raising=False)
    monkeypatch.delenv("RIG_SSH", raising=False)
    monkeypatch.setenv("HA_TOKEN", "from-env")
    env = load_env(write(tmp_path, ".env.rig", "# comment\nHA_URL='http://ha:8123'\nHA_TOKEN=from-file\n"))
    assert env == {"HA_URL": "http://ha:8123", "HA_TOKEN": "from-env", "RIG_SSH": "ha"}


def test_rig_modules_read_constants_without_importing():
    shelly = next(module for module in rig_modules() if module.path.name == "test_shelly_turn_on_for.py")
    assert (shelly.platform, shelly.feature) == ("shelly", "turn_on_for")
    assert shelly.roles == ("switch_plug", "light_onoff")
    assert shelly.seconds > 0


def test_select_and_plan_lines(inventory):
    modules = [
        RigModule(Path("test_shelly_turn_on_for.py"), "shelly", "turn_on_for", ("switch_plug", "light_dimmable"), 20),
        RigModule(Path("test_hue_move.py"), "hue", "move", ("light_color",), 10),
        RigModule(Path("test_zha_turn_on_for.py"), "zha", "turn_on_for", ("switch_plug",), 10),
    ]
    selected = rig.select(modules, inventory, None)
    assert [module.platform for module in selected] == ["shelly", "hue"]
    assert rig.select(modules, inventory, ["hue"]) == [modules[1]]

    lines = rig.plan_lines(selected, inventory, AdapterRegistry.discover())
    assert lines == [
        "shelly / turn_on_for -> switch.plug (experimental)",
        "hue / move -> light.lamp (no adapter, will skip)",
    ]


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


def test_rig_modules_name_a_missing_constant(tmp_path):
    write(tmp_path, "test_shelly_toggle_for.py", "ROLES = ['switch_plug']\n")
    with pytest.raises(ValueError, match=r"test_shelly_toggle_for.py: .*RIG_SECONDS"):
        rig_modules(tmp_path)


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


def test_wait_until_ready_points_at_the_missing_entry(monkeypatch):
    fake_clock(monkeypatch)
    fake_ha(monkeypatch, [{"state": "RUNNING"}, []] * 5)
    with pytest.raises(SystemExit, match="Add integration"):
        rig.wait_until_ready("http://ha", "token", timeout=35, sleep=lambda _: None)


def fake_git(monkeypatch, *, dirty="", remote="abc refs/heads/b", remote_tree="tree1", deployed="old"):
    replies = {
        "rev-parse --abbrev-ref HEAD": "b",
        f"rev-parse HEAD:{rig.COMPONENT}": "tree1",
        f"status --porcelain -- {rig.COMPONENT}": dirty,
        "ls-remote origin refs/heads/b": remote,
        f"rev-parse --quiet --verify abc:{rig.COMPONENT}": remote_tree,
    }
    monkeypatch.setattr(rig, "git", lambda *args, check=True: replies[" ".join(args)])
    monkeypatch.setattr(rig, "deployed_tree", lambda ssh: deployed)


@pytest.mark.parametrize(
    ("kwargs", "needed", "blocker"),
    [
        ({}, True, None),
        ({"deployed": "tree1"}, False, None),
        ({"dirty": " M x.py"}, True, "uncommitted changes"),
        ({"remote": ""}, True, "not on origin"),
        ({"remote_tree": "tree0"}, True, "does not match HEAD"),
    ],
)
def test_deploy_state(monkeypatch, kwargs, needed, blocker):
    fake_git(monkeypatch, **kwargs)
    state = rig.deploy_state("ha")
    assert state.needed is needed
    assert (state.blocker is None) if blocker is None else (blocker in state.blocker)
