"""The rig engine against a fake HAClient: a state machine plus scripted device_side responses. No HA, no rig."""

import asyncio
import contextlib
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.device_side.core.registry import AdapterRegistry
from tests.rig import engine
from tests.rig.bridge import BridgeError
from tests.rig.client import HAError
from tests.rig.engine import (
    CaseResult,
    Outcome,
    RunResult,
    Suite,
    SuiteResult,
    load_step_file,
    render_record,
    rig_facts,
    run,
    table,
    write_records,
    write_report,
)
from tests.rig.inventory import Inventory, RigEntity
from tests.rig.journal import Journal
from tests.scripts.rig_fakes import (
    OPTION_REGISTRY,
    PENDING,
    RESTORED_MIDWAY,
    WAITING_MIDWAY,
    FakeAdmin,
    FakeHA,
    inventory,
)

TOL = 0.2
TOLERANCE = {"shelly": TOL, "zha": TOL, "zigbee2mqtt": TOL, "hue": TOL, "fake": TOL}
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
def _no_settle(monkeypatch):
    monkeypatch.setattr(engine, "SETUP_SETTLE_S", 0)


@pytest.fixture(autouse=True)
async def _cancel_pending():
    """Device timers and ramps outlive the run that started them; HA's test plugin fails on lingering ones."""
    yield
    for pending in PENDING:
        pending.cancel()
    await asyncio.gather(*(task for task in PENDING if isinstance(task, asyncio.Task)), return_exceptions=True)
    PENDING.clear()


def timer_on(ha: FakeHA, action: str, data: dict) -> dict:
    """turn_on_for as a device with a working timer: on now, off after the duration."""
    entity_id = data["entity_id"]
    ha.set(entity_id, "on")
    ha.later(data["duration"]["seconds"], entity_id, "off")
    return {entity_id: {"status": "confirmed", "integration": "shelly"}}


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
    assert not result.failed


def stuck(ha, action, data):
    """A device whose timer never fires."""
    ha.set(data["entity_id"], "on")
    return {data["entity_id"]: {"status": "confirmed", "integration": "shelly"}}


async def test_a_device_that_never_turns_off_fails_on_the_timeout(tmp_path):
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
      - expect_error: {key: targets_failed, summary: timeout}
      - expect_state: {state: unchanged}
"""


def refuse(detail: str) -> Callable:
    def _respond(ha, action, data):
        summary = f"{data['entity_id']}: {detail}"
        raise HAError({"translation_key": "targets_failed", "translation_placeholders": {"summary": summary}})

    return _respond


async def test_a_refusal_passes_when_key_summary_and_state_match(tmp_path):
    ha = FakeHA({"light.lamp": {"state": "on"}}, refuse("timeout"))
    result = await run_one(ha, suite(tmp_path, REFUSAL), inventory(light_wrapped="light.lamp"))
    assert outcomes(result) == {"refuses[light_wrapped]": (Outcome.PASS, "")}


async def test_an_expect_error_mismatch_fails_naming_both_summaries(tmp_path):
    ha = FakeHA({"light.lamp": {}}, refuse("error"))
    result = await run_one(ha, suite(tmp_path, REFUSAL), inventory(light_wrapped="light.lamp"))
    outcome, detail = outcomes(result)["refuses[light_wrapped]"]
    assert outcome is Outcome.FAIL
    assert detail == ("step 2 (expect_error): error summary is 'light.lamp: error', expected 'light.lamp: timeout'")


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


@pytest.mark.parametrize(("brightness", "outcome"), [(40.0, Outcome.PASS), (60.0, Outcome.FAIL)])
async def test_a_query_response_is_checked_without_a_status(tmp_path, brightness, outcome):
    def device_side(ha, action, data):
        return {data["entity_id"]: {"brightness": brightness}}

    ha = FakeHA({"light.lamp": {"state": "on"}}, device_side)
    text = """
action: get_attributes
rig_seconds: 5
tests:
  - name: reads
    roles: [light_ct]
    steps:
      - call: {}
      - expect_response: {attributes: {brightness: {min: 39, max: 41}}}
"""
    result = await run_one(ha, suite(tmp_path, text, "hue"), inventory("hue", light_ct="light.lamp"))

    assert outcomes(result)["reads[light_ct]"][0] is outcome


@pytest.mark.parametrize(
    ("row", "outcome"),
    [
        ({"timer": {"turns": "off", "remaining_s": 18.0}}, Outcome.PASS),
        ({"timer": {"turns": "on", "remaining_s": 18.0}}, Outcome.FAIL),
        ({"timer": {"turns": "off", "remaining_s": 10.0}}, Outcome.FAIL),
        ({}, Outcome.FAIL),  # no timer: each dotted name reads as absent
    ],
)
async def test_a_dotted_name_reads_a_nested_response_key(tmp_path, row, outcome):
    ha = FakeHA({"switch.plug": {"state": "on"}}, lambda ha, action, data: {data["entity_id"]: row})
    text = """
action: get_attributes
rig_seconds: 5
tests:
  - name: reads
    roles: [switch_plug]
    steps:
      - call: {}
      - expect_response: {attributes: {timer.turns: "off", timer.remaining_s: {min: 15, max: 20}}}
"""
    result = await run_one(ha, suite(tmp_path, text, "shelly"), inventory("shelly", switch_plug="switch.plug"))

    assert outcomes(result)["reads[switch_plug]"][0] is outcome


@pytest.mark.parametrize(
    ("row", "outcome"),
    [
        ({"hs_color": [30.2, 80.0]}, Outcome.PASS),
        ({"hs_color": [90.0, 80.0]}, Outcome.FAIL),
        ({"hs_color": [30.2]}, Outcome.FAIL),  # past the end reads as absent
        ({"hs_color": 30.2}, Outcome.FAIL),
    ],
)
async def test_a_numeric_part_indexes_a_list(tmp_path, row, outcome):
    ha = FakeHA({"light.lamp": {"state": "off"}}, lambda ha, action, data: {data["entity_id"]: row})
    text = """
action: get_attributes
rig_seconds: 5
tests:
  - name: reads
    roles: [light_color]
    steps:
      - call: {}
      - expect_response: {attributes: {hs_color.0: {min: 25, max: 35}, hs_color.1: {min: 70, max: 90}}}
"""
    result = await run_one(ha, suite(tmp_path, text, "hue"), inventory("hue", light_color="light.lamp"))

    assert outcomes(result)["reads[light_color]"][0] is outcome


@pytest.mark.parametrize(("row", "outcome"), [({}, Outcome.PASS), ({"timer": {"turns": "off"}}, Outcome.FAIL)])
async def test_a_null_expectation_asserts_the_key_is_absent(tmp_path, row, outcome):
    ha = FakeHA({"switch.plug": {"state": "off"}}, lambda ha, action, data: {data["entity_id"]: row})
    text = """
action: get_attributes
rig_seconds: 5
tests:
  - name: reads
    roles: [switch_plug]
    steps:
      - call: {}
      - expect_response: {attributes: {timer: null}}
"""
    result = await run_one(ha, suite(tmp_path, text, "shelly"), inventory("shelly", switch_plug="switch.plug"))

    assert outcomes(result)["reads[switch_plug]"][0] is outcome


async def test_an_off_light_gets_its_device_side_attributes_back(tmp_path):
    def device_side(ha, action, data):
        entity_id = data["entity_id"]
        if action == "get_attributes":
            attributes = {"brightness": 40, "color_temp_kelvin": 2700, "xy_color": [0.46, 0.41]}
            return {entity_id: attributes}
        return {entity_id: {"status": "sent", "integration": "hue"}}

    ha = FakeHA({"light.lamp": {}, "light.room": {"attributes": {"entity_id": ["light.lamp"]}}}, device_side)
    text = """
