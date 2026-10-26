"""Runs the rig's YAML step files against the live HA and renders bench records from the results.

One file per action (`steps/<action>.yaml`) runs on every inventory integration that has that action's adapter.
The registry supplies what differs per integration: the expected status, the tolerance and the fields in scope.
No pytest here: scripts/rig.py calls run(), and a tester's one-file runner can import this module unchanged.
"""

import ast
import asyncio
import logging
import operator
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from scripts.fingerprint import adapter_path, fingerprint

from .client import HAClient, HAError
from .inventory import RIG_DIR, ROLES, TOLERANCE_S, Inventory

_LOGGER = logging.getLogger(__name__)

STEPS_DIR = RIG_DIR / "steps"
COMPONENT_DIR = RIG_DIR.parents[1] / "custom_components" / "device_side"

# Light attributes a restore puts back, in the order light.turn_on would accept one color at a time.
_RESTORE_COLOR = ("color_temp_kelvin", "hs_color", "xy_color", "rgb_color")

# Integrations whose adapter calls an admin-only action with the caller's context, so their suites run on
# HA_ADMIN_TOKEN. ZHA: issue_zigbee_cluster_command is registered with async_register_admin_service.
ADMIN_INTEGRATIONS = frozenset({"zha"})

# Statuses that mean the command reached the device.
_REACHED = frozenset({"confirmed", "sent"})

# An entity whose supply a case switched rejoins its network after power returns. ZHA keeps showing the last state
# of a mains device for hours, so the restore waits, then retries until the device takes the command.
POWER_SETTLE_S = 5.0
POWER_REJOIN_S = 60.0
POWER_RETRY_S = 3.0


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
class RigTest:
    name: str
    roles: tuple[str, ...]
    only: frozenset[str] | None
    steps: tuple[Step, ...]

    def roles_needed(self, role: str) -> list[str]:
        """The case's own role and every role a step targets, in first-use order."""
        targets = (step.args.get("target") for step in self.steps if isinstance(step.args, dict))
        return list(dict.fromkeys([role, *filter(None, targets)]))


@dataclass(frozen=True, slots=True)
class StepFile:
    path: Path
    action: str
    rig_seconds: int
    tests: tuple[RigTest, ...]

    @property
    def roles(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(role for test in self.tests for role in test.roles))


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
    args = _mapping(args, required=["attribute", "for"], allowed=["target", "every", "expect", "min", "max"])
    args["for"] = Expr.parse(args["for"])
    args["every"] = Expr.parse(args.get("every", 0.5))
    if args.get("expect", "rising") not in ("rising", "falling", "steady"):
        raise ValueError(f"expect must be rising, falling or steady, got {args['expect']!r}")
    return args


def _parse_observe(args: Any) -> str:
    if not isinstance(args, str) or not args.strip():
        raise ValueError("observe takes the question to ask, as a string")
    return args.strip()


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
    "observe": _parse_observe,
    "restore": _parse_restore,
}


def _parse_step(raw: Any, index: int) -> Step:
    if not isinstance(raw, dict) or len(raw) != 1:
        raise ValueError(f"step {index}: expected one `kind: args` mapping, got {raw!r}")
    ((kind, args),) = raw.items()
    label = f"step {index} ({kind})"
    if kind not in PARSERS:
        raise ValueError(f"{label}: unknown step; use one of {', '.join(PARSERS)}")
    try:
        return Step(kind, PARSERS[kind](args), label)
    except ValueError as err:
        raise ValueError(f"{label}: {err}") from None


def _parse_test(raw: Any) -> RigTest:
    if not isinstance(raw, dict) or not isinstance(name := raw.get("name"), str):
        raise ValueError(f"a test needs a name, got {raw!r}")
    try:
        if unknown := sorted(set(raw) - {"name", "roles", "only", "steps"}):
            raise ValueError(f"unknown key(s) {', '.join(unknown)}")
        roles = raw.get("roles")
        if not isinstance(roles, list) or not roles:
            raise ValueError("roles must be a non-empty list")
        if unknown := sorted(set(roles) - ROLES):
            raise ValueError(f"unknown role(s) {', '.join(unknown)}")
        only = raw.get("only")
        if only is not None and (not isinstance(only, list) or not only):
            raise ValueError("only must be a non-empty list of integration keys")
        if not isinstance(steps := raw.get("steps"), list) or not steps:
            raise ValueError("steps must be a non-empty list")
        parsed = tuple(_parse_step(step, index) for index, step in enumerate(steps, 1))
    except ValueError as err:
        raise ValueError(f"test {name}, {err}") from None
    return RigTest(name, tuple(roles), frozenset(only) if only else None, parsed)


