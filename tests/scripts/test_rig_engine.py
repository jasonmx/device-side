"""The rig engine against a fake HAClient: a state machine plus scripted device_side responses. No HA, no rig."""

import asyncio
import copy
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.device_side.core.registry import AdapterRegistry
from tests.rig import engine
from tests.rig.client import HAError
from tests.rig.engine import (
    Outcome,
    RunResult,
    Suite,
    SuiteResult,
    load_step_file,
    render_record,
    rig_facts,
    run,
    write_records,
)
from tests.rig.inventory import Inventory, RigEntity

TOL = 0.2
PENDING: list[asyncio.TimerHandle | asyncio.Task] = []
TOLERANCE = {"shelly": TOL, "zha": TOL, "fake": TOL}
REGISTRY = AdapterRegistry.discover()

ON_THEN_OFF = """
action: turn_on_for
rig_seconds: 5
tests:
  - name: on_then_off
    roles: [switch_plug]
    steps:
      - set: {state: off}
      - call: {duration: 0.6}
      - expect_response: {status: expected, integration: self}
      - expect_state: {state: on, within: tol}
      - wait: duration - tol
      - expect_state: {state: on}
      - expect_state: {state: off, within: 2 * tol}
"""


@pytest.fixture(autouse=True)
async def _cancel_pending():
    """Device timers and ramps outlive the run that started them; HA's test plugin fails on lingering ones."""
    yield
    for pending in PENDING:
        pending.cancel()
    await asyncio.gather(*(task for task in PENDING if isinstance(task, asyncio.Task)), return_exceptions=True)
    PENDING.clear()


class FakeHA:
    """Entity states HA would hold, plain on/off services, and device_side actions answered by `respond`."""

    def __init__(self, states: dict[str, dict], respond: Callable | None = None):
        self.states = {
            entity_id: {"entity_id": entity_id, "state": "off", "attributes": {}} | state
            for entity_id, state in states.items()
        }
        self.respond = respond
        self.calls: list[tuple[str, str, dict]] = []

    def set(self, entity_id: str, state: str, **attributes) -> None:
        self.states[entity_id] = {"entity_id": entity_id, "state": state, "attributes": attributes}

    def later(self, delay: float, entity_id: str, state: str) -> None:
        PENDING.append(asyncio.get_running_loop().call_later(delay, self.set, entity_id, state))

    async def call_service(self, domain: str, service: str, data: dict | None = None, return_response=False):
        self.calls.append((domain, service, dict(data or {})))
        if domain == "device_side":
            return self.respond(self, service, data)
        entity_id = data["entity_id"]
        attributes = {key: value for key, value in data.items() if key != "entity_id"}
        state = "on" if service == "turn_on" else "off"
        members = self.states[entity_id]["attributes"].get("entity_id")
        for member in members or []:
            self.set(member, state, **attributes)
        self.set(entity_id, state, **attributes)
        if members:
            self.states[entity_id]["attributes"]["entity_id"] = members
        return None

    async def get_state(self, entity_id: str) -> dict | None:
        return copy.deepcopy(self.states.get(entity_id))

    async def wait_for(self, entity_id: str, predicate, timeout: float):
        async with asyncio.timeout(timeout):
            while not predicate(state := await self.get_state(entity_id)):
                await asyncio.sleep(0.005)
        return state

    async def command(self, payload: dict):
        return {
            "get_config": {"version": "2026.10.1"},
            "config/entity_registry/list_for_display": {"entities": [{"ei": "switch.plug", "di": "d1"}]},
            "config/device_registry/list": [{"id": "d1", "model": "Mini", "model_id": "S3", "sw_version": "2.0"}],
        }[payload["type"]]


def timer_on(ha: FakeHA, action: str, data: dict) -> dict:
    """turn_on_for as a device with a working timer: on now, off after the duration."""
    entity_id = data["entity_id"]
    ha.set(entity_id, "on")
    ha.later(data["duration"]["seconds"], entity_id, "off")
    return {entity_id: {"status": "confirmed", "integration": "shelly"}}


def inventory(integration: str = "shelly", **roles: str) -> Inventory:
    entities = [RigEntity(entity_id, frozenset({role})) for role, entity_id in roles.items()]
    return Inventory({integration: entities})