action: set_attributes
rig_seconds: 5
tests:
  - name: brightens_while_off
    roles: [group]
    steps:
      - call: {brightness: 80}
"""
    result = await run_one(ha, suite(tmp_path, text, "hue"), inventory("hue", group="light.room"))

    assert outcomes(result) == {"brightens_while_off[group]": (Outcome.PASS, "")}
    # Read for the member only: the room's own row averages its lights, and the member is restored itself.
    assert [call for call in ha.calls if call[1] == "get_attributes"] == [
        ("device_side", "get_attributes", {"entity_id": "light.lamp"})
    ]
    assert ha.calls[-2:] == [
        ("light", "turn_off", {"entity_id": "light.lamp"}),
        ("device_side", "set_attributes", {"entity_id": "light.lamp", "brightness": 40, "color_temp_kelvin": 2700}),
    ]


OBSERVED = """
action: turn_on_for
rig_seconds: 5
tests:
  - name: on_then_off
    roles: [switch_plug]
    setup:
      - set: {state: off}
    steps:
      - call: {duration: 0.6}
      - expect_response: {status: expected, integration: self}
      - expect_state: {state: on, within: tol}
      - wait: duration - tol
      - expect_state: {state: off, within: 2 * tol}
    observe: {see: It clicks on then off., watch: Two clicks., ask: 'Did it click twice?'}
"""
AUTOMATED, WATCHED = "on_then_off[switch_plug]", "on_then_off[switch_plug] observed"


def answers(*replies: str) -> tuple[list[str], Callable[[str], str]]:
    """The prompts asked, and an `ask` that gives `replies` in turn, then EOF."""
    asked, queue = [], list(replies)

    def ask(prompt):
        asked.append(prompt)
        if not queue:
            raise EOFError
        return queue.pop(0)

    return asked, ask


def in_turn(*responders: Callable) -> Callable:
    """The nth device_side call answered by the nth responder: the automated case's first, then the observed one's."""
    responders_left = iter(responders)
    return lambda ha, action, data: next(responders_left)(ha, action, data)


async def test_unattended_reports_observed_cases_not_observed_and_proves_nothing(tmp_path):
    ha, printed = FakeHA({"switch.plug": {}}, timer_on), []
    inv = inventory(switch_plug="switch.plug")
    result = await run(
        [suite(tmp_path, OBSERVED)], inv, REGISTRY, ha, tolerance=TOLERANCE, out=printed.append, ask=None
    )
    assert outcomes(result) == {AUTOMATED: (Outcome.PASS, ""), WATCHED: (Outcome.NOT_OBSERVED, "")}
    assert len([call for call in ha.calls if call[0] == "device_side"]) == 1
    assert not [line for line in printed if line.startswith(("---", "You'll")) or "need" in line]
    assert result.suites[0].proven == []
    assert not result.suites[0].recordable
    record = render_record(result.suites[0], "Shelly", "2026.10.1", [], "2026-10-25", "test")
    assert "| `on_then_off[switch_plug] observed` | `switch` (switch_plug) | not observed |" in record


@pytest.mark.parametrize(("answer", "outcome"), [("", Outcome.PASS), (" Y", Outcome.PASS), ("n", Outcome.FAIL)])
async def test_observed_asks_and_proves_only_when_both_cases_pass(tmp_path, answer, outcome):
    asked, ask = answers("", answer)
    ha = FakeHA({"switch.plug": {}}, timer_on)
    result = await run_one(ha, suite(tmp_path, OBSERVED), inventory(switch_plug="switch.plug"), ask=ask)
    assert asked[:2] == ["Press Enter to start... ", "    Did it click twice? [Y/n] "]
    assert outcomes(result)[WATCHED][0] is outcome
    assert [case.id for case in result.suites[0].proven] == ([AUTOMATED, WATCHED] if outcome is Outcome.PASS else [])


@pytest.mark.parametrize(("saw", "detail"), [("Red, then  blue ", "; saw: Red, then  blue"), ("", "")])
async def test_a_no_records_what_the_person_saw(tmp_path, saw, detail):
    asked, ask = answers("", "n", saw)
    ha = FakeHA({"switch.plug": {}}, timer_on)
    result = await run_one(ha, suite(tmp_path, OBSERVED), inventory(switch_plug="switch.plug"), ask=ask)
    assert asked[-1] == "    What did you see? (Enter to skip) "
    assert outcomes(result)[WATCHED] == (Outcome.FAIL, "not seen: Did it click twice?" + detail)


async def test_eof_at_what_was_seen_still_fails_the_case(tmp_path):
    _, ask = answers("", "n")
    result = await run_one(
        FakeHA({"switch.plug": {}}, timer_on), suite(tmp_path, OBSERVED), inventory(switch_plug="switch.plug"), ask=ask
    )
    assert outcomes(result)[WATCHED] == (Outcome.FAIL, "not seen: Did it click twice?")


async def test_a_report_lists_every_suite_with_its_reasons(tmp_path):
    ha = FakeHA({"switch.plug": {}}, stuck)
    result = await run_one(ha, suite(tmp_path, OBSERVED), inventory(switch_plug="switch.plug"), ask=answers()[1])
    path = write_report(result, tmp_path / "reports", "rig run 2026-10-26 14:03:05")
    assert path == tmp_path / "reports" / "rig-run-2026-10-26-140305.md"
    text = path.read_text()
    assert text.startswith("# rig run 2026-10-26 14:03:05\n\n## shelly / turn_on_for\n")
    assert "| fail: step 5 (expect_state): switch.plug: expected {'state': 'off'}" in text
    assert "| skipped: automated case failed |" in text


async def test_an_answer_other_than_yes_or_no_is_asked_again(tmp_path):
    asked, ask = answers("", "maybe", "n")
    ha, printed = FakeHA({"switch.plug": {}}, timer_on), []
    inv = inventory(switch_plug="switch.plug")
    result = await run([suite(tmp_path, OBSERVED)], inv, REGISTRY, ha, tolerance=TOLERANCE, out=printed.append, ask=ask)
    assert asked[1:3] == ["    Did it click twice? [Y/n] "] * 2
    assert "    Answer y or n." in printed
    assert outcomes(result)[WATCHED] == (Outcome.FAIL, "not seen: Did it click twice?")


async def test_setup_runs_before_the_brief_and_the_steps_after_enter(tmp_path):
    ha, printed, calls_at_enter = FakeHA({"switch.plug": {}}, timer_on), [], []

    def ask(prompt):
        calls_at_enter.append(len(ha.calls))
        return "y"

    inv = inventory(switch_plug="switch.plug")
    await run([suite(tmp_path, OBSERVED)], inv, REGISTRY, ha, tolerance=TOLERANCE, out=printed.append, ask=ask)
    start = printed.index("1 test needs you")
    assert printed[start + 1 : start + 5] == [
        "",
        "--- turn_on_for / on_then_off on switch_plug (1 of 1) ---",
        "Lights: switch.plug",
        "You'll see: \033[1mIt clicks on then off.\033[0m",
    ]
    enter = calls_at_enter[0]
    assert ha.calls[enter - 1] == ("switch", "turn_off", {"entity_id": "switch.plug"})
    assert ha.calls[enter][:2] == ("device_side", "turn_on_for")


async def test_an_observed_case_relaxes_its_checks(tmp_path):
    def flat(ha, action, data):
        for pending in PENDING:  # the automated run's ramp
            pending.cancel()
        ha.set(data["entity_id"], "on", brightness=100)
        return {data["entity_id"]: {"status": "sent"}}

    text = """