def load_step_file(path: Path) -> StepFile:
    try:
        raw = yaml.safe_load(path.read_text())
        if not isinstance(raw, dict):
            raise ValueError("expected a mapping with action, rig_seconds and tests")
        if unknown := sorted(set(raw) - {"action", "rig_seconds", "tests"}):
            raise ValueError(f"unknown key(s) {', '.join(unknown)}")
        if not isinstance(action := raw.get("action"), str):
            raise ValueError("action must name the device_side action under test")
        if isinstance(seconds := raw.get("rig_seconds"), bool) or not isinstance(seconds, int) or seconds <= 0:
            raise ValueError("rig_seconds must be a positive whole number")
        if not isinstance(raw_tests := raw.get("tests"), list) or not raw_tests:
            raise ValueError("tests must be a non-empty list")
        tests = tuple(_parse_test(test) for test in raw_tests)
        if duplicates := sorted({t.name for t in tests if [u.name for u in tests].count(t.name) > 1}):
            raise ValueError(f"duplicate test name(s) {', '.join(duplicates)}")
    except (ValueError, yaml.YAMLError) as err:
        raise SchemaError(f"{path.name}: {err}") from None
    return StepFile(path, action, seconds, tests)


def load_step_files(steps_dir: Path = STEPS_DIR) -> list[StepFile]:
    """Every `<action>.yaml` directly in steps_dir; `examples/` below it is for the parser tests only."""
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


@dataclass(frozen=True, slots=True)
class Case:
    """One test on one role: the entities it moves, or why it is skipped."""

    suite: Suite
    test: RigTest
    role: str
    entities: dict[str, str]
    skip: str | None = None

    @property
    def id(self) -> str:
        return f"{self.test.name}[{self.role}]"


def cases(suite: Suite, inventory: Inventory, keyword: str | None = None) -> list[Case]:
    """The suite's cases in file order; `keyword` keeps only case ids containing it."""
    result = []
    for test in suite.file.tests:
        if test.only is not None and suite.integration not in test.only:
            continue
        for role in test.roles:
            case = Case(suite, test, role, {})
            if keyword and keyword not in case.id:
                continue
            entities = {needed: inventory.entity(suite.integration, needed) for needed in test.roles_needed(role)}
            if missing := [needed for needed, entity_id in entities.items() if entity_id is None]:
                result.append(Case(suite, test, role, {}, f"no {missing[0]} entity in inventory"))
            else:
                result.append(Case(suite, test, role, entities))
    return result


# --- Running -------------------------------------------------------------------------------------------------


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
    # Fields in the adapter's scope that a call carried to the device, and whether any call reached it.
    fields: frozenset[str] = frozenset()
    reached: bool = False


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
        """Cases whose every step was checked, observed ones included: only these go into a record's scope."""
        return [case for case in self.cases if case.outcome is Outcome.PASS]


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

    async def take(self, entity_id: str) -> dict | None:
        """The entity's state before the case moved it, and that of every entity it powers."""
        if entity_id not in self.taken:
            state = self.taken[entity_id] = await self.ha.get_state(entity_id)
            if self.device_side and _is_off_light(entity_id, state):
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


