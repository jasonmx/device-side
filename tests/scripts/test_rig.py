"""scripts/rig.py's preflight and gate. Nothing here touches the rig: no ssh, no HA."""

import importlib.util
import itertools
import types
from pathlib import Path

import pytest

from custom_components.device_side.core.registry import AdapterRegistry
from scripts.fingerprint import adapter_path, fingerprint
from tests.rig.engine import load_step_file, load_step_files
from tests.rig.inventory import Inventory, load_env, main_checkout

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
    path = write(
        tmp_path, "inventory.yaml", "zha:\n  - entity_id: light.g\n    roles: [group]\n    members: light.a\n"
    )
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


def test_select_plan_lines_and_estimate(inventory, tmp_path):
    step_files = [step_file for step_file in load_step_files() if step_file.action in ("turn_off_for", "turn_on_for")]
    suites = rig.select(step_files, inventory, None)
    assert [(suite.integration, suite.action) for suite in suites] == [
        ("shelly", "turn_off_for"), ("hue", "turn_off_for"), ("shelly", "turn_on_for"), ("hue", "turn_on_for"),
    ]
    assert [suite.integration for suite in rig.select(step_files, inventory, ["hue"])] == ["hue", "hue"]

    registry = AdapterRegistry.discover()
    shelly_on = [suite for suite in suites if suite.integration == "shelly" and suite.action == "turn_on_for"]
    bench = tmp_path / "bench"
    (bench / "shelly").mkdir(parents=True)
    current = fingerprint(adapter_path(registry.adapter("turn_on_for", "shelly")))
    write(
        bench / "shelly",
        "turn_on_for.md",
        f"| Result | pass |\n| Fingerprint | `{current}` |\n| Capabilities | `RGBCCT`, `Switch` |\n"
        "| Fields | `brightness`, `color_temp_kelvin`, `rgb_color`, `transition` |\n",
    )
    assert rig.plan_lines(shelly_on + suites[1:2], inventory, registry, bench_dir=bench) == [
        "shelly / turn_on_for -> switch.plug (beta)",
        "    on_then_off[switch_plug]: switch.plug",
        "    on_then_off[light_onoff]: no light_onoff entity in inventory",
        "    on_then_off[light_wrapped]: no light_wrapped entity in inventory",
        "    refuses_brightness_on_a_wrapper[light_wrapped]: no light_wrapped entity in inventory",
        "    refuses_brightness_on_a_relay_light[light_onoff]: no light_onoff entity in inventory",
        "    bulb_on_then_off[light_dimmable]: no light_dimmable entity in inventory",
        "    bulb_brightness_then_off[light_dimmable]: no light_dimmable entity in inventory",
        "    bulb_color_temp_then_off[light_ct]: no light_ct entity in inventory",
        "    bulb_transition_then_off[light_dimmable]: no light_dimmable entity in inventory",
        "    rgbcct_bulb_rgb_then_off[light_color]: no light_color entity in inventory",
        "    rgbcct_bulb_rgb_then_off[light_color] observed: no light_color entity in inventory",
        "hue / turn_off_for (no adapter, will skip)",
    ]
    # The tier is check_tiers': with no records, nothing is proven.
    assert rig.plan_lines(shelly_on, inventory, registry, "on_then", bench_dir=tmp_path) == [
        "shelly / turn_on_for -> switch.plug (untested)",
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
    monkeypatch.setattr(rig, "deployed_tree", lambda status_cmd: deployed)


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
    state = rig.deploy_state("ssh myhost status")
    assert state.needed is needed
    assert (state.blocker is None) if blocker is None else (blocker in state.blocker)


def run_git(*args: str) -> None:
    rig.subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
                       check=True, capture_output=True)


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


def test_a_held_rig_lock_makes_a_second_run_wait_naming_the_holder(tmp_path, monkeypatch):
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
        f"Another rig run holds the lock: wt/first (pid {rig.os.getpid()}). "
        "Waiting for it to finish (Ctrl-C to give up)...",
        "Rig lock acquired.",
    ]
    assert path.read_text().startswith("wt/second ")


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
    env = {"HA_URL": "http://ha:8123", "HA_TOKEN": "tok"}
    with pytest.raises(SystemExit, match="hue needs HA_ADMIN_TOKEN"):
        rig.check_tokens(env, [rig.Suite(step_file, "hue")], registry)
    rig.check_tokens({**env, "HA_ADMIN_TOKEN": "admin"}, [rig.Suite(step_file, "hue")], registry)