action: turn_on_for
rig_seconds: 5
tests:
  - name: ramps
    roles: [light_dimmable]
    setup:
      - set: {state: off}
    steps:
      - call: {duration: 6}
      - expect_response: {status: expected}
      - sample: {attribute: brightness, for: 0.2, every: 0.05, expect: rising}
      - expect_state: {brightness: {min: 105}}
      - expect_state: {brightness: {min: 110}, within: tol}
    observe: {see: s, watch: w, ask: 'ok?'}
"""
    # The observed run's call gets a sent status and a flat brightness: every check would fail.
    ha, (asked, ask), prompted = FakeHA({"light.lamp": {}}, in_turn(ramp(5), flat)), answers("", "y"), []
    loop = asyncio.get_running_loop()

    def timed(prompt):
        prompted.append(loop.time())
        return ask(prompt)

    result = await run_one(ha, suite(tmp_path, text), inventory(light_dimmable="light.lamp"), ask=timed)
    assert outcomes(result) == {
        "ramps[light_dimmable]": (Outcome.PASS, ""),
        "ramps[light_dimmable] observed": (Outcome.PASS, ""),
    }
    assert asked[-1] == "    ok? [Y/n] "
    # The sample still takes its 0.2 s, and the expect_state that never holds its whole `within`.
    assert prompted[1] - prompted[0] >= 0.2 + TOL


async def test_a_failed_automated_case_skips_its_observed_twin(tmp_path):
    ha, printed = FakeHA({"switch.plug": {}}, stuck), []
    asked, ask = answers()
    inv = inventory(switch_plug="switch.plug")
    result = await run([suite(tmp_path, OBSERVED)], inv, REGISTRY, ha, tolerance=TOLERANCE, out=printed.append, ask=ask)
    assert outcomes(result)[WATCHED] == (Outcome.SKIPPED, "automated case failed")
    assert asked == []
    assert not [line for line in printed if "need" in line]
    assert table(result.suites[0])[-1] == "| `on_then_off[switch_plug] observed` | `switch` (switch_plug) | skipped |"


async def test_a_call_that_raises_after_enter_says_there_is_nothing_to_observe(tmp_path):
    ha, printed = FakeHA({"switch.plug": {}}, in_turn(timer_on, refuse("device_offline"))), []
    asked, ask = answers("", "")
    inv = inventory(switch_plug="switch.plug")
    result = await run([suite(tmp_path, OBSERVED)], inv, REGISTRY, ha, tolerance=TOLERANCE, out=printed.append, ask=ask)
    assert asked == ["Press Enter to start... ", "Press Enter to go on... "]
    outcome, detail = outcomes(result)[WATCHED]
    assert outcome is Outcome.FAIL
    assert detail.startswith("step 1 (call): device_side.turn_on_for raised targets_failed")
    assert f"    nothing to observe: {detail}" in printed


TWO_SUITES = OBSERVED.replace("integration: self", "integration: shelly")


async def test_every_automated_case_runs_before_the_first_brief(tmp_path):
    ha, printed = FakeHA({"switch.plug": {}, "switch.other": {}}, timer_on), []
    inv = Inventory(
        {
            "shelly": [RigEntity("switch.plug", frozenset({"switch_plug"}))],
            "zha": [RigEntity("switch.other", frozenset({"switch_plug"}))],
        }
    )
    steps = suite(tmp_path, TWO_SUITES)
    suites = [steps, Suite(steps.file, "zha")]
    await run(suites, inv, REGISTRY, ha, admin=ha, tolerance=TOLERANCE, out=printed.append, ask=lambda _: "y")
    automated = [index for index, line in enumerate(printed) if line == f"  {AUTOMATED}: pass"]
    briefs = [index for index, line in enumerate(printed) if line.startswith("---")]
    assert len(automated) == 2
    assert max(automated) < printed.index("2 tests need you") < min(briefs)
    assert [printed[index] for index in briefs] == [
        "--- turn_on_for / on_then_off on switch_plug (1 of 2) ---",
        "--- turn_on_for / on_then_off on switch_plug (2 of 2) ---",
    ]


ONLY = """
action: turn_on_for
rig_seconds: 5
tests:
  - name: everywhere
    roles: [switch_plug]
    setup: [{wait: 0}]
    steps: [{wait: 0}]
    observe: {see: s, watch: w, ask: 'ok?'}
  - name: elsewhere
    roles: [switch_plug]
    only: [zha]
    setup: [{wait: 0}]
    steps: [{wait: 0}]
    observe: {see: s, watch: w, ask: 'ok?'}
  - name: needs_a_dimmer
    roles: [light_dimmable]
    setup: [{wait: 0}]
    steps: [{wait: 0}]
    observe: {see: s, watch: w, ask: 'ok?'}
"""


async def test_eof_at_a_brief_leaves_it_and_every_later_one_not_observed(tmp_path):
    asked, ask = answers()
    text = ONLY.replace("needs_a_dimmer", "again").replace("light_dimmable", "switch_plug")
    result = await run_one(
        FakeHA({"switch.plug": {}}), suite(tmp_path, text), inventory(switch_plug="switch.plug"), ask=ask
    )
    assert asked == ["Press Enter to start... "]
    assert outcomes(result) == {
        "everywhere[switch_plug] observed": (Outcome.NOT_OBSERVED, ""),
        "again[switch_plug] observed": (Outcome.NOT_OBSERVED, ""),
    }


async def test_a_setup_failure_fails_before_the_brief(tmp_path):
    asked, ask = answers()
    text = ONLY.split("  - name: elsewhere")[0].replace("setup: [{wait: 0}]", "setup: [{expect_state: {state: on}}]")
    result = await run_one(
        FakeHA({"switch.plug": {}}), suite(tmp_path, text), inventory(switch_plug="switch.plug"), ask=ask
    )
    outcome, detail = outcomes(result)["everywhere[switch_plug] observed"]
    assert (outcome, detail.split(":")[0]) == (Outcome.FAIL, "setup step 1 (expect_state)")
    assert asked == []


async def test_do_waits_for_enter_before_the_brief(tmp_path):
    asked, ask = answers("", "", "y")
    text = ONLY.split("  - name: elsewhere")[0].replace("setup: [{wait: 0}]", "setup: [{do: Flip it.}]")
    result = await run_one(
        FakeHA({"switch.plug": {}}), suite(tmp_path, text), inventory(switch_plug="switch.plug"), ask=ask
    )
    assert asked == ["    Flip it. Press Enter when done... ", "Press Enter to start... ", "    ok? [Y/n] "]
    assert outcomes(result) == {"everywhere[switch_plug] observed": (Outcome.PASS, "")}


async def test_eof_at_do_leaves_the_case_not_observed(tmp_path):
    asked, ask = answers()
    text = ONLY.split("  - name: elsewhere")[0].replace("setup: [{wait: 0}]", "setup: [{do: Flip it.}]")
    result = await run_one(
        FakeHA({"switch.plug": {}}), suite(tmp_path, text), inventory(switch_plug="switch.plug"), ask=ask
    )
    assert asked == ["    Flip it. Press Enter when done... "]
    assert outcomes(result) == {"everywhere[switch_plug] observed": (Outcome.NOT_OBSERVED, "")}


async def test_eof_at_the_question_leaves_the_case_not_observed(tmp_path):
    asked, ask = answers("")
    text = ONLY.split("  - name: elsewhere")[0]
    result = await run_one(
        FakeHA({"switch.plug": {}}), suite(tmp_path, text), inventory(switch_plug="switch.plug"), ask=ask
    )
    assert asked == ["Press Enter to start... ", "    ok? [Y/n] "]
    assert outcomes(result) == {"everywhere[switch_plug] observed": (Outcome.NOT_OBSERVED, "")}


async def test_an_observed_case_relaxes_expect_error(tmp_path):
    text = """
