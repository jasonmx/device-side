"""Fixtures for tests that drive the live rig HA. Collected only under scripts/rig.py, after its approval gate."""

import logging
import os
from dataclasses import dataclass, field

import pytest

from custom_components.device_side.core.registry import AdapterRegistry

from .client import HAClient
from .inventory import TOLERANCE_S, Inventory, load_env

_LOGGER = logging.getLogger(__name__)

# Light attributes a restore puts back, in the order light.turn_on would accept one color at a time.
_RESTORE_COLOR = ("color_temp_kelvin", "hs_color", "xy_color", "rgb_color")


def pytest_collection_modifyitems(config, items):
    # The devices are in-use household lights: nothing here runs unless the runner's gate was passed.
    if os.environ.get("DEVICE_SIDE_RIG_APPROVED") != "1":
        skip = pytest.mark.skip(reason="rig tests run only through scripts/rig.py, after its approval gate")
        for item in items:
            item.add_marker(skip)
    for item in items:
        item.add_marker(pytest.mark.rig)


@pytest.fixture(scope="session")
def inventory() -> Inventory:
    try:
        return Inventory.load()
    except FileNotFoundError:
        pytest.skip("tests/rig/inventory.yaml is absent; copy inventory.example.yaml")


@pytest.fixture(scope="session")
def registry() -> AdapterRegistry:
    return AdapterRegistry.discover()


@pytest.fixture
async def ha():
    env = load_env()
    client = HAClient(env["HA_URL"], env["HA_TOKEN"])
    await client.connect()
    yield client
    await client.close()


@pytest.fixture
def require_adapter(inventory: Inventory, registry: AdapterRegistry):
    """The inventory entity for a role, skipping when the rig has none or the registry lacks the adapter."""

    def _require(platform: str, feature: str, role: str) -> str:
        if registry.adapter(feature, platform) is None:
            pytest.skip(f"no {feature} adapter on {platform}")
        if (entity_id := inventory.entity(platform, role)) is None:
            pytest.skip(f"inventory has no {platform} entity with role {role}")
        return entity_id

    return _require


@pytest.fixture
def timing():
    def _tolerance(platform: str) -> float:
        return TOLERANCE_S[platform]

    return _tolerance


@dataclass(slots=True)
class Snapshot:
    ha: HAClient
    taken: dict[str, dict | None] = field(default_factory=dict)

    async def take(self, entity_id: str) -> dict | None:
        if entity_id not in self.taken:
            self.taken[entity_id] = await self.ha.get_state(entity_id)
        return self.taken[entity_id]

    async def restore(self) -> None:
        for entity_id, state in self.taken.items():
            if state is None or state["state"] not in ("on", "off"):
                continue
            domain = entity_id.partition(".")[0]
            try:
                if state["state"] == "off":
                    await self.ha.call_service(domain, "turn_off", {"entity_id": entity_id})
                    continue
                data = {"entity_id": entity_id}
                if domain == "light":
                    attributes = state["attributes"]
                    if attributes.get("brightness") is not None:
                        data["brightness"] = attributes["brightness"]
                    for name in _RESTORE_COLOR:
                        if attributes.get(name) is not None:
                            data[name] = attributes[name]
                            break
                await self.ha.call_service(domain, "turn_on", data)
            except Exception as err:  # noqa: BLE001 - a failed restore is logged so it can't mask the test result
                _LOGGER.warning("Could not restore %s to %s: %s", entity_id, state["state"], err)


@pytest.fixture
async def snapshot(ha: HAClient):
    """Records each touched entity's state before the test and puts it back afterwards."""
    snap = Snapshot(ha)
    yield snap
    await snap.restore()