def suite(tmp_path: Path, text: str, integration: str = "shelly") -> Suite:
    path = tmp_path / "steps.yaml"
    path.write_text(text)
    return Suite(load_step_file(path), integration)


async def run_one(ha, steps: Suite, inv: Inventory, registry=REGISTRY, **kwargs) -> RunResult:
    return await run([steps], inv, registry, ha, tolerance=TOLERANCE, out=lambda _: None, **kwargs)


def outcomes(result: RunResult) -> dict[str, tuple[Outcome, str]]:
    return {case.id: (case.outcome, case.detail) for suite in result.suites for case in suite.cases}


async def test_a_timed_on_off_passes_and_restores(tmp_path):
    ha = FakeHA({"switch.plug": {"state": "on"}}, timer_on)
    result = await run_one(ha, suite(tmp_path, ON_THEN_OFF), inventory(switch_plug="switch.plug"))
    assert outcomes(result) == {"on_then_off[switch_plug]": (Outcome.PASS, "")}
    assert ("device_side", "turn_on_for", {"entity_id": "switch.plug", "duration": {"seconds": 0.6}}) in ha.calls
    assert ha.calls[-1] == ("switch", "turn_on", {"entity_id": "switch.plug"})
    assert result.suites[0].cases[0].reached
    assert not result.failed


async def test_a_device_that_never_turns_off_fails_on_the_timeout(tmp_path):
    def stuck(ha, action, data):
        ha.set(data["entity_id"], "on")
        return {data["entity_id"]: {"status": "confirmed", "integration": "shelly"}}

    ha = FakeHA({"switch.plug": {}}, stuck)
    result = await run_one(ha, suite(tmp_path, ON_THEN_OFF), inventory(switch_plug="switch.plug"))
    outcome, detail = outcomes(result)["on_then_off[switch_plug]"]
    assert outcome is Outcome.FAIL
    assert detail.startswith("step 7 (expect_state): switch.plug: expected {'state': 'off'} within 0.4 s")
    assert result.failed


async def test_a_sent_status_fails_where_the_adapter_can_confirm(tmp_path):
    def sent(ha, action, data):
        return {data["entity_id"]: {"status": "sent", "integration": "shelly"}}

    ha = FakeHA({"switch.plug": {}}, sent)
    result = await run_one(ha, suite(tmp_path, ON_THEN_OFF), inventory(switch_plug="switch.plug"))
    assert "status is 'sent', expected 'confirmed'" in outcomes(result)["on_then_off[switch_plug]"][1]


REFUSAL = """
action: turn_on_for
rig_seconds: 5
tests:
  - name: refuses
    roles: [light_wrapped]
    steps:
      - call: {duration: 6, brightness: 128}
      - expect_error: {key: all_targets_failed, summary: fields_not_supported}
      - expect_state: {state: unchanged}
"""


def refuse(detail: str) -> Callable:
    def _respond(ha, action, data):
        summary = f"{data['entity_id']}: {detail}"
        raise HAError({"translation_key": "all_targets_failed", "translation_placeholders": {"summary": summary}})

    return _respond


async def test_a_refusal_passes_when_key_summary_and_state_match(tmp_path):
    ha = FakeHA({"light.lamp": {"state": "on"}}, refuse("fields_not_supported"))
    result = await run_one(ha, suite(tmp_path, REFUSAL), inventory(light_wrapped="light.lamp"))
    assert outcomes(result) == {"refuses[light_wrapped]": (Outcome.PASS, "")}
    assert not result.suites[0].cases[0].reached


async def test_an_expect_error_mismatch_fails_naming_both_summaries(tmp_path):
    ha = FakeHA({"light.lamp": {}}, refuse("fields_not_tested"))
    result = await run_one(ha, suite(tmp_path, REFUSAL), inventory(light_wrapped="light.lamp"))
    outcome, detail = outcomes(result)["refuses[light_wrapped]"]
    assert outcome is Outcome.FAIL
    assert detail == (
        "step 2 (expect_error): error summary is 'light.lamp: fields_not_tested', "
        "expected 'light.lamp: fields_not_supported'"
    )


async def test_a_call_that_succeeds_where_an_error_is_expected_fails(tmp_path):
    ha = FakeHA({"light.lamp": {}}, timer_on)
    result = await run_one(ha, suite(tmp_path, REFUSAL), inventory(light_wrapped="light.lamp"))
    assert "succeeded where an error was expected" in outcomes(result)["refuses[light_wrapped]"][1]