action: turn_on_for
rig_seconds: 5
tests:
  - name: refuses
    roles: [light_wrapped]
    setup: [{wait: 0}]
    steps:
      - call: {duration: 6}
      - expect_error: {key: targets_failed, summary: timeout}
    observe: {see: s, watch: w, ask: 'ok?'}
"""
    # The observed run's refusal names another summary: the automated check would fail it.
    ha = FakeHA({"light.lamp": {}}, in_turn(refuse("timeout"), refuse("error")))
    result = await run_one(ha, suite(tmp_path, text), inventory(light_wrapped="light.lamp"), ask=answers("", "y")[1])
    assert outcomes(result) == {
        "refuses[light_wrapped]": (Outcome.PASS, ""),
        "refuses[light_wrapped] observed": (Outcome.PASS, ""),
    }


async def test_only_and_missing_roles_narrow_the_cases(tmp_path):
    ha = FakeHA({"switch.plug": {}})
    result = await run_one(ha, suite(tmp_path, ONLY), inventory(switch_plug="switch.plug"), ask=lambda _: "y")
    assert outcomes(result) == {
        "everywhere[switch_plug] observed": (Outcome.PASS, ""),
        "needs_a_dimmer[light_dimmable] observed": (Outcome.SKIPPED, "no light_dimmable entity in inventory"),
    }


async def test_a_keyword_runs_a_subset_and_marks_the_suite_partial(tmp_path):
    ha = FakeHA({"switch.plug": {}})
    inv = inventory(switch_plug="switch.plug")
    result = await run_one(ha, suite(tmp_path, ONLY), inv, ask=lambda _: "y", keyword="everywhere")
    assert list(outcomes(result)) == ["everywhere[switch_plug] observed"]
    assert not result.suites[0].recordable


async def test_the_brief_counts_only_the_observed_cases_that_run(tmp_path):
    ha, printed = FakeHA({"switch.plug": {}}), []
    steps = suite(tmp_path, ONLY + ON_THEN_OFF.split("tests:\n")[1])
    inv = inventory(switch_plug="switch.plug")
    await run([steps], inv, REGISTRY, ha, tolerance=TOLERANCE, out=printed.append, ask=lambda _: "y")
    assert [line for line in printed if line.startswith("---")] == [
        "--- turn_on_for / everywhere on switch_plug (1 of 1) ---"
    ]


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
    adapter=lambda action, integration: SimpleNamespace(
        scope=SimpleNamespace(confirmable=False, capabilities=None, fields=frozenset(), options=frozenset())
    )
)


# Like Z2M: a turn_on_for adapter, and none for get_attributes or set_attributes.
NO_ATTRIBUTES_REGISTRY = SimpleNamespace(
    adapter=lambda action, integration: GROUP_REGISTRY.adapter(action, integration) if action == "turn_on_for" else None
)


async def test_a_group_checks_every_member(tmp_path):
    ha = group_ha(members_on("light.a", "light.b"))
    steps = suite(tmp_path, GROUP, "fake")
    result = await run_one(ha, steps, inventory("fake", group="light.room"), registry=GROUP_REGISTRY)
    assert outcomes(result) == {"every_member[group]": (Outcome.PASS, "")}


async def test_a_group_without_the_attribute_uses_inventory_members(tmp_path):
    ha = FakeHA({"light.room": {}, "light.a": {}, "light.b": {}}, members_on("light.a", "light.b"))
    steps = suite(tmp_path, GROUP, "fake")
    inv = Inventory({"fake": [RigEntity("light.room", frozenset({"group"}), members=("light.a", "light.b"))]})
    result = await run_one(ha, steps, inv, registry=NO_ATTRIBUTES_REGISTRY)
    assert outcomes(result) == {"every_member[group]": (Outcome.PASS, "")}
    assert ha.states["light.a"]["state"] == "off"  # restored: the inventory's members were snapshotted too


async def test_an_observed_group_brief_names_the_group_and_its_members(tmp_path):
    ha = FakeHA(
        {"light.room": {"attributes": {"friendly_name": "Room"}}, "light.a": {"attributes": {"friendly_name": "A"}}},
        members_on("light.a", "light.b"),
    )
    ha.states["light.b"] = {"entity_id": "light.b", "state": "off", "attributes": {}}  # no friendly name: its ID
    setup_first = "    setup:\n      - set: {state: off}\n    steps:\n"
    text = GROUP.replace("    steps:\n      - set: {state: off}\n", setup_first)
    text += "    observe: {see: Both turn on., watch: Both., ask: 'Both?'}\n"
    inv = Inventory({"fake": [RigEntity("light.room", frozenset({"group"}), members=("light.a", "light.b"))]})
    printed, (_, ask) = [], answers("", "y")
    steps = [suite(tmp_path, text, "fake")]
    await run(steps, inv, NO_ATTRIBUTES_REGISTRY, ha, tolerance=TOLERANCE, out=printed.append, ask=ask)
    assert "Lights: Room (A, light.b)" in printed


async def test_a_group_without_the_attribute_is_not_read_as_one_light(tmp_path):
    """With get_attributes, the group's members are read one by one, never the group as if it were a bulb."""
    ha = FakeHA({"light.room": {}, "light.a": {}, "light.b": {}}, lambda ha, action, data: {})
    steps = suite(tmp_path, GROUP.replace("      - expect_response: {status: sent, integration: self}\n", ""), "fake")
    inv = Inventory({"fake": [RigEntity("light.room", frozenset({"group"}), members=("light.a", "light.b"))]})
    await run_one(ha, steps, inv, registry=GROUP_REGISTRY)
    reads = [data["entity_id"] for domain, service, data in ha.calls if service == "get_attributes"]
    assert reads == ["light.a", "light.b"]


async def test_a_group_case_targeting_a_light_outside_the_group_is_skipped(tmp_path):
    text = GROUP + "      - set: {target: light_ct, state: on}\n"
    room = RigEntity("light.room", frozenset({"group"}), members=("light.a", "light.b"))
    inv = Inventory({"fake": [room, RigEntity("light.lamp", frozenset({"light_ct"}))]})
    result = await run_one(FakeHA({}, members_on()), suite(tmp_path, text, "fake"), inv, registry=GROUP_REGISTRY)
    assert outcomes(result) == {"every_member[group]": (Outcome.SKIPPED, "light_ct is not one of the group's members")}


async def test_a_group_color_is_a_group(tmp_path):
    """A group_color case checks the inventory's members and is never read as one light."""
    ha = FakeHA({"light.colors": {}, "light.a": {}, "light.b": {}}, members_on("light.a", "light.b"))
    text = GROUP.replace("roles: [group]", "roles: [group_color]")
    inv = Inventory({"fake": [RigEntity("light.colors", frozenset({"group_color"}), members=("light.a", "light.b"))]})
    result = await run_one(ha, suite(tmp_path, text, "fake"), inv, registry=NO_ATTRIBUTES_REGISTRY)
    assert outcomes(result) == {"every_member[group_color]": (Outcome.PASS, "")}
    assert ha.states["light.a"]["state"] == "off"  # restored: its members were snapshotted too


