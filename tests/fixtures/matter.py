"""Fabricate Matter entities the way the core matter integration registers them, with a mocked client.

matter_server and chip are not installed in the test environment.  This module replaces them with
minimal mocks so the adapter runs and its boundary calls can be inspected.  The mock structure
follows what the adapter reads at runtime:

    hass.config_entries.async_loaded_entries("matter")[0]
        .runtime_data.adapter.matter_client
            .get_node(node_id) -> mock_node
                .node_data.attributes["{endpoint_id}/6/65532"] -> int feature_map
            .send_device_command(node_id, endpoint_id, command) -> None  (AsyncMock)
            .read_attribute(node_id, attribute_path) -> {attribute_path: value}  (AsyncMock)
"""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

_MATTER_DOMAIN = "matter"
# fabric_hex and node_hex are both fixed 16-char hex strings with no hyphens.
FABRIC_HEX = "0000000000000001"
NODE_HEX = "0000000000000002"
NODE_ID = int(NODE_HEX, 16)


def make_node_mock(endpoint_id: int, feature_map: int = 0x0001) -> MagicMock:
    """Return a mock MatterNode whose attribute cache holds one endpoint's OnOff FeatureMap."""
    node = MagicMock()
    node.node_id = NODE_ID
    node.node_data.attributes = {f"{endpoint_id}/6/65532": feature_map}
    return node


def on_time_reads(value: int) -> AsyncMock:
    """A read_attribute mock that answers like python-matter-server: {attribute_path: value}."""
    return AsyncMock(side_effect=lambda node_id, attribute_path: {attribute_path: value})


def matter_device(
    hass: HomeAssistant,
    endpoint_id: int = 1,
    feature_map: int = 0x0001,
) -> tuple[MockConfigEntry, AsyncMock, AsyncMock]:
    """A loaded Matter config entry whose matter_client is fully mocked.

    Returns (entry, send_device_command mock, read_attribute mock).
    """
    send_cmd = AsyncMock(return_value=None)
    read_attr = on_time_reads(1)  # non-zero = timer running

    node_mock = make_node_mock(endpoint_id, feature_map)

    client = MagicMock()
    client.get_node.return_value = node_mock
    client.send_device_command = send_cmd
    client.read_attribute = read_attr

    adapter = SimpleNamespace(matter_client=client)
    entry_data = SimpleNamespace(adapter=adapter)

    entry = MockConfigEntry(domain=_MATTER_DOMAIN, unique_id="mock-matter")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    entry.runtime_data = entry_data
    return entry, send_cmd, read_attr


def add_matter_entity(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    entity_id: str,
    endpoint_id: int = 1,
    state: str = "off",
    attributes: dict | None = None,
    unique_id: str | None = None,
) -> str:
    """Register a Matter light or plug entity with a unique_id that the adapter can parse.

    Unique_id format: {fab_hex16}-{node_hex16}-MatterNodeDevice-{ep}-{key}-6-0, key MatterLight or
    MatterPlug (matches what homeassistant/components/matter/entity.py builds for each). Pass unique_id to
    register one the adapter can't parse.
    """
    domain, object_id = entity_id.split(".")
    key = "MatterPlug" if domain == "switch" else "MatterLight"
    unique_id = unique_id or f"{FABRIC_HEX}-{NODE_HEX}-MatterNodeDevice-{endpoint_id}-{key}-6-0"
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(_MATTER_DOMAIN, f"deviceid_{FABRIC_HEX}-{NODE_HEX}-MatterNodeDevice")},
    )
    er.async_get(hass).async_get_or_create(
        domain,
        _MATTER_DOMAIN,
        unique_id,
        suggested_object_id=object_id,
        config_entry=entry,
        device_id=device.id,
    )
    hass.states.async_set(entity_id, state, attributes or {})
    return entity_id


@pytest.fixture
def mock_chip(monkeypatch):
    """Inject a minimal mock for chip.clusters into sys.modules.

    Allows the lazy `from chip.clusters import Objects as clusters` in addressing.make_on_with_timed_off
    to succeed.  The mock's OnWithTimedOff factory returns a SimpleNamespace so tests can inspect
    the exact onOffControl/onTime/offWaitTime values that the adapter passed.
    """

    def _OnWithTimedOff(onOffControl=0, onTime=0, offWaitTime=0):
        return SimpleNamespace(onOffControl=onOffControl, onTime=onTime, offWaitTime=offWaitTime)

    mock_objects = SimpleNamespace(OnOff=SimpleNamespace(Commands=SimpleNamespace(OnWithTimedOff=_OnWithTimedOff)))
    mock_chip_clusters = SimpleNamespace(Objects=mock_objects)
    mock_chip_pkg = SimpleNamespace(clusters=mock_chip_clusters)

    monkeypatch.setitem(sys.modules, "chip", mock_chip_pkg)
    monkeypatch.setitem(sys.modules, "chip.clusters", mock_chip_clusters)
    # The `from chip.clusters import Objects` form needs .Objects on sys.modules["chip.clusters"].
    return mock_objects