async def test_an_unexpected_error_fails_the_call_step(tmp_path):
    ha = FakeHA({"switch.plug": {}}, refuse("capability_not_tested"))
    result = await run_one(ha, suite(tmp_path, ON_THEN_OFF), inventory(switch_plug="switch.plug"))
    assert outcomes(result)["on_then_off[switch_plug]"][1].startswith("step 2 (call): device_side.turn_on_for raised")


async def test_a_failure_still_restores_brightness(tmp_path):
    ha = FakeHA({"light.lamp": {"state": "on", "attributes": {"brightness": 50, "hs_color": [30, 50]}}}, None)
    text = """
action: turn_on_for
rig_seconds: 5
tests:
  - name: fails
    roles: [light_dimmable]
    steps:
      - set: {state: off}
      - expect_state: {state: on}
"""
    result = await run_one(ha, suite(tmp_path, text), inventory(light_dimmable="light.lamp"))
    assert outcomes(result)["fails[light_dimmable]"][0] is Outcome.FAIL
    assert ha.calls[-1] == ("light", "turn_on", {"entity_id": "light.lamp", "brightness": 50, "hs_color": [30, 50]})
    assert ha.states["light.lamp"]["state"] == "on"


OBSERVED = ON_THEN_OFF + "      - observe: Did it click twice?\n"


async def test_observe_unattended_reports_not_observed_and_proves_nothing(tmp_path):
    ha = FakeHA({"switch.plug": {}}, timer_on)
    result = await run_one(ha, suite(tmp_path, OBSERVED), inventory(switch_plug="switch.plug"), ask=None)
    assert outcomes(result) == {"on_then_off[switch_plug]": (Outcome.NOT_OBSERVED, "")}
    assert result.suites[0].proven == []
    assert not result.suites[0].recordable
    record = render_record(result.suites[0], "Shelly", "2026.10.1", [], "2026-10-25", "test")
    assert "| Capabilities | none |" in record
    assert "`not observed`" in record


@pytest.mark.parametrize(("answer", "outcome"), [("y", Outcome.PASS), ("", Outcome.FAIL)])
async def test_observe_asks_and_a_no_fails(tmp_path, answer, outcome):
    asked = []

    def ask(prompt):
        asked.append(prompt)
        return answer

    ha = FakeHA({"switch.plug": {}}, timer_on)
    result = await run_one(ha, suite(tmp_path, OBSERVED), inventory(switch_plug="switch.plug"), ask=ask)
    assert asked == ["    Did it click twice? [y/N] "]
    assert outcomes(result)["on_then_off[switch_plug]"][0] is outcome


ONLY = """
action: turn_on_for
rig_seconds: 5
tests:
  - name: everywhere
    roles: [switch_plug]
    steps: [{observe: 'ok?'}]
  - name: elsewhere
    roles: [switch_plug]
    only: [zha]
    steps: [{observe: 'ok?'}]
  - name: needs_a_dimmer
    roles: [light_dimmable]
    steps: [{observe: 'ok?'}]
"""


async def test_only_and_missing_roles_narrow_the_cases(tmp_path):
    ha = FakeHA({"switch.plug": {}})
    result = await run_one(ha, suite(tmp_path, ONLY), inventory(switch_plug="switch.plug"), ask=lambda _: "y")
    assert outcomes(result) == {
        "everywhere[switch_plug]": (Outcome.PASS, ""),
        "needs_a_dimmer[light_dimmable]": (Outcome.SKIPPED, "no light_dimmable entity in inventory"),
    }


async def test_a_keyword_runs_a_subset_and_marks_the_suite_partial(tmp_path):
    ha = FakeHA({"switch.plug": {}})
    inv = inventory(switch_plug="switch.plug")
    result = await run_one(ha, suite(tmp_path, ONLY), inv, ask=lambda _: "y", keyword="everywhere")
    assert list(outcomes(result)) == ["everywhere[switch_plug]"]
    assert not result.suites[0].recordable


async def test_a_suite_without_an_adapter_is_skipped(tmp_path):
    result = await run_one(FakeHA({}), suite(tmp_path, ONLY, "hue"), Inventory({"hue": []}))
    assert result.suites == []