async def test_observe_roles_leave_the_other_roles_automated_only(tmp_path):
    text = OBSERVED.replace("roles: [switch_plug]", "roles: [switch_plug, light_onoff]").replace(
        "observe: {", "observe: {roles: [switch_plug], "
    )
    inv = inventory(switch_plug="switch.plug", light_onoff="light.relay")
    result = await run_one(
        FakeHA({"switch.plug": {}, "light.relay": {}}, timer_on), suite(tmp_path, text), inv, ask=None
    )
    assert set(outcomes(result)) == {AUTOMATED, WATCHED, "on_then_off[light_onoff]"}
    (relay,) = (case for case in result.suites[0].cases if case.role == "light_onoff")
    assert relay.twin is None


async def test_a_group_with_no_members_anywhere_fails(tmp_path):
    ha = FakeHA({"light.room": {}}, members_on())
    steps = suite(tmp_path, GROUP, "fake")
    result = await run_one(ha, steps, inventory("fake", group="light.room"), registry=GROUP_REGISTRY)
    outcome, detail = outcomes(result)["every_member[group]"]
    assert outcome is Outcome.FAIL
    assert "the inventory gives none" in detail


async def test_a_group_fails_on_a_lagging_member(tmp_path):
    ha = group_ha(members_on("light.a"))
    steps = suite(tmp_path, GROUP, "fake")
    result = await run_one(ha, steps, inventory("fake", group="light.room"), registry=GROUP_REGISTRY)
    outcome, detail = outcomes(result)["every_member[group]"]
    assert outcome is Outcome.FAIL
    assert detail.startswith("step 4 (expect_state): light.b: expected {'state': 'on'}")


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


@pytest.mark.parametrize(("settled", "failure"), [(101, ""), (102, "moved")])
async def test_a_steady_brightness_may_settle_one_step(tmp_path, settled, failure):
    # A Zigbee bulb can settle one level step after a stop.
    def respond(ha, action, data):
        async def _settle():
            await asyncio.sleep(0.1)
            ha.set(data["entity_id"], "on", brightness=settled)

        ha.set(data["entity_id"], "on", brightness=100)
        PENDING.append(asyncio.get_running_loop().create_task(_settle()))
        return {data["entity_id"]: {"status": "confirmed"}}

    steps = suite(tmp_path, SAMPLE.replace("EXPECT", "steady"))
    result = await run_one(FakeHA({"light.lamp": {}}, respond), steps, inventory(light_dimmable="light.lamp"))
    outcome, detail = outcomes(result)["ramps[light_dimmable]"]
    assert outcome is (Outcome.FAIL if failure else Outcome.PASS)
    assert failure in detail


@pytest.mark.parametrize(("settled", "failure"), [(40.2, ""), (39.8, "moved")])
async def test_a_steady_device_side_brightness_may_settle_one_rounded_step(tmp_path, settled, failure):
    # 103/254 and 102/254 of full read 40.6 % and 40.2 %, one step apart once rounded.
    text = SAMPLE.replace("EXPECT", "steady").replace("max: 200}", "source: device_side}")
    readings = iter([40.6])

    def respond(ha, action, data):
        if action == "get_attributes":
            return {data["entity_id"]: {"brightness": next(readings, settled)}}
        return {data["entity_id"]: {"status": "confirmed"}}

    ha = FakeHA({"light.lamp": {}}, respond)
    result = await run_one(ha, suite(tmp_path, text), inventory(light_dimmable="light.lamp"))
    outcome, detail = outcomes(result)["ramps[light_dimmable]"]
    assert outcome is (Outcome.FAIL if failure else Outcome.PASS)
    assert failure in detail


async def test_a_device_side_sample_reads_get_attributes_not_ha(tmp_path):
    text = SAMPLE.replace("EXPECT", "rising").replace("max: 200}", "max: 50, source: device_side}")
    predicted = iter(range(10, 100, 5))

    def respond(ha, action, data):
        ha.set(data["entity_id"], "on", brightness=255)  # HA shows the fade's end value at once
        if action == "get_attributes":
            return {data["entity_id"]: {"brightness": next(predicted)}}
        return {data["entity_id"]: {"status": "confirmed"}}

    ha = FakeHA({"light.lamp": {}}, respond)
    result = await run_one(ha, suite(tmp_path, text), inventory(light_dimmable="light.lamp"))
    assert outcomes(result) == {"ramps[light_dimmable]": (Outcome.PASS, "")}


async def test_a_sample_reads_a_dotted_attribute(tmp_path):
    text = SAMPLE.replace("EXPECT", "falling").replace("attribute: brightness", "attribute: hs_color.1")
    text = text.replace("max: 200}", "max: 100, source: device_side}")
    saturation = iter(range(90, 0, -5))

    def respond(ha, action, data):
        if action == "get_attributes":
            return {data["entity_id"]: {"hs_color": [200, next(saturation)]}}
        return {data["entity_id"]: {"status": "confirmed"}}

    ha = FakeHA({"light.lamp": {}}, respond)
    result = await run_one(ha, suite(tmp_path, text), inventory(light_dimmable="light.lamp"))
    assert outcomes(result) == {"ramps[light_dimmable]": (Outcome.PASS, "")}


MATCHES_READ = """
action: turn_on_for
rig_seconds: 5
tests:
  - name: matches
    roles: [light_dimmable]
    steps:
      - call: {duration: 6}
      - expect_matches_read: {attributes: [xy_color.0, xy_color.1], tolerance: 0.01, within: WITHIN}
"""


@pytest.mark.parametrize(
    ("read_x", "within", "failure"),
    [
        (0.305, 0, ""),
        (0.35, 0, "light.lamp: HA shows {'xy_color.0': 0.3, 'xy_color.1': 0.4}, a live read gives"),
        (0.35, 0.6, ""),  # HA catches up within the window
    ],
)
async def test_expect_matches_read_compares_ha_with_a_live_read(tmp_path, read_x, within, failure):
    def respond(ha, action, data):
        if action == "get_attributes":
            reads.append(None)
            return {data["entity_id"]: {"xy_color": [read_x if len(reads) == 1 else 0.3, 0.4]}}
        ha.set(data["entity_id"], "on", xy_color=[0.3, 0.4])
        return {data["entity_id"]: {"status": "confirmed"}}

    reads: list = []
    ha = FakeHA({"light.lamp": {}}, respond)
    steps = suite(tmp_path, MATCHES_READ.replace("WITHIN", str(within)))
    result = await run_one(ha, steps, inventory(light_dimmable="light.lamp"))
    outcome, detail = outcomes(result)["matches[light_dimmable]"]
    assert outcome is (Outcome.FAIL if failure else Outcome.PASS)
    assert failure in detail


def test_expect_matches_read_needs_attributes(tmp_path):
    text = MATCHES_READ.replace("attributes: [xy_color.0, xy_color.1]", "attributes: []")
    with pytest.raises(ValueError, match="attributes must be a non-empty list"):
        suite(tmp_path, text.replace("WITHIN", "0"))


RAISES = """
action: raise_brightness
rig_seconds: 5
tests:
  - name: raises_the_room
    roles: [group]
    steps:
      - call: {sweep_time: 0.2}
  - name: raises_a_member
    roles: [light_ct]
    steps:
      - call: {}
"""


