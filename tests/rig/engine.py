"""Runs the rig's YAML step files against the live HA and renders bench records from the results.

One file per action (`steps/<action>.yaml`) runs on every inventory integration that has that action's adapter; a
file with `options` (`steps/<action>-<option>.yaml`) runs it again with those device_side options on. The registry
supplies what differs per integration: the expected status, the tolerance, and the fields and options in scope.
No pytest here: scripts/rig.py calls run(), and a tester's one-file runner can import this module unchanged.
"""

import ast
import asyncio
import contextlib
import logging
import operator
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from scripts.fingerprint import adapter_path, fingerprint

from .bridge import BridgeError, HueBridge
from .client import HAClient, HAError
from .inventory import RIG_DIR, ROLES, SETTLE_S, TOLERANCE_S, Inventory

_LOGGER = logging.getLogger(__name__)

STEPS_DIR = RIG_DIR / "steps"
COMPONENT_DIR = RIG_DIR.parents[1] / "custom_components" / "device_side"

# Light attributes a restore puts back, in the order light.turn_on would accept one color at a time.
_RESTORE_COLOR = ("color_temp_kelvin", "hs_color", "xy_color", "rgb_color")

# Integrations whose adapter calls an admin-only action with the caller's context, so their suites run on
# HA_ADMIN_TOKEN. ZHA: issue_zigbee_cluster_command is registered with async_register_admin_service.
# Zigbee2MQTT: the z2m_option steps publish and subscribe over MQTT, which only an admin may.
ADMIN_INTEGRATIONS = frozenset({"zha", "zigbee2mqtt"})

# Statuses that mean the command reached the device; unchanged sent nothing, so it proves no call.
_REACHED = frozenset({"confirmed", "sent"})

# An entity whose supply a case switched rejoins its network after power returns. ZHA keeps showing the last state
# of a mains device for hours, so the restore waits, then retries until the device takes the command.
POWER_SETTLE_S = 5.0
POWER_REJOIN_S = 60.0
POWER_RETRY_S = 3.0

# A light reports off as its fade starts: an observed case waits this long after setup, so the brief comes once the
# lights have reached the start state it describes.
SETUP_SETTLE_S = 2.0

# How long after saving options the engine waits before checking the entry has reloaded.
OPTIONS_RELOAD_S = 1.0

# Actions whose calls leave a prediction behind (SETTLE_S), and move's default sweep_time (actions/move.py
# DEFAULT_SWEEP_TIME), the longest a move without one can run.
_PREDICTED = frozenset({"move", "stop"})
MOVE_SWEEP_TIME_S = 5.0


class SchemaError(ValueError):
    """A step file that does not parse; the message names the file, test and step."""


class StepFailure(AssertionError):
    """A step whose expectation did not hold."""


# --- Expressions: numbers, `duration`, `tol`, and + - * --------------------------------------------------------

_OPS: dict[type, Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
}
NAMES = frozenset({"duration", "tol"})


@dataclass(frozen=True, slots=True)
class Expr:
    """A duration in seconds, such as `6`, `tol` or `duration - tol`, checked when the file loads."""

    node: ast.expr

    @classmethod
    def parse(cls, value: Any) -> Expr:
        if isinstance(value, bool) or not isinstance(value, int | float | str):
            raise ValueError(f"expected a number or an expression, got {value!r}")
        try:
            node = ast.parse(str(value), mode="eval").body
        except SyntaxError:
            raise ValueError(f"cannot parse {value!r}") from None
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                if child.id not in NAMES:
                    raise ValueError(f"unknown name {child.id!r} in {value!r}; use {', '.join(sorted(NAMES))}")
            elif isinstance(child, ast.Constant):
                if isinstance(child.value, bool) or not isinstance(child.value, int | float):
                    raise ValueError(f"{child.value!r} in {value!r} is not a number")
            elif not isinstance(child, (ast.BinOp, ast.UnaryOp, ast.USub, ast.Load, *_OPS)):
                raise ValueError(f"{value!r} uses something other than numbers, names and + - *")
        return cls(node)

    def eval(self, names: dict[str, float]) -> float:
        return _eval(self.node, names)


def _eval(node: ast.expr, names: dict[str, float]) -> float:
    match node:
        case ast.Constant(value=value):
            return float(value)
        case ast.Name(id=name):
            if name not in names:
                raise StepFailure(f"{name} is unset: no call has set a duration yet")
            return names[name]
        case ast.UnaryOp(operand=operand):
            return -_eval(operand, names)
        case ast.BinOp(left=left, op=op, right=right):
            return _OPS[type(op)](_eval(left, names), _eval(right, names))
    raise TypeError(node)  # unreachable: Expr.parse admits nothing else


# --- Step files ----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Step:
    kind: str
    args: Any
    label: str


@dataclass(frozen=True, slots=True)
class Observe:
    """What an observed test asks of the person: what the lights will do, what to watch for, and the question."""

    see: str
    watch: str
    ask: str


# Steps that check something; an observed run turns them into the waits they imply.
CHECKS = frozenset({"expect_response", "expect_error", "expect_state", "sample"})


@dataclass(frozen=True, slots=True)
class RigTest:
    name: str
    roles: tuple[str, ...]
    only: frozenset[str] | None
    steps: tuple[Step, ...]
    setup: tuple[Step, ...] = ()
    observe: Observe | None = None

    @property
    def automated(self) -> bool:
        """Whether the test has an automated case: always without `observe`, else when its steps check something
        and its setup needs no one."""
        if self.observe is None:
            return True
        return any(step.kind in CHECKS for step in self.steps) and not any(step.kind == "do" for step in self.setup)

    def roles_needed(self, role: str) -> list[str]:
        """The case's own role and every role a step targets, in first-use order."""
        steps = (*self.setup, *self.steps)
        targets = (step.args.get("target") for step in steps if isinstance(step.args, dict))
        return list(dict.fromkeys([role, *filter(None, targets)]))


@dataclass(frozen=True, slots=True)
class StepFile:
    path: Path
    action: str
    rig_seconds: int
    tests: tuple[RigTest, ...]
    # The device_side options its suites run with on; every other option in the adapter's scope runs off.
    options: frozenset[str] = frozenset()

    @property
    def roles(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(role for test in self.tests for role in test.roles))

    @property
    def uses_bridge(self) -> bool:
        return any(step.kind == "bridge" for test in self.tests for step in (*test.setup, *test.steps))


def _state(value: Any) -> Any:
    # YAML 1.1 reads a bare on/off as a boolean.
    return {True: "on", False: "off"}.get(value, value) if isinstance(value, bool) else value


def _mapping(args: Any, required: Iterable[str] = (), allowed: Iterable[str] | None = None) -> dict:
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ValueError(f"expected a mapping, got {args!r}")
    if missing := [key for key in required if key not in args]:
        raise ValueError(f"missing {', '.join(missing)}")
    if allowed is not None and (unknown := sorted(set(args) - set(allowed) - set(required))):
        raise ValueError(f"unknown key(s) {', '.join(unknown)}")
    if (target := args.get("target")) is not None and target not in ROLES:
        raise ValueError(f"target {target!r} is not an inventory role")
    return dict(args)