GROUP = """
action: turn_on_for
rig_seconds: 5
tests:
  - name: every_member
    roles: [group]
    steps:
      - set: {state: off}
      - call: {duration: 6}
      - expect_response: {status: sent, integration: self}
      - expect_state: {state: on, within: tol}
"""


def group_ha(respond) -> FakeHA:
    members = ["light.a", "light.b"]
    return FakeHA({"light.room": {"attributes": {"entity_id": members}}, "light.a": {}, "light.b": {}}, respond)


def members_on(*members: str) -> Callable:
    def _respond(ha, action, data):
        for member in members:
            ha.set(member, "on")
        return {member: {"status": "sent", "integration": "fake"} for member in ("light.a", "light.b")}

    return _respond


GROUP_REGISTRY = SimpleNamespace(
    adapter=lambda action, integration: SimpleNamespace(scope=SimpleNamespace(confirmable=False, fields=frozenset()))
)


async def test_a_group_checks_every_member(tmp_path):
    ha = group_ha(members_on("light.a", "light.b"))
    steps = suite(tmp_path, GROUP, "fake")
    result = await run_one(ha, steps, inventory("fake", group="light.room"), registry=GROUP_REGISTRY)
    assert outcomes(result) == {"every_member[group]": (Outcome.PASS, "")}


async def test_a_group_fails_on_a_lagging_member(tmp_path):
    ha = group_ha(members_on("light.a"))
    steps = suite(tmp_path, GROUP, "fake")
    result = await run_one(ha, steps, inventory("fake", group="light.room"), registry=GROUP_REGISTRY)
    outcome, detail = outcomes(result)["every_member[group]"]
    assert outcome is Outcome.FAIL
    assert detail.startswith("step 4 (expect_state): light.b: expected {'state': 'on'}")


async def test_fields_in_scope_count_only_when_the_call_reaches_the_device(tmp_path):
    text = """
action: turn_on_for
rig_seconds: 5
tests:
  - name: dims
    roles: [light_dimmable]
    steps:
      - call: {duration: 6, brightness: 128, transition: 1}
      - expect_response: {status: expected}
"""
    scope = SimpleNamespace(confirmable=False, fields=frozenset({"brightness"}))
    registry = SimpleNamespace(adapter=lambda action, integration: SimpleNamespace(scope=scope))

    def sent(ha, action, data):
        return {data["entity_id"]: {"status": "sent"}}

    result = await run_one(
        FakeHA({"light.lamp": {}}, sent), suite(tmp_path, text, "fake"), inventory("fake", light_dimmable="light.lamp"),
        registry=registry,
    )
    case = result.suites[0].cases[0]
    assert (case.outcome, case.fields, case.reached) == (Outcome.PASS, frozenset({"brightness"}), True)


SAMPLE = """
action: turn_on_for
rig_seconds: 5
tests:
  - name: ramps
    roles: [light_dimmable]
    steps:
      - call: {duration: 6}
      - sample: {attribute: brightness, for: 0.3, every: 0.05, expect: EXPECT, max: 200}
"""


def ramp(step: int) -> Callable:
    """Brightness that changes by `step` every 50 ms, from 100, until the test ends."""

    def _respond(ha, action, data):
        async def _ramp():
            brightness = 100
            while True:
                await asyncio.sleep(0.05)
                brightness += step
                ha.set(data["entity_id"], "on", brightness=brightness)

        ha.set(data["entity_id"], "on", brightness=100)

        PENDING.append(asyncio.get_running_loop().create_task(_ramp()))
        return {data["entity_id"]: {"status": "confirmed"}}

    return _respond


@pytest.mark.parametrize(
    ("expect", "step", "failure"),
    [
        ("rising", 5, ""),
        ("steady", 0, ""),
        ("rising", 0, "did not rise steadily"),
        ("falling", 5, "did not fall steadily"),
        ("steady", 5, "moved"),
        ("rising", 50, "rose above 200"),
    ],
)
async def test_sample(tmp_path, expect, step, failure):
    ha = FakeHA({"light.lamp": {}}, ramp(step))
    steps = suite(tmp_path, SAMPLE.replace("EXPECT", expect))
    result = await run_one(ha, steps, inventory(light_dimmable="light.lamp"))
    outcome, detail = outcomes(result)["ramps[light_dimmable]"]
    assert outcome is (Outcome.FAIL if failure else Outcome.PASS)
    assert failure in detail