@pytest.mark.parametrize(("settle", "gap"), [({"fake": 0.3}, (0.45, 1.0)), ({}, (0.0, 0.1))])
async def test_a_case_waits_out_the_predictions_a_raise_left_on_its_lights(tmp_path, settle, gap):
    called_at = []

    def respond(ha, action, data):
        if action == "raise_brightness":  # the snapshot reads get_attributes too
            called_at.append(asyncio.get_running_loop().time())
        return {data["entity_id"]: {"status": "sent", "integration": "fake"}}

    result = await run(
        [suite(tmp_path, RAISES, "fake")],
        inventory("fake", group="light.room", light_ct="light.a"),
        GROUP_REGISTRY,
        group_ha(respond),
        tolerance=TOLERANCE,
        settle=settle,
        out=lambda _: None,
    )
    assert not result.failed
    assert gap[0] <= called_at[1] - called_at[0] < gap[1]


def test_the_default_sweep_time_matches_the_ramp_actions():
    from custom_components.device_side.actions.ramp import DEFAULT_SWEEP_TIME

    assert engine.SWEEP_TIME_S == DEFAULT_SWEEP_TIME


def test_the_engine_knows_every_raise_and_lower_action():
    # Their cases wait out the predictions the calls leave behind.
    from custom_components.device_side.actions import discover
    from custom_components.device_side.actions.ramp import Ramp

    assert {action.key for action in discover() if issubclass(action, Ramp)} == engine._RAMPS


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
    failed = RunResult([SuiteResult(steps, [], complete=True)])
    assert await write_records(failed, ha, REGISTRY, tmp_path / "bench", "2026-10-25", "test") == []

    [path] = await write_records(passed, ha, REGISTRY, tmp_path / "bench", "2026-10-25", "rig run")
    assert path == tmp_path / "bench" / "shelly" / "turn_on_for.md"
    record = path.read_text()
    assert record.startswith("# Shelly · turn_on_for\n")
    assert "| Device | Mini (`S3`), firmware `2.0` |" in record
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


async def test_set_waits_for_every_member_to_reach_the_brightness(tmp_path):
    ha = FakeHA(
        {
            "light.room": {"state": "on", "attributes": {"entity_id": ["light.a"], "brightness": 255}},
            "light.a": {"state": "on", "attributes": {"brightness": 255}},
        }
    )

    async def slow_member(domain, service, data=None, return_response=False):
        """The group reads the new brightness at once, its member only a moment later."""
        ha.calls.append((domain, service, dict(data or {})))
        ha.states["light.room"]["attributes"]["brightness"] = 51
        PENDING.append(asyncio.get_running_loop().call_later(0.05, lambda: ha.set("light.a", "on", brightness=51)))

    ha.call_service = slow_member
    text = header("group") + "      - set: {state: on, brightness_pct: 20}\n      - expect_state: {brightness: 51}\n"
    result = await run_one(ha, suite(tmp_path, text), inventory(group="light.room"))
    assert outcomes(result)["t[group]"] == (Outcome.PASS, "")


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


Z2M_COLOR = """
action: turn_on_for
rig_seconds: 5
tests:
  - name: color_then_off
    roles: [light_color]
    setup:
      - z2m_option: {hue_native_control: false}
    steps:
      - call: {duration: 0.6, rgb_color: [255, 0, 0]}
      - expect_z2m_option: {hue_native_control: true}
"""


class Z2MHA(FakeHA):
    """FakeHA with one Z2M device behind light.bulb and Z2M's device options, as Z2M's bridge holds them."""

    def __init__(self, respond: Callable):
        super().__init__({"light.bulb": {}}, respond)
        self.options: dict = {}

    async def command(self, payload: dict):
        if payload["type"] == "config/entity_registry/get":
            return {"entity_id": payload["entity_id"], "device_id": "d1"}
        if payload["type"] == "config/device_registry/list":
            return [{"id": "d1", "identifiers": [["mqtt", "zigbee2mqtt_0x0017880100000001"]]}]
        return await super().command(payload)

    async def set_z2m_device_options(self, ieee: str, options: dict) -> None:
        self.calls.append(("z2m", "options", {"id": ieee, **options}))
        self.options.update(options)

    async def z2m_device_options(self, ieee: str) -> dict:
        return dict(self.options)


def native_control(turns_it_on: bool) -> Callable:
    def respond(ha, action, data):
        if turns_it_on:
            ha.options["hue_native_control"] = True
        return timer_on(ha, action, data)

    return respond


async def test_z2m_option_steps_set_and_check_a_device_option(tmp_path):
    ha = Z2MHA(native_control(turns_it_on=True))
    steps = suite(tmp_path, Z2M_COLOR, "zigbee2mqtt")
    result = await run_one(ha, steps, inventory("zigbee2mqtt", light_color="light.bulb"), admin=ha)
    assert outcomes(result) == {"color_then_off[light_color]": (Outcome.PASS, "")}
    assert ("z2m", "options", {"id": "0x0017880100000001", "hue_native_control": False}) in ha.calls


async def test_expect_z2m_option_fails_when_the_option_stays_off(tmp_path):
    ha = Z2MHA(native_control(turns_it_on=False))
    steps = suite(tmp_path, Z2M_COLOR, "zigbee2mqtt")
    result = await run_one(ha, steps, inventory("zigbee2mqtt", light_color="light.bulb"), admin=ha)
    outcome, detail = outcomes(result)["color_then_off[light_color]"]
    assert outcome is Outcome.FAIL
    assert "Zigbee2MQTT option hue_native_control is False, expected True" in detail


async def test_z2m_option_steps_do_nothing_in_another_integrations_suite(tmp_path):
    # ZHA has get_attributes and set_attributes, so the snapshot reads the off light first; it stores nothing.
    def respond(ha, action, data):
        return {} if action == "get_attributes" else timer_on(ha, action, data)

    ha = FakeHA({"light.bulb": {}}, respond)
    result = await run_one(ha, suite(tmp_path, Z2M_COLOR, "zha"), inventory("zha", light_color="light.bulb"), admin=ha)
    assert outcomes(result) == {"color_then_off[light_color]": (Outcome.PASS, "")}


async def test_a_light_without_a_z2m_device_fails_the_step(tmp_path):
    ha = Z2MHA(timer_on)

    async def no_device(payload):
        return {"entity_id": "light.bulb", "device_id": None} if payload["type"] == "config/entity_registry/get" else []

    ha.command = no_device
    steps = suite(tmp_path, Z2M_COLOR, "zigbee2mqtt")
    result = await run_one(ha, steps, inventory("zigbee2mqtt", light_color="light.bulb"), admin=ha)
    assert "light.bulb has no Zigbee2MQTT device" in outcomes(result)["color_then_off[light_color]"][1]


@pytest.mark.parametrize("args", ["null", "{}", "{target: light_color}"])
def test_z2m_option_needs_an_option(tmp_path, args):
    text = Z2M_COLOR.replace("z2m_option: {hue_native_control: false}", f"z2m_option: {args}")
    with pytest.raises(ValueError, match="name an option"):
        suite(tmp_path, text, "zigbee2mqtt")


def option_file(options: str = "") -> str:
    lines = ["action: raise_brightness", "rig_seconds: 5"] + ([f"options: [{options}]"] if options else [])
    return "\n".join([*lines, "tests:", "  - name: t", "    roles: [light_ct]", "    steps:", "      - call: {}", ""])


def options_seen(admin: FakeAdmin) -> Callable:
    def respond(ha, action, data):
        if action == "raise_brightness":  # the snapshot reads get_attributes too
            seen.append(dict(admin.options))
        return {data["entity_id"]: {"status": "sent", "integration": "fake"}}

    seen: list[dict] = []
    respond.seen = seen
    return respond