def _expected(value: Any) -> Any:
    """A literal, or a {min, max} range for a number that drifts (brightness, color temperature)."""
    if isinstance(value, dict):
        if not value or set(value) - {"min", "max"}:
            raise ValueError(f"a range takes min and/or max, got {value!r}")
        if not all(isinstance(bound, int | float) for bound in value.values()):
            raise ValueError(f"range bounds must be numbers, got {value!r}")
    return value


def _parse_set(args: Any) -> dict:
    args = _mapping(args, required=["state"])
    args["state"] = _state(args["state"])
    if args["state"] not in ("on", "off"):
        raise ValueError(f"state must be on or off, got {args['state']!r}")
    return args


def _parse_call(args: Any) -> dict:
    args = _mapping(args)
    if "duration" in args:
        args["duration"] = Expr.parse(args["duration"])
    return args


def _parse_expect_response(args: Any) -> dict:
    args = _mapping(args, allowed=["target", "status", "integration", "detail", "clamped_to", "attributes"])
    if not isinstance(attributes := args.get("attributes", {}), dict):
        raise ValueError("attributes must be a mapping")
    args["attributes"] = {name: _expected(value) for name, value in attributes.items()}
    return args


def _parse_expect_error(args: Any) -> dict:
    args = _mapping(args, allowed=["key", "summary"])
    if not args:
        raise ValueError("name a key, a summary or both")
    return args


def _parse_expect_state(args: Any) -> dict:
    args = _mapping(args)
    if "within" in args:
        args["within"] = Expr.parse(args["within"])
    for name, value in args.items():
        if name not in ("target", "within"):
            args[name] = _state(value) if name == "state" else _expected(value)
    if len(set(args) - {"target", "within"}) == 0:
        raise ValueError("name a state or an attribute to expect")
    return args


def _parse_sample(args: Any) -> dict:
    args = _mapping(
        args, required=["attribute", "for"], allowed=["target", "every", "expect", "min", "max", "source"]
    )
    args["for"] = Expr.parse(args["for"])
    args["every"] = Expr.parse(args.get("every", 0.5))
    if args.get("expect", "rising") not in ("rising", "falling", "steady"):
        raise ValueError(f"expect must be rising, falling or steady, got {args['expect']!r}")
    if args.get("source", "ha") not in ("ha", "device_side"):
        raise ValueError(f"source must be ha or device_side, got {args['source']!r}")
    return args


def _parse_do(args: Any) -> str:
    if not isinstance(args, str) or not args.strip():
        raise ValueError("do takes the instruction for the person, as a string")
    return args.strip()


def _parse_z2m_option(args: Any) -> dict:
    args = _mapping(args)
    if not set(args) - {"target"}:
        raise ValueError("name an option")
    return args


def _body_keys(value: Any) -> Any:
    """A body with YAML 1.1's boolean keys put back: a bare `on:` key reads as True, and Hue's is `on`."""
    if isinstance(value, dict):
        return {_state(key): _body_keys(inner) for key, inner in value.items()}
    return value


def _parse_bridge(args: Any) -> dict:
    args = _mapping(args, allowed=["target", "put", "recall"])
    if ("put" in args) == ("recall" in args):
        raise ValueError("give put or recall, one of them")
    if "put" in args and (not isinstance(args["put"], dict) or not args["put"]):
        raise ValueError("put takes the body to write, as a mapping")
    if "put" in args:
        args["put"] = _body_keys(args["put"])
    if "recall" in args and args["recall"] is not True:
        raise ValueError("recall takes true")
    return args


def _parse_restore(args: Any) -> None:
    if args not in (None, {}):
        raise ValueError("restore takes no arguments")


PARSERS: dict[str, Callable[[Any], Any]] = {
    "set": _parse_set,
    "call": _parse_call,
    "expect_response": _parse_expect_response,
    "expect_error": _parse_expect_error,
    "expect_state": _parse_expect_state,
    "wait": Expr.parse,
    "sample": _parse_sample,
    "do": _parse_do,
    "restore": _parse_restore,
    # A write to the Hue bridge that bypasses HA; fails in any other integration's suite.
    "bridge": _parse_bridge,
    # Zigbee2MQTT device options; both steps do nothing in another integration's suite.
    "z2m_option": _parse_z2m_option,
    "expect_z2m_option": _parse_z2m_option,
}


def _parse_step(raw: Any, label: str) -> Step:
    if not isinstance(raw, dict) or len(raw) != 1:
        raise ValueError(f"{label}: expected one `kind: args` mapping, got {raw!r}")
    ((kind, args),) = raw.items()
    label = f"{label} ({kind})"
    if kind == "observe":
        raise ValueError(f"{label}: the observe step is gone; give the test observe: {{see, watch, ask}}")
    if kind not in PARSERS:
        raise ValueError(f"{label}: unknown step; use one of {', '.join(PARSERS)}")
    try:
        return Step(kind, PARSERS[kind](args), label)
    except ValueError as err:
        raise ValueError(f"{label}: {err}") from None