async def test_duration_before_any_call_fails_the_step(tmp_path):
    text = "action: turn_on_for\nrig_seconds: 5\ntests:\n  - name: early\n    roles: [switch_plug]\n    steps:\n"
    text += "      - wait: duration\n"
    result = await run_one(FakeHA({"switch.plug": {}}), suite(tmp_path, text), inventory(switch_plug="switch.plug"))
    detail = outcomes(result)["early[switch_plug]"][1]
    assert detail == "step 1 (wait): duration is unset: no call has set a duration yet"


async def test_rig_facts_maps_entities_to_their_devices():
    version, devices = await rig_facts(FakeHA({}), ["switch.plug", "light.wrapper", "switch.plug"])
    assert version == "2026.10.1"
    assert [str(device) for device in devices] == ["Mini (`S3`), firmware `2.0`"]


async def test_a_full_pass_writes_a_record_and_a_failure_writes_none(tmp_path):
    ha = FakeHA({"switch.plug": {}}, timer_on)
    steps = suite(tmp_path, ON_THEN_OFF)
    passed = await run_one(ha, steps, inventory(switch_plug="switch.plug"))
    failed = RunResult([SuiteResult(steps, passed.suites[0].adapter, [], complete=True)])
    assert await write_records(failed, ha, REGISTRY, tmp_path / "bench", "2026-10-25", "test") == []

    [path] = await write_records(passed, ha, REGISTRY, tmp_path / "bench", "2026-10-25", "rig run")
    assert path == tmp_path / "bench" / "shelly" / "turn_on_for.md"
    record = path.read_text()
    assert record.startswith("# Shelly · turn_on_for\n")
    assert "| Fingerprint | `" in record and "(`integrations/shelly/turn_on_for.py`) |" in record
    assert "| Device | Mini (`S3`), firmware `2.0` |" in record
    assert "| Capabilities | `Switch` |" in record
    assert "| Fields | none |" in record
    assert "| `on_then_off[switch_plug]` | `switch` (switch_plug) | pass |" in record
    assert "switch.plug" not in record


def header(role: str) -> str:
    """A one-test step file on `role`, steps to follow."""
    return f"action: turn_on_for\nrig_seconds: 5\ntests:\n  - name: t\n    roles: [{role}]\n    steps:\n"


async def test_a_failed_restore_is_logged_and_keeps_the_result(tmp_path, caplog):
    class Unreachable(FakeHA):
        async def call_service(self, domain, service, data=None, return_response=False):
            if service == "turn_on":
                raise OSError("device gone")
            return await super().call_service(domain, service, data, return_response)

    ha = Unreachable({"light.lamp": {"state": "on"}})
    text = header("light_dimmable") + "      - set: {state: off}\n      - expect_state: {state: on}\n"
    result = await run_one(ha, suite(tmp_path, text), inventory(light_dimmable="light.lamp"))
    assert outcomes(result)["t[light_dimmable]"][0] is Outcome.FAIL
    assert "Could not restore light.lamp to on: device gone" in caplog.text


@pytest.mark.parametrize(("brightness", "outcome"), [(50, Outcome.PASS), (39, Outcome.FAIL), (61, Outcome.FAIL)])
async def test_a_range_bounds_a_drifting_attribute(tmp_path, brightness, outcome):
    ha = FakeHA({"light.lamp": {"state": "on", "attributes": {"brightness": brightness}}})
    text = header("light_dimmable") + "      - expect_state: {brightness: {min: 40, max: 60}}\n"
    result = await run_one(ha, suite(tmp_path, text), inventory(light_dimmable="light.lamp"))
    assert outcomes(result)["t[light_dimmable]"][0] is outcome


async def test_set_activates_a_scene_without_waiting_on_its_state(tmp_path):
    ha = FakeHA({"scene.evening": {"state": "2026-10-25T10:00:00+00:00"}})
    text = header("scene") + "      - set: {state: on}\n"
    result = await run_one(ha, suite(tmp_path, text), inventory(scene="scene.evening"))
    assert outcomes(result)["t[scene]"] == (Outcome.PASS, "")
    assert ("scene", "turn_on", {"entity_id": "scene.evening"}) in ha.calls