class _CaseRun:
    """The steps of one case, against one HA connection, with what earlier steps left behind."""

    def __init__(
        self,
        case: Case,
        ha: HAClient,
        registry: Any,
        tolerance: float,
        ask: Callable[[str], str] | None,
        power: dict[str, str] | None = None,
    ):
        self.case, self.ha, self.registry, self.ask = case, ha, registry, ask
        self.integration = case.suite.integration
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
        self.unobserved = False

    def entity(self, args: Any) -> str:
        role = args.get("target") if isinstance(args, dict) else None
        return self.case.entities[role or self.case.role]

    def is_group(self, entity_id: str) -> bool:
        return self.case.entities.get("group") == entity_id

    async def members(self, entity_id: str) -> list[str]:
        """A group's member lights, from its `entity_id` attribute; any other entity is its own one member."""
        if not self.is_group(entity_id):
            return [entity_id]
        state = await self.ha.get_state(entity_id)
        members = state and state["attributes"].get("entity_id")
        if not isinstance(members, list) or not members:
            raise StepFailure(f"{entity_id} lists no members in its entity_id attribute")
        return members

    async def touch(self, entity_id: str) -> None:
        """Snapshot the entity, and a group's members after it, so a restore puts each member back last."""
        await self.snapshot.take(entity_id)
        if self.is_group(entity_id):
            for member in await self.members(entity_id):
                await self.snapshot.take(member)

    async def run(self) -> CaseResult:
        case = self.case
        domain = case.entities[case.role].partition(".")[0]
        result = CaseResult(case.id, case.role, domain, Outcome.PASS, entity_ids=tuple(case.entities.values()))
        steps = case.test.steps
        try:
            await self.check_power()
            for index, step in enumerate(steps):
                following = steps[index + 1].kind if index + 1 < len(steps) else None
                try:
                    await getattr(self, f"_{step.kind}")(step.args, following)
                except StepFailure as err:
                    raise StepFailure(f"{step.label}: {err}") from None
                except Exception as err:  # noqa: BLE001 - any error ends the case as a fail, not the run
                    raise StepFailure(f"{step.label}: {type(err).__name__}: {err}") from None
        except StepFailure as err:
            result.outcome, result.detail = Outcome.FAIL, str(err)
        else:
            if self.unobserved:
                result.outcome = Outcome.NOT_OBSERVED
        finally:
            await self.snapshot.restore()
        result.fields, result.reached = frozenset(self.fields), self.reached
        return result

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
        entries = [entry for entry in (self.response or {}).values() if isinstance(entry, dict)]
        # A query returns only the targets it read, as core does, with no status to check.
        if entries and (self.query or any(entry.get("status") in _REACHED for entry in entries)):
            self.reached = True
            if (adapter := self.registry.adapter(action, self.integration)) is not None:
                self.fields |= set(data) & adapter.scope.fields

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
        """Poll an attribute for `for` seconds; an absent attribute (a light that is off) reads as 0."""
        entity_id, attribute = self.entity(args), args["attribute"]
        loop = asyncio.get_running_loop()
        deadline = loop.time() + args["for"].eval(self.names)
        every = max(args["every"].eval(self.names), 0.05)
        readings: list[float] = []
        while True:
            state = await self.ha.get_state(entity_id)
            value = state["attributes"].get(attribute) if state else None
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

    async def _observe(self, question: str, _following: str | None) -> None:
        if self.ask is None:
            self.unobserved = True
            return
        try:
            answer = await asyncio.to_thread(self.ask, f"    {question} [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            raise StepFailure(f"not seen: {question}")

    async def _restore(self, _args: None, _following: str | None) -> None:
        await self.snapshot.restore()


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
    out: Callable[[str], None] = print,
) -> RunResult:
    """Run every case in order and print the table; ADMIN_INTEGRATIONS run on `admin`. `ask=None` is --unattended."""
    results, power = [], inventory.power()
    for suite in suites:
        adapter = registry.adapter(suite.action, suite.integration)
        if adapter is None:
            out(f"{suite.integration} / {suite.action}: no adapter, skipped")
            continue
        client = admin if suite.integration in ADMIN_INTEGRATIONS else ha
        if client is None:
            out(f"{suite.integration} / {suite.action}: needs HA_ADMIN_TOKEN, skipped")
            continue
        suite_result = SuiteResult(suite, adapter, [], complete=not keyword)
        out(f"{suite.integration} / {suite.action}")
        for case in cases(suite, inventory, keyword):
            if case.skip:
                result = CaseResult(case.id, case.role, None, Outcome.SKIPPED, case.skip)
            else:
                result = await _CaseRun(case, client, registry, tolerance[suite.integration], ask, power).run()
            out(f"  {case.id}: {result.outcome}" + (f" ({result.detail})" if result.detail else ""))
            suite_result.cases.append(result)
        results.append(suite_result)
    run_result = RunResult(results)
    for suite_result in results:
        out("")
        out(f"{suite_result.suite.integration} / {suite_result.suite.action}")
        out("\n".join(table(suite_result, details=True)))
    return run_result


# --- Bench records -------------------------------------------------------------------------------------------


def table(suite_result: SuiteResult, details: bool = False) -> list[str]:
    """The pass/fail table, by role and domain: a record is public, so it never names a household entity."""
    lines = ["| Test | Target | Result |", "|---|---|---|"]
    for case in suite_result.cases:
        target = f"`{case.domain}` ({case.role})" if case.domain else f"{case.role}: none in inventory"
        outcome = str(case.outcome) + (f": {case.detail}" if details and case.outcome is Outcome.FAIL else "")
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
        capabilities = ", ".join(f"`{name}`" for name in sorted(adapter.scope.capabilities))
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
    lines = [f"# {title} · {suite.action}", "", "| | |", "|---|---|"]
    lines += [f"| {name} | {value} |" for name, value in rows]
    lines += ["", "## Tests", "", *table(suite_result)]
    if any(case.outcome is Outcome.NOT_OBSERVED for case in suite_result.cases):
        lines += ["", "Tests marked `not observed` ran unattended; their fields and capabilities are not listed."]
    return "\n".join(lines) + "\n"


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
        path = bench_dir / suite.integration / f"{suite.action}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_record(suite_result, title, ha_version, devices, date, source))
        written.append(path)
    return written
