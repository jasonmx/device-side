"""Step files parse, and a broken one fails at load naming the file, the test and the step."""

from pathlib import Path

import pytest

from custom_components.device_side.core.registry import AdapterRegistry
from tests.rig.engine import STEPS_DIR, Expr, Observe, SchemaError, load_step_file, load_step_files


@pytest.mark.parametrize("path", sorted(STEPS_DIR.rglob("*.yaml")), ids=lambda path: path.name)
def test_every_shipped_step_file_parses(path):
    assert load_step_file(path).tests


def test_load_step_files_skips_the_examples():
    actions = {step_file.action for step_file in load_step_files()}
    assert actions == {"get_attributes", "set_attributes", "set_scene", "turn_on_for", "turn_off_for"}
    assert actions <= set(AdapterRegistry.discover().actions)


def test_the_step_files_keep_their_roles():
    by_action = {step_file.action: step_file for step_file in load_step_files()}
    assert by_action["turn_on_for"].roles == (
        "switch_plug",
        "light_onoff",
        "light_wrapped",
        "light_dimmable",
        "light_ct",
        "light_color",
        "group",
    )
    assert by_action["turn_off_for"].roles == ("switch_plug", "light_onoff", "light_wrapped", "light_dimmable")


HEADER = "action: turn_on_for\nrig_seconds: 5\ntests:\n  - name: broken\n    roles: [switch_plug]\n    steps:\n"


def observed(observe: str = "{see: s, watch: w, ask: a}", setup: str = "[{wait: 0}]") -> str:
    """HEADER for an observed test, its steps to follow."""
    return HEADER.replace("    steps:\n", f"    setup: {setup}\n    observe: {observe}\n    steps:\n")


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
        (HEADER + "      - observe: ok?\n", "step 1 (observe): the observe step is gone; give the test observe:"),
        (
            HEADER.replace("    steps:\n", "    brief: {see: s, watch: w}\n    steps:\n") + "      - wait: 0\n",
            "test broken, brief is gone; give the test observe:",
        ),
        (observed("{see: s, watch: w}") + "      - wait: 0\n", "observe: missing ask"),
        (
            observed("{see: s, watch: w, ask: ''}") + "      - wait: 0\n",
            "observe: see, watch and ask must be non-empty",
        ),
        (observed("[a]") + "      - wait: 0\n", "observe: expected a mapping"),
        (observed(setup="[]") + "      - wait: 0\n", "setup must be a non-empty list"),
        (
            HEADER.replace("    steps:\n", "    observe: {see: s, watch: w, ask: a}\n    steps:\n")
            + "      - wait: 0\n",
            "a test with observe needs setup",
        ),
        (observed() + "      - do: Flip it.\n", "step 1 (do): do belongs in setup"),
        (
            HEADER.replace("    steps:\n", "    setup: [{do: Flip it.}]\n    steps:\n") + "      - wait: 0\n",
            "setup step 1 (do): do is only for a test with observe",
        ),
        (observed("{see: s, watch: w, ask: a}", "[{do: ''}]") + "      - wait: 0\n", "do takes the instruction"),
        (observed(setup="[{observe: x}]") + "      - wait: 0\n", "setup step 1 (observe): the observe step is gone"),
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


def test_an_observed_test_is_parsed_with_its_setup(tmp_path: Path):
    path = tmp_path / "observed.yaml"
    text = observed("{see: ' It clicks. ', watch: Twice., ask: 'Two?'}", "[{do: Flip it.}, {set: {state: off}}]")
    path.write_text(text + "      - call: {}\n      - expect_state: {state: on}\n")
    (test,) = load_step_file(path).tests
    assert test.observe == Observe("It clicks.", "Twice.", "Two?")
    assert [step.label for step in test.setup] == ["setup step 1 (do)", "setup step 2 (set)"]
    assert not test.automated  # its setup needs the person


@pytest.mark.parametrize(
    ("steps", "automated"),
    [("      - call: {}\n", False), ("      - call: {}\n      - sample: {attribute: b, for: 1}\n", True)],
)
def test_an_observed_test_is_automated_too_when_its_steps_check_something(tmp_path: Path, steps, automated):
    path = tmp_path / "observed.yaml"
    path.write_text(observed() + steps)
    assert load_step_file(path).tests[0].automated is automated