async def test_admin_integrations_run_on_the_admin_connection(tmp_path):
    ha, admin = FakeHA({"switch.plug": {}}), FakeHA({"switch.plug": {}}, timer_on)
    await run_one(ha, suite(tmp_path, ON_THEN_OFF, "zha"), inventory("zha", switch_plug="switch.plug"), admin=admin)
    assert not ha.calls
    assert any(domain == "device_side" for domain, _, _ in admin.calls)


async def test_admin_integrations_skip_without_an_admin_connection(tmp_path):
    ha = FakeHA({"switch.plug": {}}, timer_on)
    result = await run_one(ha, suite(tmp_path, ON_THEN_OFF, "zha"), inventory("zha", switch_plug="switch.plug"))
    assert result.suites == []
    assert not ha.calls


def powered_inventory() -> Inventory:
    """A bulb that draws power through a plug, both on ZHA."""
    return Inventory(
        {
            "zha": [
                RigEntity("light.bulb", frozenset({"light_dimmable"}), "switch.plug"),
                RigEntity("switch.plug", frozenset({"switch_plug"})),
            ]
        }
    )


async def test_a_case_on_an_unpowered_entity_fails_before_any_step(tmp_path):
    ha = FakeHA({"light.bulb": {"state": "on"}, "switch.plug": {"state": "off"}})
    text = header("light_dimmable") + "      - set: {state: off}\n"
    result = await run_one(ha, suite(tmp_path, text, "zha"), powered_inventory(), admin=ha)
    outcome, detail = outcomes(result)["t[light_dimmable]"]
    assert outcome is Outcome.FAIL
    assert detail == "power: light.bulb draws power through switch.plug, which is off; turn it on"
    assert ha.calls == []


async def test_switching_a_supply_puts_what_it_powers_back_once_it_rejoins(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "POWER_SETTLE_S", 0)
    monkeypatch.setattr(engine, "POWER_RETRY_S", 0.01)

    class Rejoining(FakeHA):
        refusals = 2

        async def call_service(self, domain, service, data=None, return_response=False):
            if domain == "light" and self.refusals:
                self.refusals -= 1
                raise OSError("no route")
            return await super().call_service(domain, service, data, return_response)

    ha = Rejoining({"light.bulb": {"state": "on", "attributes": {"brightness": 90}}, "switch.plug": {"state": "on"}})
    text = header("switch_plug") + "      - set: {state: off}\n"
    result = await run_one(ha, suite(tmp_path, text, "zha"), powered_inventory(), admin=ha)
    assert outcomes(result)["t[switch_plug]"][0] is Outcome.PASS
    assert ha.calls[-2:] == [
        ("switch", "turn_on", {"entity_id": "switch.plug"}),
        ("light", "turn_on", {"entity_id": "light.bulb", "brightness": 90}),
    ]
    assert ha.refusals == 0


async def test_an_entity_unpowered_before_the_case_is_left_alone(tmp_path):
    ha = FakeHA({"light.bulb": {"state": "on"}, "switch.plug": {"state": "off"}})
    text = header("switch_plug") + "      - set: {state: on}\n"
    await run_one(ha, suite(tmp_path, text, "zha"), powered_inventory(), admin=ha)
    assert ha.calls[-1] == ("switch", "turn_off", {"entity_id": "switch.plug"})
    assert not [call for call in ha.calls if call[0] == "light"]


async def test_an_entity_that_never_rejoins_is_logged_after_the_deadline(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(engine, "POWER_SETTLE_S", 0)
    monkeypatch.setattr(engine, "POWER_REJOIN_S", 0.02)
    monkeypatch.setattr(engine, "POWER_RETRY_S", 0.01)

    class Gone(FakeHA):
        async def call_service(self, domain, service, data=None, return_response=False):
            if domain == "light":
                raise OSError("no route")
            return await super().call_service(domain, service, data, return_response)

    ha = Gone({"light.bulb": {"state": "on"}, "switch.plug": {"state": "on"}})
    text = header("switch_plug") + "      - set: {state: off}\n"
    result = await run_one(ha, suite(tmp_path, text, "zha"), powered_inventory(), admin=ha)
    assert outcomes(result)["t[switch_plug]"][0] is Outcome.PASS
    assert "Could not restore light.bulb after power returned: no route" in caplog.text