async def test_each_suite_runs_with_its_options_and_the_rig_gets_its_own_back(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "OPTIONS_RELOAD_S", 0)
    admin = FakeAdmin({"light.a": {}})
    admin.respond = respond = options_seen(admin)
    (tmp_path / "plain").mkdir()
    (tmp_path / "on").mkdir()
    plain = suite(tmp_path / "plain", option_file(), "fake")
    on = suite(tmp_path / "on", option_file("opt"), "fake")

    result = await run(
        [plain, on],
        inventory("fake", light_ct="light.a"),
        OPTION_REGISTRY,
        admin,
        admin=admin,
        tolerance=TOLERANCE,
        out=lambda _: None,
    )

    assert not result.failed
    assert respond.seen == [{"opt": False, "other": False}, {"opt": True, "other": False}]
    assert admin.options == {"opt": True, "other": False}  # as the rig had them
    assert admin.saved == [{"opt": False, "other": False}, {"opt": True, "other": False}]
    assert [suite_result.suite.name for suite_result in result.suites] == ["raise_brightness", "raise_brightness-opt"]


async def test_options_already_in_force_are_not_saved(tmp_path, monkeypatch):
    # An entry whose options were never saved reloads on any save, so the engine cancels the flow instead.
    monkeypatch.setattr(engine, "OPTIONS_RELOAD_S", 0)
    admin = FakeAdmin({"light.a": {}})
    admin.respond = options_seen(admin)

    result = await run(
        [suite(tmp_path, option_file("opt"), "fake")],
        inventory("fake", light_ct="light.a"),
        OPTION_REGISTRY,
        admin,
        admin=admin,
        tolerance=TOLERANCE,
        out=lambda _: None,
    )

    assert not result.failed
    assert admin.saved == []
    assert admin.aborted == 1


async def test_the_journal_holds_each_change_before_it_is_made_and_is_gone_after_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "OPTIONS_RELOAD_S", 0)
    journal = Journal(tmp_path / "journal.json")
    admin = FakeAdmin({"light.a": {"state": "on", "attributes": {"brightness": 200}}})
    admin.respond = options_seen(admin)
    seen = []  # what the journal held as each change was sent
    rest, call_service = admin.rest, admin.call_service

    async def save(method, path, json=None):
        if method == "post" and not path.endswith("/options/flow"):
            seen.append(("save", journal.get("options")))
        return await rest(method, path, json)

    async def light(domain, service, data=None, return_response=False):
        if domain == "light":
            seen.append((service, list(journal.get("taken", {}))))
        return await call_service(domain, service, data, return_response)

    admin.rest, admin.call_service = save, light
    result = await run(
        [suite(tmp_path, RESTORED_MIDWAY, "fake")],
        inventory("fake", light_ct="light.a"),
        OPTION_REGISTRY,
        admin,
        admin=admin,
        tolerance=TOLERANCE,
        out=lambda _: None,
        journal=journal,
    )

    assert not result.failed
    original = {"opt": True, "other": False}
    assert seen == [
        ("save", original),
        ("turn_off", ["light.a"]),
        ("turn_on", ["light.a"]),  # the restore step: the case goes on, so the journal keeps the light
        ("turn_off", ["light.a"]),
        ("turn_on", ["light.a"]),
        ("save", original),
    ]
    assert admin.states["light.a"]["attributes"] == {"brightness": 200}
    assert not journal.path.exists()


async def test_a_run_cancelled_mid_case_puts_back_and_clears_its_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "OPTIONS_RELOAD_S", 0)
    journal = Journal(tmp_path / "journal.json")
    admin = FakeAdmin({"light.a": {"state": "on", "attributes": {"brightness": 200}}})
    admin.respond = options_seen(admin)
    task = asyncio.create_task(
        run(
            [suite(tmp_path, WAITING_MIDWAY, "fake")],
            inventory("fake", light_ct="light.a"),
            OPTION_REGISTRY,
            admin,
            admin=admin,
            tolerance=TOLERANCE,
            out=lambda _: None,
            journal=journal,
        )
    )
    while admin.states["light.a"]["state"] != "off":
        await asyncio.sleep(0.005)
    assert journal.path.exists()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert admin.states["light.a"] == {"entity_id": "light.a", "state": "on", "attributes": {"brightness": 200}}
    assert admin.options == {"opt": True, "other": False}
    assert not journal.path.exists()


async def test_a_save_the_flow_refuses_closes_the_flow_and_raises():
    admin = FakeAdmin({})

    async def refused(method: str, path: str, json: dict | None = None):
        if method == "post" and not path.endswith("/options/flow"):
            return {"type": "form", "errors": {"base": "unknown"}}
        return await FakeAdmin.rest(admin, method, path, json)

    admin.rest = refused
    with pytest.raises(RuntimeError, match="did not save"):
        await engine.EntryOptions(admin, reload_s=0).apply({"opt": False})
    assert admin.aborted == 1


async def test_a_suite_whose_adapter_has_options_needs_the_admin_token(tmp_path):
    out: list[str] = []
    result = await run(
        [suite(tmp_path, option_file(), "fake")],
        inventory("fake", light_ct="light.a"),
        OPTION_REGISTRY,
        FakeHA({"light.a": {}}),
        tolerance=TOLERANCE,
        out=out.append,
    )
    assert result.suites == []
    assert "fake / raise_brightness: needs HA_ADMIN_TOKEN, skipped" in out


async def test_an_option_outside_the_adapters_scope_is_a_schema_error(tmp_path):
    with pytest.raises(engine.SchemaError, match="has no option nope"):
        await run_one(
            FakeAdmin({"light.a": {}}),
            suite(tmp_path, option_file("nope"), "fake"),
            inventory("fake", light_ct="light.a"),
            registry=OPTION_REGISTRY,
            admin=None,
        )


async def test_an_option_file_skips_an_adapter_without_the_option(tmp_path):
    # raise_brightness-predicted_state.yaml is Hue's: Zigbee2MQTT's raise_brightness has no predicted_state.
    out: list[str] = []
    result = await run(
        [suite(tmp_path, option_file("predicted_state"), "zigbee2mqtt")],
        inventory("zigbee2mqtt", light_ct="light.a"),
        REGISTRY,
        FakeAdmin({"light.a": {}}),
        tolerance=TOLERANCE,
        out=out.append,
    )
    assert result.suites == []
    assert "zigbee2mqtt / raise_brightness: no options, steps.yaml skipped" in out


def test_a_step_file_lists_options_by_name(tmp_path):
    path = tmp_path / "steps.yaml"
    path.write_text(option_file().replace("rig_seconds: 5", "rig_seconds: 5\noptions: predicted_state"))
    with pytest.raises(engine.SchemaError, match="options must be a list"):
        load_step_file(path)


async def test_a_record_with_options_on_is_named_for_them(tmp_path):
    steps = suite(tmp_path, option_file("predicted_state"), "hue")
    case = CaseResult("t[light_ct]", "light_ct", "light", Outcome.PASS)
    result = RunResult([SuiteResult(steps, [case], complete=True)])

    [path] = await write_records(result, FakeHA({}), REGISTRY, tmp_path / "bench", "2026-10-27", "rig run")

    assert path == tmp_path / "bench" / "hue" / "raise_brightness-predicted_state.md"
    assert path.read_text().startswith("# Hue · raise_brightness-predicted_state\n")


# --- bridge ---------------------------------------------------------------------------------------------------

BRIDGE_STEPS = """
action: set_scene
rig_seconds: 5
tests:
  - name: other_actor
    roles: [light_dimmable]
    setup:
      - bridge: {put: {on: {on: true}}}
    steps:
      - bridge: {target: group, put: {dimming: {brightness: 40}}}
      - bridge: {target: scene, recall: true}
"""

