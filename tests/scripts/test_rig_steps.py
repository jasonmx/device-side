"""Step files parse, and a broken one fails at load naming the file, the test and the step."""

from pathlib import Path

import pytest

from custom_components.device_side.core.registry import AdapterRegistry
from tests.rig.engine import STEPS_DIR, Expr, SchemaError, load_step_file, load_step_files


@pytest.mark.parametrize("path", sorted(STEPS_DIR.rglob("*.yaml")), ids=lambda path: path.name)
def test_every_shipped_step_file_parses(path):
    assert load_step_file(path).tests


def test_load_step_files_skips_the_examples():
    actions = {step_file.action for step_file in load_step_files()}
    assert actions == {"turn_on_for", "turn_off_for"}
    assert actions <= set(AdapterRegistry.discover().actions)


def test_the_shelly_tests_keep_their_roles():
    by_action = {step_file.action: step_file for step_file in load_step_files()}
    assert by_action["turn_on_for"].roles == ("switch_plug", "light_onoff", "light_wrapped")
    assert by_action["turn_off_for"].roles == ("switch_plug", "light_onoff", "light_wrapped", "light_dimmable")


HEADER = "action: turn_on_for\nrig_seconds: 5\ntests:\n  - name: broken\n    roles: [switch_plug]\n    steps:\n"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("- 1\n", "expected a mapping"),
        ("action: turn_on_for\nrig_seconds: 5\ntests: []\n", "tests must be a non-empty list"),
        ("action: turn_on_for\nrig_seconds: 0\ntests: [x]\n", "rig_seconds must be a positive whole number"),
        ("action: turn_on_for\nrig_seconds: 5\ntests: [x]\nextra: 1\n", "unknown key"),
        ("rig_seconds: 5\ntests: [x]\n", "action must name"),
        ("action: x\nrig_seconds: 5\ntests: [{roles: [switch_plug]}]\n", "a test needs a name"),
        (HEADER + "      - bogus: 1\n", "test broken, step 1 (bogus): unknown step"),
        (HEADER + "      - set: {state: on}\n        wait: 1\n", "step 1: expected one `kind: args` mapping"),
        (HEADER + "      - set: {state: dim}\n", "step 1 (set): state must be on or off"),
        (HEADER + "      - set: {}\n", "step 1 (set): missing state"),
        (HEADER + "      - call: {target: lamp}\n", "target 'lamp' is not an inventory role"),
        (HEADER + "      - call: {duration: forever}\n", "unknown name 'forever'"),
        (HEADER + "      - wait: duration / 2\n", "something other than numbers, names and + - *"),
        (HEADER + "      - wait: '1 +'\n", "cannot parse"),
        (HEADER + "      - wait: \"'a' + 1\"\n", "is not a number"),
        (HEADER + "      - wait: true\n", "expected a number or an expression"),
        (HEADER + "      - expect_error: {}\n", "name a key, a summary or both"),
        (HEADER + "      - expect_state: {}\n", "name a state or an attribute"),
        (HEADER + "      - expect_state: {brightness: {low: 1}}\n", "a range takes min and/or max"),
        (HEADER + "      - expect_state: {brightness: {min: a}}\n", "range bounds must be numbers"),
        (HEADER + "      - expect_response: {attributes: 3}\n", "attributes must be a mapping"),
        (HEADER + "      - sample: {attribute: brightness, for: 1, expect: wobbly}\n", "rising, falling or steady"),
        (HEADER + "      - observe: {question: x}\n", "observe takes the question"),
        (HEADER + "      - restore: 1\n", "restore takes no arguments"),
        (HEADER + "      - expect_response: 1\n", "expected a mapping"),
        (HEADER + "      - expect_response: {status: fine, colour: red}\n", "unknown key(s) colour"),
        (HEADER.replace("[switch_plug]", "[plug]") + "      - restore: null\n", "unknown role(s) plug"),
        (HEADER.replace("[switch_plug]", "[]") + "      - restore: null\n", "roles must be a non-empty list"),
        (HEADER.replace("    steps:\n", "    only: []\n    steps:\n") + "      - restore: null\n", "only must be"),
        (HEADER.replace("    steps:\n", "    steps: []\n"), "steps must be a non-empty list"),
        (HEADER.replace("    steps:\n", "    when: now\n    steps:\n") + "      - restore: null\n", "unknown key"),
        (HEADER + "      - restore: null\n" + HEADER.split("tests:\n")[1] + "      - restore: null\n", "duplicate"),
        ("action: [\n", "while parsing"),
    ],
)
def test_a_schema_error_names_where_it_is(tmp_path: Path, text, message):
    path = tmp_path / "broken.yaml"
    path.write_text(text)
    with pytest.raises(SchemaError, match=r"^broken\.yaml: ") as err:
        load_step_file(path)
    assert message in str(err.value)


@pytest.mark.parametrize(
    ("text", "value"), [("6", 6), ("duration - tol", 9.5), ("2 * tol", 1.0), ("-tol + duration", 9.5), (1.5, 1.5)]
)
def test_expressions_evaluate_against_the_run(text, value):
    assert Expr.parse(text).eval({"duration": 10, "tol": 0.5}) == value