def _parse_steps(raw: Any, key: str) -> tuple[Step, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{key} must be a non-empty list")
    prefix = "setup step" if key == "setup" else "step"
    return tuple(_parse_step(step, f"{prefix} {index}") for index, step in enumerate(raw, 1))


def _parse_observe(raw: Any) -> Observe:
    try:
        args = _mapping(raw, required=("see", "watch", "ask"), allowed=())
        if not all(isinstance(value, str) and value.strip() for value in args.values()):
            raise ValueError("see, watch and ask must be non-empty strings")
    except ValueError as err:
        raise ValueError(f"observe: {err}") from None
    return Observe(args["see"].strip(), args["watch"].strip(), args["ask"].strip())


def _parse_test(raw: Any) -> RigTest:
    if not isinstance(raw, dict) or not isinstance(name := raw.get("name"), str):
        raise ValueError(f"a test needs a name, got {raw!r}")
    try:
        if "brief" in raw:
            raise ValueError("brief is gone; give the test observe: {see, watch, ask}")
        if unknown := sorted(set(raw) - {"name", "roles", "only", "setup", "steps", "observe"}):
            raise ValueError(f"unknown key(s) {', '.join(unknown)}")
        roles = raw.get("roles")
        if not isinstance(roles, list) or not roles:
            raise ValueError("roles must be a non-empty list")
        if unknown := sorted(set(roles) - ROLES):
            raise ValueError(f"unknown role(s) {', '.join(unknown)}")
        only = raw.get("only")
        if only is not None and (not isinstance(only, list) or not only):
            raise ValueError("only must be a non-empty list of integration keys")
        steps, setup, observe = _parse_phases(raw)
    except ValueError as err:
        raise ValueError(f"test {name}, {err}") from None
    return RigTest(name, tuple(roles), frozenset(only) if only else None, steps, setup, observe)


def _parse_phases(raw: dict) -> tuple[tuple[Step, ...], tuple[Step, ...], Observe | None]:
    """A test's steps, setup and observe block, with `do` only in the setup of an observed test."""
    steps = _parse_steps(raw.get("steps"), "steps")
    setup = _parse_steps(raw["setup"], "setup") if "setup" in raw else ()
    observe = _parse_observe(raw["observe"]) if "observe" in raw else None
    if observe is not None and not setup:
        raise ValueError("a test with observe needs setup: the steps that bring the lights to where see begins")
    if do := next((step for step in steps if step.kind == "do"), None):
        raise ValueError(f"{do.label}: do belongs in setup, before the brief")
    if observe is None and (do := next((step for step in setup if step.kind == "do"), None)):
        raise ValueError(f"{do.label}: do is only for a test with observe")
    return steps, setup, observe


def load_step_file(path: Path) -> StepFile:
    try:
        raw = yaml.safe_load(path.read_text())
        if not isinstance(raw, dict):
            raise ValueError("expected a mapping with action, rig_seconds and tests")
        if unknown := sorted(set(raw) - {"action", "rig_seconds", "options", "tests"}):
            raise ValueError(f"unknown key(s) {', '.join(unknown)}")
        if not isinstance(action := raw.get("action"), str):
            raise ValueError("action must name the device_side action under test")
        options = raw.get("options", [])
        if not isinstance(options, list) or not all(isinstance(name, str) and name for name in options):
            raise ValueError("options must be a list of device_side option names")
        if isinstance(seconds := raw.get("rig_seconds"), bool) or not isinstance(seconds, int) or seconds <= 0:
            raise ValueError("rig_seconds must be a positive whole number")
        if not isinstance(raw_tests := raw.get("tests"), list) or not raw_tests:
            raise ValueError("tests must be a non-empty list")
        tests = tuple(_parse_test(test) for test in raw_tests)
        if duplicates := sorted({t.name for t in tests if [u.name for u in tests].count(t.name) > 1}):
            raise ValueError(f"duplicate test name(s) {', '.join(duplicates)}")
    except (ValueError, yaml.YAMLError) as err:
        raise SchemaError(f"{path.name}: {err}") from None
    return StepFile(path, action, seconds, tests, frozenset(options))


def load_step_files(steps_dir: Path = STEPS_DIR) -> list[StepFile]:
    """Every `<action>.yaml` directly in steps_dir."""
    return [load_step_file(path) for path in sorted(steps_dir.glob("*.yaml"))]


# --- Planning ------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Suite:
    """One step file on one integration."""

    file: StepFile
    integration: str

    @property
    def action(self) -> str:
        return self.file.action

    @property
    def name(self) -> str:
        """The name its record takes: the action, then any options it runs with on (`move-predicted_state`)."""
        return "-".join([self.action, *sorted(self.file.options)])


@dataclass(frozen=True, slots=True)
class Case:
    """One run of a test on one role, automated or observed: the entities it moves, or why it is skipped."""

    suite: Suite
    test: RigTest
    role: str
    entities: dict[str, str]
    skip: str | None = None
    observed: bool = False
    members: tuple[str, ...] = ()  # the inventory's members for the group role, if it lists them

    @property
    def id(self) -> str:
        return f"{self.test.name}[{self.role}]" + (" observed" if self.observed else "")

    @property
    def twin(self) -> str | None:
        """The id of the test's other case on this role, when it has both: either proves nothing alone."""
        if self.test.observe is None or not self.test.automated:
            return None
        return replace(self, observed=not self.observed).id


def cases(suite: Suite, inventory: Inventory, keyword: str | None = None) -> list[Case]:
    """The suite's cases in file order, a test's automated case before its observed one; `keyword` keeps only case
    ids containing it."""
    result = []
    for test in suite.file.tests:
        if test.only is not None and suite.integration not in test.only:
            continue
        for role in test.roles:
            for observed in [False] * test.automated + [True] * (test.observe is not None):
                case = Case(suite, test, role, {}, observed=observed)
                if keyword and keyword not in case.id:
                    continue
                needed = test.roles_needed(role)
                entities = {name: inventory.entity(suite.integration, name) for name in needed}
                if missing := [name for name, entity_id in entities.items() if entity_id is None]:
                    case = Case(suite, test, role, {}, f"no {missing[0]} entity in inventory", observed)
                else:
                    members = inventory.members(suite.integration, entities["group"]) if "group" in entities else ()
                    case = Case(suite, test, role, entities, observed=observed, members=members)
                result.append(case)
    return result


# --- Running -------------------------------------------------------------------------------------------------


class EntryOptions:
    """device_side's options on the rig, set for each case through the entry's options flow (admin only) and put
    back when the run ends. Saving a change reloads the entry."""

    def __init__(self, admin: HAClient, reload_s: float = OPTIONS_RELOAD_S):
        self.admin = admin
        self.reload_s = reload_s
        self.entry_id: str | None = None
        self.original: dict[str, Any] | None = None
        self.current: dict[str, Any] = {}

    async def apply(self, wanted: dict[str, bool]) -> None:
        if self.original is not None and all(self.current.get(name) == on for name, on in wanted.items()):
            return
        if self.entry_id is None:
            entries = await self.admin.command({"type": "config_entries/get", "domain": "device_side"})
            if not entries:
                raise RuntimeError("no device_side config entry to set options on")
            self.entry_id = entries[0]["entry_id"]
        flow = await self.admin.rest("post", "/api/config/config_entries/options/flow", {"handler": self.entry_id})
        # The form's defaults are the options in force.
        values = {field["name"]: field.get("default") for field in flow.get("data_schema", [])}
        if self.original is None:
            self.original = dict(values)
        flow_path = f"/api/config/config_entries/options/flow/{flow['flow_id']}"
        if all(values.get(name) == on for name, on in wanted.items()):
            # Saving would still reload an entry whose options were never saved: they go from none to these.
            await self.admin.rest("delete", flow_path)
            self.current = values
            return
        values |= wanted
        try:
            result = await self.admin.rest("post", flow_path, values)
            if result.get("type") != "create_entry":
                raise RuntimeError(f"device_side's options flow did not save: {result}")
        except Exception:
            with contextlib.suppress(Exception):  # don't leave the flow open in HA; the save's error is the one raised
                await self.admin.rest("delete", flow_path)
            raise
        self.current = values
        await self.reloaded()

    async def reloaded(self) -> None:
        """Wait for the reload a saved change schedules: it starts after the save returns."""
        await asyncio.sleep(self.reload_s)
        query = {"type": "config_entries/get", "domain": "device_side"}
        async with asyncio.timeout(30):
            while not (entries := await self.admin.command(query)) or entries[0]["state"] != "loaded":
                await asyncio.sleep(0.5)

    async def restore(self) -> None:
        if self.original is not None and self.current != self.original:
            await self.apply(self.original)


class Outcome(StrEnum):
    PASS = "pass"
    NOT_OBSERVED = "not observed"
    FAIL = "fail"
    SKIPPED = "skipped"


@dataclass(slots=True)
class CaseResult:
    id: str
    role: str
    domain: str | None
    outcome: Outcome
    detail: str = ""
    entity_ids: tuple[str, ...] = ()
    # Fields in the adapter's scope that a call carried to the device, whether any call reached it, and the
    # capabilities those calls reached (empty when the adapter's scope.capabilities is None).
    fields: frozenset[str] = frozenset()
    reached: bool = False
    capabilities: frozenset[str] = frozenset()
    twin: str | None = None  # Case.twin


@dataclass(slots=True)
class SuiteResult:
    suite: Suite
    adapter: Any
    cases: list[CaseResult]
    # False when -k left tests out: a partial run writes no record.
    complete: bool

    @property
    def recordable(self) -> bool:
        """A complete run that proved something and failed nothing; an all-unobserved run would erase a record."""
        return self.complete and bool(self.proven) and all(case.outcome is not Outcome.FAIL for case in self.cases)

    @property
    def proven(self) -> list[CaseResult]:
        """Passed cases whose twin passed too: only these go into a record's scope."""
        passed = {case.id for case in self.cases if case.outcome is Outcome.PASS}
        return [case for case in self.cases if case.id in passed and (case.twin is None or case.twin in passed)]


@dataclass(slots=True)
class RunResult:
    suites: list[SuiteResult]

    @property
    def failed(self) -> bool:
        return any(case.outcome is Outcome.FAIL for suite in self.suites for case in suite.cases)


@dataclass(slots=True)
class Snapshot:
    """Each touched entity's state, put back after the case.

    HA shows no brightness or color for a light that is off, so with `device_side` set (the integration has
    get_attributes and set_attributes adapters) an off light's device-side attributes are read when it is first
    touched and written back after it is turned off again. A group is skipped there: its members are touched too.
    """

    ha: HAClient
    power: dict[str, str] = field(default_factory=dict)  # Inventory.power(): entity -> its supply
    device_side: bool = False
    taken: dict[str, dict | None] = field(default_factory=dict)
    stored: dict[str, dict] = field(default_factory=dict)

    async def take(self, entity_id: str, group: bool = False) -> dict | None:
        """The entity's state before the case moved it, and that of every entity it powers."""
        if entity_id not in self.taken:
            state = self.taken[entity_id] = await self.ha.get_state(entity_id)
            if self.device_side and not group and _is_off_light(entity_id, state):
                response = await self.ha.call_service(
                    "device_side", "get_attributes", {"entity_id": entity_id}, return_response=True
                )
                if attributes := (response or {}).get(entity_id):
                    self.stored[entity_id] = attributes
            for powered, supply in self.power.items():
                if supply == entity_id:
                    await self.take(powered)
        return self.taken[entity_id]

    async def restore(self) -> None:
        # A powered entity goes back after its supply, whatever order the case touched them in.
        cut = [entity_id for entity_id in self.taken if self.power.get(entity_id) in self.taken]
        for entity_id in [entity_id for entity_id in self.taken if entity_id not in cut] + cut:
            state = self.taken[entity_id]
            if state is None or state["state"] not in ("on", "off"):
                continue
            if entity_id not in cut:
                try:
                    await self.put_back(entity_id, state)
                except Exception as err:  # noqa: BLE001 - a failed restore is logged so it can't mask the test result
                    _LOGGER.warning("Could not restore %s to %s: %s", entity_id, state["state"], err)
            elif (self.taken[self.power[entity_id]] or {}).get("state") == "on":  # unpowered before: nothing to restore
                await self.put_back_after_power(entity_id, state)

    async def put_back_after_power(self, entity_id: str, state: dict) -> None:
        loop = asyncio.get_running_loop()
        await asyncio.sleep(POWER_SETTLE_S)
        deadline = loop.time() + POWER_REJOIN_S
        while True:
            try:
                await self.put_back(entity_id, state)
                return
            except Exception as err:  # noqa: BLE001 - as restore(): retried, then logged
                if loop.time() >= deadline:
                    _LOGGER.warning("Could not restore %s after power returned: %s", entity_id, err)
                    return
            await asyncio.sleep(POWER_RETRY_S)

    async def put_back(self, entity_id: str, state: dict) -> None:
        domain = entity_id.partition(".")[0]
        if state["state"] == "off":
            await self.ha.call_service(domain, "turn_off", {"entity_id": entity_id})
            if (stored := self.stored.get(entity_id)) and (data := _light_data(stored)):
                await self.ha.call_service("device_side", "set_attributes", {"entity_id": entity_id, **data})
            return
        data = _light_data(state["attributes"]) if domain == "light" else {}
        await self.ha.call_service(domain, "turn_on", {"entity_id": entity_id, **data})


def _is_off_light(entity_id: str, state: dict | None) -> bool:
    """A light that is off and not a group (a group lists its members in its entity_id attribute)."""
    return (
        entity_id.startswith("light.")
        and state is not None
        and state["state"] == "off"
        and "entity_id" not in state["attributes"]
    )


def _light_data(attributes: dict) -> dict:
    """Brightness and the first color attribute light.turn_on (or set_attributes) accepts, from a light's attributes."""
    data = {"brightness": attributes["brightness"]} if attributes.get("brightness") is not None else {}
    for name in _RESTORE_COLOR:
        if attributes.get(name) is not None:
            data[name] = attributes[name]
            break
    return data


def _value(state: dict, name: str) -> Any:
    return state["state"] if name == "state" else state["attributes"].get(name)


def _matches(actual: Any, want: Any) -> bool:
    if isinstance(want, dict):
        if isinstance(actual, bool) or not isinstance(actual, int | float):
            return False
        return want.get("min", actual) <= actual <= want.get("max", actual)
    return actual == want


def _describe(state: dict | None, names: Iterable[str]) -> str:
    if state is None:
        return "no state"
    return ", ".join(f"{name}={_value(state, name)!r}" for name in names)


def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


class _NoOneThere(Exception):
    """EOF at a prompt: nobody is at the rig, so the observed case ends not observed."""


class _CaseRun:
    """The steps of one case, against one HA connection, with what earlier steps left behind.

    An observed case runs its setup, briefs the person and waits for Enter, runs its steps with every check relaxed to
    the wait it implies (so the timing matches the automated case), then asks its question.
    """

    def __init__(
        self,
        case: Case,
        ha: HAClient,
        registry: Any,
        tolerance: float,
        ask: Callable[[str], str] | None,
        power: dict[str, str] | None = None,
        out: Callable[[str], None] = print,
        position: str = "",
        busy: dict[str, float] | None = None,
        settle: float = 0.0,
        bridge: HueBridge | None = None,
    ):
        self.bridge = bridge
        self.case, self.ha, self.registry, self.ask, self.out, self.position = case, ha, registry, ask, out, position
        self.integration = case.suite.integration
        # Each light's loop time once the predictions an earlier move or stop left on it have expired; shared
        # by every case in the run.
        self.busy = {} if busy is None else busy
        self.settle = settle
        self.names: dict[str, float] = {"tol": tolerance}
        self.snapshot = Snapshot(
            ha,
            power or {},
            device_side=all(
                registry.adapter(action, self.integration) is not None
                for action in ("get_attributes", "set_attributes")
            ),
        )
        self.response: dict | None = None
        self.error: HAError | None = None
        self.last_action = case.suite.action
        self.query = False
        self.fields: set[str] = set()
        self.reached = False
        self.capabilities: set[str] = set()

    def entity(self, args: Any) -> str:
        role = args.get("target") if isinstance(args, dict) else None
        return self.case.entities[role or self.case.role]

    def is_group(self, entity_id: str) -> bool:
        return self.case.entities.get("group") == entity_id

    async def members(self, entity_id: str) -> list[str]:
        """A group's member lights, from its `entity_id` attribute, else the inventory's `members:` (a Z2M group light
        has no such attribute); any other entity is its own one member."""
        if not self.is_group(entity_id):
            return [entity_id]
        state = await self.ha.get_state(entity_id)
        members = state and state["attributes"].get("entity_id")
        if isinstance(members, list) and members:
            return members
        if self.case.members:
            return list(self.case.members)
        raise StepFailure(f"{entity_id} lists no members in its entity_id attribute, and the inventory gives none")

    async def touch(self, entity_id: str) -> None:
        """Snapshot the entity, and a group's members after it, so a restore puts each member back last."""
        await self.snapshot.take(entity_id, group=self.is_group(entity_id))
        if self.is_group(entity_id):
            for member in await self.members(entity_id):
                await self.snapshot.take(member)

    async def run(self) -> CaseResult:
        case = self.case
        domain = case.entities[case.role].partition(".")[0]
        result = CaseResult(
            case.id, case.role, domain, Outcome.PASS, entity_ids=tuple(case.entities.values()), twin=case.twin
        )
        try:
            if case.observed:
                self.out("")
                self.out(f"--- {case.suite.action} / {case.test.name} on {case.role} ({self.position}) ---")
            await self.await_settled()
            await self.check_power()
            await self.steps(case.test.setup)
            if case.observed:
                await self.observed()
            else:
                await self.steps(case.test.steps)
        except StepFailure as err:
            result.outcome, result.detail = Outcome.FAIL, str(err)
        except _NoOneThere:
            result.outcome = Outcome.NOT_OBSERVED
        finally:
            await self.snapshot.restore()
        result.fields, result.reached = frozenset(self.fields), self.reached
        result.capabilities = frozenset(self.capabilities)
        return result

    async def steps(self, steps: tuple[Step, ...], relaxed: bool = False) -> None:
        for index, step in enumerate(steps):
            following = steps[index + 1].kind if index + 1 < len(steps) else None
            handler = getattr(self, f"_{step.kind}")
            if relaxed:
                handler = getattr(self, f"_relaxed_{step.kind}", handler)
            try:
                await handler(step.args, following)
            except StepFailure as err:
                raise StepFailure(f"{step.label}: {err}") from None
            except _NoOneThere:
                raise
            except Exception as err:  # noqa: BLE001 - any error ends the case as a fail, not the run
                raise StepFailure(f"{step.label}: {type(err).__name__}: {err}") from None

    async def observed(self) -> None:
        observe = self.case.test.observe
        assert observe is not None  # only a test with observe has an observed case
        await asyncio.sleep(SETUP_SETTLE_S)
        self.out(f"Lights: {await self.lights_by_name()}")
        self.out(f"You'll see: {_bold(observe.see)}")
        self.out(f"Watch for: {observe.watch}")
        await self.answer("Press Enter to start... ")
        try:
            await self.steps(self.case.test.steps, relaxed=True)
        except StepFailure as err:
            self.out(f"    nothing to observe: {err}")
            with contextlib.suppress(EOFError):
                await asyncio.to_thread(self.ask, "Press Enter to go on... ")
            raise
        while (answer := (await self.answer(f"    {observe.ask} [Y/n] ")).lower()) not in ("", "y", "yes", "n", "no"):
            self.out("    Answer y or n.")
        if answer in ("n", "no"):
            try:
                saw = await self.answer("    What did you see? (Enter to skip) ")
            except _NoOneThere:
                saw = ""
            raise StepFailure(f"not seen: {observe.ask}" + (f"; saw: {saw}" if saw else ""))

    async def lights_by_name(self) -> str:
        """The case's lights by name, a group's members after it: the brief's step files can't name household lights."""

        async def name(entity_id: str) -> str:
            state = await self.ha.get_state(entity_id)
            return (state and state["attributes"].get("friendly_name")) or entity_id

        names = []
        for entity_id in self.case.entities.values():
            label = await name(entity_id)
            if self.is_group(entity_id):
                label += f" ({', '.join([await name(member) for member in await self.members(entity_id)])})"
            names.append(label)
        return "; ".join(names)

    async def answer(self, text: str) -> str:
        """The person's reply, stripped; EOF there means nobody is at the rig."""
        try:
            return (await asyncio.to_thread(self.ask, text)).strip()
        except EOFError:
            raise _NoOneThere from None

    async def await_settled(self) -> None:
        """Wait out the predictions an earlier case's move or stop left on this case's lights."""
        lights = [member for entity_id in self.case.entities.values() for member in await self.members(entity_id)]
        wait = max((self.busy.get(light, 0.0) for light in lights), default=0.0) - asyncio.get_running_loop().time()
        if wait > 0:
            if self.case.observed:
                self.out(f"Waiting {wait:.0f} s for the last move's predictions to expire...")
            await asyncio.sleep(wait)

    async def check_power(self) -> None:
        """Fail up front if a target's supply is off: its state in HA is stale, so every step would mislead."""
        for entity_id in self.case.entities.values():
            if (supply := self.snapshot.power.get(entity_id)) is None:
                continue
            state = await self.ha.get_state(supply)
            if state is None or state["state"] != "on":
                found = state["state"] if state else "missing"
                raise StepFailure(f"power: {entity_id} draws power through {supply}, which is {found}; turn it on")

    async def _set(self, args: dict, _following: str | None) -> None:
        entity_id = self.entity(args)
        domain = entity_id.partition(".")[0]
        await self.touch(entity_id)
        data = {key: value for key, value in args.items() if key not in ("target", "state")}
        if domain == "scene":
            await self.ha.call_service("scene", "turn_on", {"entity_id": entity_id, **data})
            return
        service = "turn_on" if args["state"] == "on" else "turn_off"
        await self.ha.call_service(domain, service, {"entity_id": entity_id, **data})
        want: dict[str, Any] = {"state": args["state"]}
        if "brightness_pct" in data:
            # A light already on reads "on" at once; wait for the brightness, so the bridge state the next call
            # reads is the one just set. Hue rounds to its own 0-100 scale, so allow a step either side.
            brightness = round(data["brightness_pct"] * 255 / 100)
            want["brightness"] = {"min": brightness - 2, "max": brightness + 2}
        await self.await_state(entity_id, want, self.names["tol"])

    async def z2m_ieee(self, entity_id: str) -> str:
        entry = await self.ha.command({"type": "config/entity_registry/get", "entity_id": entity_id})
        for device in await self.ha.command({"type": "config/device_registry/list"}):
            if device["id"] == entry.get("device_id"):
                for domain, ident in device["identifiers"]:
                    if domain == "mqtt" and ident.startswith("zigbee2mqtt_0x"):
                        return ident.removeprefix("zigbee2mqtt_")
        raise StepFailure(f"{entity_id} has no Zigbee2MQTT device")

    async def _z2m_option(self, args: dict, _following: str | None) -> None:
        if self.integration != "zigbee2mqtt":
            return
        options = {name: value for name, value in args.items() if name != "target"}
        await self.ha.set_z2m_device_options(await self.z2m_ieee(self.entity(args)), options)

    async def _expect_z2m_option(self, args: dict, _following: str | None) -> None:
        if self.integration != "zigbee2mqtt":
            return
        entity_id = self.entity(args)
        got = await self.ha.z2m_device_options(await self.z2m_ieee(entity_id))
        for name, want in args.items():
            if name != "target" and got.get(name) != want:
                raise StepFailure(f"{entity_id}: Zigbee2MQTT option {name} is {got.get(name)!r}, expected {want!r}")

    async def bridge_resource(self, entity_id: str) -> tuple[str, str]:
        """The CLIP v2 type and id behind a Hue entity. Core's hue integration keys each entity by its resource id:
        a light's by its light, a room or zone light's by its grouped_light, a scene's by its scene."""
        entry = await self.ha.command({"type": "config/entity_registry/get", "entity_id": entity_id})
        if entry.get("platform") != "hue":
            raise StepFailure(f"{entity_id} is not a Hue entity (platform {entry.get('platform')!r})")
        if not entry.get("unique_id"):
            raise StepFailure(f"{entity_id} has no unique_id to find on the bridge")
        domain = entity_id.partition(".")[0]
        if domain == "scene":
            return "scene", entry["unique_id"]
        return ("grouped_light" if self.is_group(entity_id) else "light"), entry["unique_id"]

    async def _bridge(self, args: dict, _following: str | None) -> None:
        if self.integration != "hue":
            raise StepFailure(f"bridge steps need a Hue suite, not {self.integration}")
        if self.bridge is None:
            raise StepFailure("no Hue bridge: set HUE_BRIDGE_HOST and HUE_APP_KEY in .env.rig")
        entity_id = self.entity(args)
        is_scene = entity_id.startswith("scene.")
        if "recall" in args and not is_scene:
            raise StepFailure(f"recall needs a scene target, not {entity_id}")
        if "put" in args and is_scene:
            raise StepFailure(f"put needs a light or group target, not {entity_id}")
        await self.touch(entity_id)
        resource_type, resource_id = await self.bridge_resource(entity_id)
        body = {"recall": {"action": "active"}} if "recall" in args else args["put"]
        try:
            await self.bridge.put(resource_type, resource_id, body)
        except BridgeError as err:
            raise StepFailure(str(err)) from None

    async def _call(self, args: dict, following: str | None) -> None:
        action = args.get("action", self.case.suite.action)
        entity_id = self.entity(args)
        await self.touch(entity_id)
        data: dict[str, Any] = {"entity_id": entity_id}
        for key, value in args.items():
            if key == "duration":
                seconds = self.names["duration"] = value.eval(self.names)
                data["duration"] = {"seconds": int(seconds) if seconds.is_integer() else seconds}
            elif key not in ("action", "target"):
                data[key] = value
        self.last_action, self.response, self.error = action, None, None
        # ActionKind is a StrEnum: compared by value so the engine needs no integration import.
        self.query = getattr(getattr(self.registry, "actions", {}).get(action), "kind", None) == "query"
        try:
            self.response = await self.ha.call_service("device_side", action, data, return_response=True)
        except HAError as err:
            if following != "expect_error":
                raise StepFailure(f"device_side.{action} raised {err.translation_key}: {err}") from None
            self.error = err
            return
        if following == "expect_error":
            raise StepFailure(f"device_side.{action} succeeded where an error was expected: {self.response}")
        await self.mark_busy(action, data)
        entries = [entry for entry in (self.response or {}).values() if isinstance(entry, dict)]
        # A query returns only the targets it read, as core does, with no status to check. Only the action under
        # test counts: a move that sets up a stop proves nothing about the stop adapter.
        if action == self.case.suite.action and (
            entries and (self.query or any(entry.get("status") in _REACHED for entry in entries))
        ):
            await self.mark_reached(action, data)

    async def mark_reached(self, action: str, data: dict) -> None:
        """Note the fields the call carried and the capability it reached, as far as the adapter's scope covers."""
        self.reached = True
        if (adapter := self.registry.adapter(action, self.integration)) is not None:
            self.fields |= set(data) & adapter.scope.fields
            if adapter.scope.capabilities is not None:
                self.capabilities.add(await self.capability(data["entity_id"]))

    async def capability(self, entity_id: str) -> str:
        """The capability a call on the entity reached, read as its adapter addresses it (Shelly: the RPC component)."""
        if self.integration != "shelly":
            raise StepFailure(f"the rig can't tell which {self.integration} capability {entity_id} reaches")
        # Imported here: the component imports Home Assistant, and a tester's runner imports this module without it.
        from custom_components.device_side.integrations.shelly.addressing import address  # noqa: PLC0415

        entry = await self.ha.command({"type": "config/entity_registry/get", "entity_id": entity_id})
        # address() reads only the registry entry's unique_id.
        if (rpc := address(SimpleNamespace(entry=SimpleNamespace(unique_id=entry.get("unique_id") or "")))) is None:
            raise StepFailure(f"{entity_id} is not a Shelly component the adapter addresses")
        return rpc.component

    async def mark_busy(self, action: str, data: dict) -> None:
        """After a move or stop, hold its lights until the predictions it left expire (see await_settled)."""
        if not self.settle or action not in _PREDICTED:
            return
        sweep = data.get("sweep_time", MOVE_SWEEP_TIME_S) if action == "move" else 0.0
        until = asyncio.get_running_loop().time() + sweep + self.settle
        for member in await self.members(data["entity_id"]):
            self.busy[member] = max(self.busy.get(member, 0.0), until)

    def expected(self, name: str, want: Any) -> Any:
        if name == "status" and want == "expected":
            if (adapter := self.registry.adapter(self.last_action, self.integration)) is None:
                raise StepFailure(f"no {self.last_action} adapter on {self.integration} to expect a status from")
            return "confirmed" if adapter.scope.confirmable else "sent"
        if name == "integration" and want == "self":
            return self.integration
        return want

    async def _expect_response(self, args: dict, _following: str | None) -> None:
        if self.response is None:
            raise StepFailure("no response to check: no call has returned one")
        entity_id = self.entity(args)
        keys = [entity_id] if entity_id in self.response else await self.members(entity_id)
        for key in keys:
            if not isinstance(entry := self.response.get(key), dict):
                raise StepFailure(f"the response has no entry for {key}: {self.response}")
            for name, want in args.items():
                if name == "target":
                    continue
                if name == "attributes":
                    got = entry if self.query else entry.get("attributes") or {}
                    if bad := [attr for attr, value in want.items() if not _matches(got.get(attr), value)]:
                        raise StepFailure(f"{key}: attributes {bad} are {got}, expected {want}")
                elif not _matches(entry.get(name), expected := self.expected(name, want)):
                    raise StepFailure(f"{key}: {name} is {entry.get(name)!r}, expected {expected!r}: {entry}")

    async def _expect_error(self, args: dict, _following: str | None) -> None:
        if self.error is None:
            raise StepFailure("no error to check: the last call did not raise")
        err = self.error
        if "key" in args and err.translation_key != args["key"]:
            raise StepFailure(f"error key is {err.translation_key!r}, expected {args['key']!r}: {err}")
        if "summary" in args:
            expected = f"{self.entity({})}: {args['summary']}"
            if (summary := err.translation_placeholders.get("summary")) != expected:
                raise StepFailure(f"error summary is {summary!r}, expected {expected!r}")

    async def _expect_state(self, args: dict, _following: str | None) -> None:
        want = {name: value for name, value in args.items() if name not in ("target", "within")}
        within = args["within"].eval(self.names) if "within" in args else None
        await self.await_state(self.entity(args), want, within)

    async def await_state(self, entity_id: str, want: dict, within: float | None) -> None:
        """Every member of the target matches `want` now, or within `within` seconds shared between them."""
        deadline = asyncio.get_running_loop().time() + (within or 0)
        for member in await self.members(entity_id):
            member_want = dict(want)
            if member_want.get("state") == "unchanged":
                before = self.snapshot.taken.get(member)
                member_want["state"] = before["state"] if before else None

            def holds(state: dict | None, member_want: dict = member_want) -> bool:
                return state is not None and all(_matches(_value(state, n), v) for n, v in member_want.items())

            if within is None:
                if not holds(state := await self.ha.get_state(member)):
                    raise StepFailure(f"{member}: expected {member_want}, got {_describe(state, member_want)}")
                continue
            remaining = max(deadline - asyncio.get_running_loop().time(), 0)
            try:
                await self.ha.wait_for(member, holds, remaining)
            except TimeoutError:
                state = await self.ha.get_state(member)
                raise StepFailure(
                    f"{member}: expected {member_want} within {within:g} s, got {_describe(state, member_want)}"
                ) from None

    async def _wait(self, seconds: Expr, _following: str | None) -> None:
        await asyncio.sleep(max(seconds.eval(self.names), 0))

    async def _sample(self, args: dict, _following: str | None) -> None:
        """Poll an attribute for `for` seconds; an absent attribute (a light that is off) reads as 0.

        `source: device_side` reads device_side.get_attributes instead of HA's state, in its units (brightness in
        percent): mid-move it predicts where the light is, where HA shows a Hue fade's end value at once.
        """
        entity_id, attribute = self.entity(args), args["attribute"]
        loop = asyncio.get_running_loop()
        deadline = loop.time() + args["for"].eval(self.names)
        every = max(args["every"].eval(self.names), 0.05)
        readings: list[float] = []
        while True:
            value = await self.reading(entity_id, attribute, args.get("source", "ha"))
            if value is not None and (isinstance(value, bool) or not isinstance(value, int | float)):
                raise StepFailure(f"{entity_id}: {attribute} is {value!r}, not a number")
            readings.append(float(value or 0))
            if loop.time() >= deadline:
                break
            await asyncio.sleep(min(every, max(deadline - loop.time(), 0)))
        shown = [round(reading, 1) for reading in readings]
        if "min" in args and min(readings) < args["min"]:
            raise StepFailure(f"{entity_id}: {attribute} fell below {args['min']}: {shown}")
        if "max" in args and max(readings) > args["max"]:
            raise StepFailure(f"{entity_id}: {attribute} rose above {args['max']}: {shown}")
        pairs = list(zip(readings, readings[1:], strict=False))
        match args.get("expect", "rising"):
            case "rising" if not (all(b >= a for a, b in pairs) and readings[-1] > readings[0]):
                raise StepFailure(f"{entity_id}: {attribute} did not rise steadily: {shown}")
            case "falling" if not (all(b <= a for a, b in pairs) and readings[-1] < readings[0]):
                raise StepFailure(f"{entity_id}: {attribute} did not fall steadily: {shown}")
            case "steady" if len(set(readings)) > 1:
                raise StepFailure(f"{entity_id}: {attribute} moved: {shown}")

    async def reading(self, entity_id: str, attribute: str, source: str) -> Any:
        if source == "ha":
            state = await self.ha.get_state(entity_id)
            return state["attributes"].get(attribute) if state else None
        response = await self.ha.call_service(
            "device_side", "get_attributes", {"entity_id": entity_id}, return_response=True
        )
        return ((response or {}).get(entity_id) or {}).get(attribute)

    async def _do(self, instruction: str, _following: str | None) -> None:
        await self.answer(f"    {instruction} Press Enter when done... ")

    async def _restore(self, _args: None, _following: str | None) -> None:
        await self.snapshot.restore()

    # Observed mode: a check becomes the wait it implies, and never fails.

    async def _relaxed_expect_response(self, _args: dict, _following: str | None) -> None:
        pass

    _relaxed_expect_error = _relaxed_expect_response
    _relaxed_expect_z2m_option = _relaxed_expect_response

    async def _relaxed_expect_state(self, args: dict, following: str | None) -> None:
        if "within" in args:
            with contextlib.suppress(StepFailure):
                await self._expect_state(args, following)

    async def _relaxed_sample(self, args: dict, _following: str | None) -> None:
        await asyncio.sleep(max(args["for"].eval(self.names), 0))


async def run(
    suites: list[Suite],
    inventory: Inventory,
    registry: Any,
    ha: HAClient,
    *,
    admin: HAClient | None = None,
    keyword: str | None = None,
    ask: Callable[[str], str] | None = input,
    tolerance: dict[str, float] = TOLERANCE_S,
    settle: dict[str, float] = SETTLE_S,
    out: Callable[[str], None] = print,
    bridge: HueBridge | None = None,
) -> RunResult:
    """Run every case and print the table; ADMIN_INTEGRATIONS run on `admin`. `ask=None` is --unattended.

    Every automated case runs first, with nobody needed. Then each observed case runs, unless its automated twin
    failed; unattended, they are reported not observed instead.
    """
    planned = []
    for suite in suites:
        adapter = registry.adapter(suite.action, suite.integration)
        if adapter is None:
            out(f"{suite.integration} / {suite.action}: no adapter, skipped")
            continue
        if unknown := sorted(suite.file.options - adapter.scope.options):
            raise SchemaError(f"{suite.file.path.name}: {suite.integration} {suite.action} has no option {unknown[0]}")
        client = admin if suite.integration in ADMIN_INTEGRATIONS else ha
        if client is None or (adapter.scope.options and admin is None):
            out(f"{suite.integration} / {suite.action}: needs HA_ADMIN_TOKEN, skipped")
            continue
        planned.append((suite, adapter, client, cases(suite, inventory, keyword)))
    options = {
        id(suite): {name: name in suite.file.options for name in adapter.scope.options}
        for suite, adapter, *_ in planned
    }
    rig_run = _Run(
        registry, tolerance, settle, inventory.power(), ask, out, options, EntryOptions(admin) if admin else None,
        bridge=bridge,
    )
    try:
        waiting = [
            case
            for suite, _, client, suite_cases in planned
            for case in await rig_run.automated(suite, client, suite_cases)
        ]
        await rig_run.observed(waiting)
    finally:
        if rig_run.entry_options is not None:
            # A failure here must not hide the one that ended the run.
            try:
                await rig_run.entry_options.restore()
            except Exception as err:  # noqa: BLE001
                out(f"Could not put device_side's options back; set them in HA: {err}")
    suite_results = [
        SuiteResult(suite, adapter, [rig_run.results[id(suite), case.id] for case in suite_cases], complete=not keyword)
        for suite, adapter, _, suite_cases in planned
    ]
    for suite_result in suite_results:
        out("")
        out(f"{suite_result.suite.integration} / {suite_result.suite.name}")
        out("\n".join(table(suite_result, details=True)))
    return RunResult(suite_results)


@dataclass(slots=True)
class _Run:
    """The cases of one rig run, and their results by suite (by identity: a Suite holds dicts) and case id."""

    registry: Any
    tolerance: dict[str, float]
    settle: dict[str, float]
    power: dict[str, str]
    ask: Callable[[str], str] | None
    out: Callable[[str], None]
    # Each suite's options by its id, set before each of its cases.
    options: dict[int, dict[str, bool]] = field(default_factory=dict)
    entry_options: EntryOptions | None = None
    results: dict[tuple[int, str], CaseResult] = field(default_factory=dict)
    busy: dict[str, float] = field(default_factory=dict)  # _CaseRun.busy
    bridge: HueBridge | None = None

    def case_run(self, case: Case, client: HAClient, ask: Callable[[str], str] | None, position: str = "") -> _CaseRun:
        integration = case.suite.integration
        return _CaseRun(
            case,
            client,
            self.registry,
            self.tolerance[integration],
            ask,
            self.power,
            self.out,
            position,
            self.busy,
            self.settle.get(integration, 0.0),
            self.bridge,
        )

    async def run_case(
        self, case: Case, client: HAClient, ask: Callable[[str], str] | None, position: str = ""
    ) -> CaseResult:
        if wanted := self.options.get(id(case.suite)):
            await self.entry_options.apply(wanted)
        return await self.case_run(case, client, ask, position).run()

    def report(self, case: Case, result: CaseResult) -> None:
        self.results[id(case.suite), case.id] = result
        self.out(f"  {case.id}: {result.outcome}" + (f" ({result.detail})" if result.detail else ""))

    async def automated(self, suite: Suite, client: HAClient, suite_cases: list[Case]) -> list[tuple[Case, HAClient]]:
        """Run the suite's automated cases; return the observed ones still to run, with their client."""
        self.out(f"{suite.integration} / {suite.name}")
        waiting = []
        for case in suite_cases:
            twin = self.results.get((id(suite), case.twin or ""))
            if case.skip:
                self.report(case, _not_run(case, Outcome.SKIPPED, case.skip))
            elif not case.observed:
                self.report(case, await self.run_case(case, client, None))
            elif self.ask is None:
                self.report(case, _not_run(case, Outcome.NOT_OBSERVED))
            elif twin is not None and twin.outcome is Outcome.FAIL:
                self.report(case, _not_run(case, Outcome.SKIPPED, "automated case failed"))
            else:
                waiting.append((case, client))
        return waiting

    async def observed(self, waiting: list[tuple[Case, HAClient]]) -> None:
        """Run each observed case in turn; after an EOF at a prompt, the rest are not observed."""
        if waiting:
            self.out("")
            self.out(f"{len(waiting)} test{'s need' if len(waiting) > 1 else ' needs'} you")
        for number, (case, client) in enumerate(waiting, 1):
            if self.ask is None:
                self.report(case, _not_run(case, Outcome.NOT_OBSERVED))
                continue
            result = await self.run_case(case, client, self.ask, f"{number} of {len(waiting)}")
            self.report(case, result)
            if result.outcome is Outcome.NOT_OBSERVED:
                self.ask = None


def _not_run(case: Case, outcome: Outcome, detail: str = "") -> CaseResult:
    domain = case.entities[case.role].partition(".")[0] if case.entities else None
    return CaseResult(case.id, case.role, domain, outcome, detail, twin=case.twin)


# --- Bench records -------------------------------------------------------------------------------------------


def table(suite_result: SuiteResult, details: bool = False) -> list[str]:
    """The pass/fail table, by role and domain: a record is public, so it never names a household entity."""
    lines = ["| Test | Target | Result |", "|---|---|---|"]
    for case in suite_result.cases:
        target = f"`{case.domain}` ({case.role})" if case.domain else f"{case.role}: none in inventory"
        outcome = str(case.outcome) + (f": {case.detail}" if details and case.detail else "")
        lines.append(f"| `{case.id}` | {target} | {outcome} |")
    return lines


@dataclass(frozen=True, slots=True)
class Device:
    model: str | None
    model_id: str | None
    firmware: str | None

    def __str__(self) -> str:
        model_id = f" (`{self.model_id}`)" if self.model_id and self.model_id != self.model else ""
        return f"{self.model or 'unknown model'}{model_id}, firmware `{self.firmware or 'unknown'}`"


async def rig_facts(ha: HAClient, entity_ids: Iterable[str]) -> tuple[str, list[Device]]:
    """HA's version and the devices behind the entities, via registry calls a non-admin token may make."""
    config = await ha.command({"type": "get_config"})
    listed = await ha.command({"type": "config/entity_registry/list_for_display"})
    device_ids = {entry["ei"]: entry.get("di") for entry in listed["entities"]}
    devices = {device["id"]: device for device in await ha.command({"type": "config/device_registry/list"})}
    found: dict[Device, None] = {}
    for entity_id in entity_ids:
        if (device := devices.get(device_ids.get(entity_id))) is not None:
            found[Device(device.get("model"), device.get("model_id"), device.get("sw_version"))] = None
    return config["version"], list(found)


def render_record(
    suite_result: SuiteResult, title: str, ha_version: str, devices: list[Device], date: str, source: str
) -> str:
    """The bench record check_tiers parses: a key/value table, then the per-test table."""
    adapter, suite = suite_result.adapter, suite_result.suite
    path = adapter_path(adapter)
    proven = suite_result.proven
    if not any(case.reached for case in proven):
        capabilities = "none"
    elif adapter.scope.capabilities is None:
        capabilities = "every capability the adapter addresses"
    else:
        reached = sorted({name for case in proven for name in case.capabilities})
        capabilities = ", ".join(f"`{name}`" for name in reached) or "none"
    fields = sorted({name for case in proven for name in case.fields})
    rows = [
        ("Result", "pass"),
        ("Date", date),
        ("Source", source),
        ("Fingerprint", f"`{fingerprint(path)}` (`{path.relative_to(COMPONENT_DIR)}`)"),
        ("Home Assistant", ha_version),
        ("Device", "; ".join(map(str, devices)) or "none"),
        ("Capabilities", capabilities),
        ("Fields", ", ".join(f"`{name}`" for name in fields) or "none"),
    ]
    if suite.file.options:
        rows.append(("Options", ", ".join(f"`{name}`" for name in sorted(suite.file.options))))
    lines = [f"# {title} · {suite.action}", "", "| | |", "|---|---|"]
    lines += [f"| {name} | {value} |" for name, value in rows]
    lines += ["", "## Tests", "", *table(suite_result)]
    if any(case.outcome is Outcome.NOT_OBSERVED for case in suite_result.cases):
        lines += ["", "Tests marked `not observed` had nobody watching; their fields and capabilities are not listed."]
    return "\n".join(lines) + "\n"


def write_report(result: RunResult, directory: Path, title: str) -> Path:
    """Every suite's table with each failure's and skip's reason, for any run: failed, partial or unattended."""
    lines = [f"# {title}"]
    for suite_result in result.suites:
        suite = suite_result.suite
        lines += ["", f"## {suite.integration} / {suite.name}", "", *table(suite_result, details=True)]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{title.replace(' ', '-').replace(':', '')}.md"
    path.write_text("\n".join(lines) + "\n")
    return path


async def write_records(
    result: RunResult, ha: HAClient, registry: Any, bench_dir: Path, date: str, source: str
) -> list[Path]:
    """One record per suite that fully passed; a partial or failed suite writes nothing."""
    written = []
    for suite_result in result.suites:
        if not suite_result.recordable:
            continue
        suite = suite_result.suite
        entity_ids = [entity_id for case in suite_result.cases for entity_id in case.entity_ids]
        ha_version, devices = await rig_facts(ha, entity_ids)
        title = registry.integrations[suite.integration].title
        path = bench_dir / suite.integration / f"{suite.name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_record(suite_result, title, ha_version, devices, date, source))
        written.append(path)
    return written