UNIQUE_IDS = {"light.bulb": "light-id", "light.room": "grouped-id", "scene.dusk": "scene-id"}


class FakeBridge:
    def __init__(self, error: str | None = None):
        self.error = error
        self.puts: list[tuple[str, str, dict]] = []

    async def put(self, resource_type: str, resource_id: str, body: dict) -> None:
        self.puts.append((resource_type, resource_id, body))
        if self.error:
            raise BridgeError(self.error)


class BridgeHA(FakeHA):
    """FakeHA whose entity registry holds each entity's platform and unique_id."""

    def __init__(self, platform: str = "hue", unique_id: str | None = None):
        super().__init__({entity_id: {} for entity_id in UNIQUE_IDS}, lambda ha, action, data: {})
        self.states["light.room"]["attributes"]["entity_id"] = ["light.bulb"]
        self.platform, self.unique_id = platform, unique_id

    async def command(self, payload: dict):
        if payload["type"] != "config/entity_registry/get":
            return await super().command(payload)
        entity_id = payload["entity_id"]
        return {"platform": self.platform, "unique_id": self.unique_id or UNIQUE_IDS[entity_id]}


def bridge_inventory() -> Inventory:
    return inventory("hue", light_dimmable="light.bulb", group="light.room", scene="scene.dusk")


async def run_bridge(tmp_path, bridge, ha=None, text=BRIDGE_STEPS, integration="hue") -> dict:
    ha = ha or BridgeHA()
    steps = suite(tmp_path, text.replace("set_scene", "turn_on_for") if integration == "shelly" else text, integration)
    result = await run_one(
        ha,
        steps,
        bridge_inventory()
        if integration == "hue"
        else inventory(integration, light_dimmable="light.bulb", group="light.room", scene="scene.dusk"),
        bridge=bridge,
    )
    return outcomes(result)


async def test_a_bridge_step_writes_each_resource_type_to_its_unique_id(tmp_path):
    bridge = FakeBridge()
    assert await run_bridge(tmp_path, bridge) == {"other_actor[light_dimmable]": (Outcome.PASS, "")}
    assert bridge.puts == [
        ("light", "light-id", {"on": {"on": True}}),
        ("grouped_light", "grouped-id", {"dimming": {"brightness": 40}}),
        ("scene", "scene-id", {"recall": {"action": "active"}}),
    ]


async def test_a_failing_bridge_write_fails_the_case(tmp_path):
    results = await run_bridge(tmp_path, FakeBridge("PUT light/light-id got 403: unauthorized user"))
    outcome, detail = results["other_actor[light_dimmable]"]
    assert outcome is Outcome.FAIL
    assert "setup step 1 (bridge): PUT light/light-id got 403: unauthorized user" in detail


async def test_a_bridge_step_without_a_bridge_says_what_to_set(tmp_path):
    outcome, detail = (await run_bridge(tmp_path, None))["other_actor[light_dimmable]"]
    assert outcome is Outcome.FAIL
    assert "HUE_BRIDGE_HOST and HUE_APP_KEY" in detail


async def test_a_bridge_step_outside_a_hue_suite_fails(tmp_path):
    bridge = FakeBridge()
    outcome, detail = (await run_bridge(tmp_path, bridge, integration="shelly"))["other_actor[light_dimmable]"]
    assert outcome is Outcome.FAIL
    assert "bridge steps need a Hue suite, not shelly" in detail
    assert bridge.puts == []


async def test_a_bridge_step_on_another_platforms_entity_fails(tmp_path):
    bridge = FakeBridge()
    outcome, detail = (await run_bridge(tmp_path, bridge, BridgeHA(platform="mqtt")))["other_actor[light_dimmable]"]
    assert outcome is Outcome.FAIL
    assert "light.bulb is not a Hue entity" in detail
    assert bridge.puts == []


async def test_a_bridge_step_on_an_entity_without_a_unique_id_fails(tmp_path):
    class NoId(BridgeHA):
        async def command(self, payload: dict):
            return {"platform": "hue", "unique_id": None}

    outcome, detail = (await run_bridge(tmp_path, FakeBridge(), NoId()))["other_actor[light_dimmable]"]
    assert outcome is Outcome.FAIL
    assert "light.bulb has no unique_id" in detail


@pytest.mark.parametrize(
    ("step", "message"),
    [
        ("{target: scene, put: {on: {on: true}}}", "put needs a light or group target, not scene.dusk"),
        ("{recall: true}", "recall needs a scene target, not light.bulb"),
    ],
)
async def test_a_bridge_step_on_the_wrong_kind_of_target_fails(tmp_path, step, message):
    text = BRIDGE_STEPS.replace("{put: {on: {on: true}}}", step, 1)
    bridge = FakeBridge()
    outcome, detail = (await run_bridge(tmp_path, bridge, text=text))["other_actor[light_dimmable]"]
    assert outcome is Outcome.FAIL
    assert message in detail
    assert bridge.puts == []


async def test_an_observed_case_runs_a_bridge_step_as_it_is(tmp_path):
    text = """
action: set_scene
rig_seconds: 5
tests:
  - name: other_actor
    roles: [light_dimmable]
    setup:
      - set: {state: off}
    steps:
      - bridge: {put: {on: {on: true}}}
    observe: {see: s, watch: w, ask: a}
"""
    bridge = FakeBridge()
    ha = BridgeHA()
    _, ask = answers("", "y")
    steps = suite(tmp_path, text, "hue")
    result = await run_one(ha, steps, bridge_inventory(), bridge=bridge, ask=ask)
    assert outcomes(result)["other_actor[light_dimmable] observed"][0] is Outcome.PASS
    assert bridge.puts == [("light", "light-id", {"on": {"on": True}})]


def test_a_bridge_step_makes_its_target_role_needed(tmp_path):
    test = suite(tmp_path, BRIDGE_STEPS).file.tests[0]
    assert test.roles_needed("light_dimmable") == ["light_dimmable", "group", "scene"]
    assert suite(tmp_path, BRIDGE_STEPS).file.uses_bridge
    assert not suite(tmp_path, ON_THEN_OFF).file.uses_bridge


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ("null", "give put or recall"),
        ("{}", "give put or recall"),
        ("{put: {on: {on: true}}, recall: true}", "give put or recall"),
        ("{put: {}}", "put takes the body"),
        ("{put: on}", "put takes the body"),
        ("{recall: false}", "recall takes true"),
        ("{recall: true, state: on}", "unknown key"),
        ("{target: nowhere, recall: true}", "not an inventory role"),
    ],
)
def test_a_bad_bridge_step_does_not_parse(tmp_path, args, message):
    text = BRIDGE_STEPS.replace("bridge: {put: {on: {on: true}}}", f"bridge: {args}", 1)
    with pytest.raises(ValueError, match=message):
        suite(tmp_path, text)


def test_a_run_cancelled_at_a_prompt_exits_without_waiting_for_an_answer():
    # asyncio.run waits for its executor's threads at exit, and a thread blocked in input() never ends by itself.
    answered = threading.Event()

    def nobody_answers(_text: str) -> str:
        answered.wait(10)
        return ""

    async def cancelled_at_the_prompt():
        prompt = asyncio.create_task(engine._prompt(nobody_answers, "Press Enter to start... "))
        await asyncio.sleep(0.05)
        prompt.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await prompt

    started = time.monotonic()
    asyncio.run(cancelled_at_the_prompt())
    assert time.monotonic() - started < 2
    answered.set()
