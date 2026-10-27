"""Fakes shared by the rig's tests: a fake HAClient (and its admin twin, with device_side's options flow), a
registry whose adapters all take options, and the step files that tests/scripts/test_rig.py reuses."""

import asyncio
import copy
from collections.abc import Callable
from types import SimpleNamespace

from tests.rig.inventory import Inventory, RigEntity

PENDING: list[asyncio.TimerHandle | asyncio.Task] = []


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
        # HA keeps an entity's name whatever its state; every other attribute is the new state's own.
        if name := self.states.get(entity_id, {}).get("attributes", {}).get("friendly_name"):
            attributes = {"friendly_name": name} | attributes
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


def inventory(integration: str = "shelly", **roles: str) -> Inventory:
    entities = [RigEntity(entity_id, frozenset({role})) for role, entity_id in roles.items()]
    return Inventory({integration: entities})


OPTION_REGISTRY = SimpleNamespace(
    adapter=lambda action, integration: SimpleNamespace(
        scope=SimpleNamespace(
            confirmable=False, capabilities=None, fields=frozenset(), options=frozenset({"opt", "other"})
        )
    )
)


class FakeAdmin(FakeHA):
    """FakeHA plus device_side's entry and its options flow, which saves what it is sent."""

    def __init__(self, states: dict[str, dict], respond: Callable | None = None, options: dict | None = None):
        super().__init__(states, respond)
        self.options = {"opt": True, "other": False} | (options or {})
        self.saved: list[dict] = []
        self.aborted = 0

    async def command(self, payload: dict):
        if payload["type"] == "config_entries/get":
            return [{"entry_id": "e1", "state": "loaded"}]
        return await super().command(payload)

    async def rest(self, method: str, path: str, json: dict | None = None):
        if path.endswith("/options/flow"):
            schema = [{"name": name, "default": value, "type": "boolean"} for name, value in self.options.items()]
            return {"type": "form", "flow_id": "f1", "data_schema": schema}
        if method == "delete":
            self.aborted += 1
            return {"message": "Flow aborted"}
        self.options = dict(json)
        self.saved.append(dict(json))
        return {"type": "create_entry"}


RESTORED_MIDWAY = """
action: move
rig_seconds: 5
tests:
  - name: t
    roles: [light_ct]
    steps:
      - set: {state: off}
      - restore: null
      - set: {state: off}
"""
WAITING_MIDWAY = RESTORED_MIDWAY.replace("      - restore: null\n", "      - wait: 30\n")
