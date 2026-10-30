from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util.color import color_hs_to_xy
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.device_side.integrations.zha import zcl
from custom_components.device_side.integrations.zha.fade import transition_cache

from ...fixtures.zha import IEEE, add_zha_entity, zha_entry, zha_group

SENT = {"status": "sent", "integration": "zha"}
A, B = "00:00:00:00:00:00:00:0a", "00:00:00:00:00:00:00:0b"
COLOR_MODES = ["color_temp", "xy"]
# MoveToLevel to 1 with ExecuteIfOff: a light that is off, put at the bottom before a raise.
BOTTOM = (0x0008, 0x00, {"level": 1, "transition_time": 0, "options_mask": 1, "options_override": 1})


def unchanged(detail: str) -> dict:
    return {"status": "unchanged", "integration": "zha", "detail": detail}


@pytest.fixture(autouse=True)
async def unload_mock_zha_entries(hass):
    """Mark mocked ZHA entries not loaded before teardown, so HA doesn't import the real zha to unload them."""
    yield
    for entry in hass.config_entries.async_entries("zha"):
        entry.mock_state(hass, ConfigEntryState.NOT_LOADED)


@pytest.fixture
def zha_groups(monkeypatch) -> dict:
    """The fake zha gateway's groups by ID; the gateway answers get_group from it."""
    groups: dict = {}
    monkeypatch.setattr(zcl, "gateway", lambda hass: SimpleNamespace(get_group=groups.get))
    return groups


class Clock:
    """A transition cache clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(hass, setup_production) -> Clock:
    clock = Clock()
    transition_cache(hass).clock = clock
    return clock


@pytest.fixture
def commands(hass):
    return async_mock_service(hass, "zha", "issue_zigbee_cluster_command")


@pytest.fixture
def group_commands(hass):
    return async_mock_service(hass, "zha", "issue_zigbee_group_command")


@pytest.fixture
def refreshes(hass):
    return async_mock_service(hass, "homeassistant", "update_entity")


def bulb(
    hass,
    entity_id: str = "light.bulb",
    ieee: str = IEEE,
    *,
    state: str = "on",
    brightness: int = 153,  # 60 %
    hs: tuple[float, float] = (200.0, 60.0),
    modes: list[str] | None = None,
    model: str | None = None,
) -> str:
    entries = hass.config_entries.async_entries("zha")
    entry = entries[0] if entries else zha_entry(hass)
    attributes: dict = {"supported_color_modes": COLOR_MODES if modes is None else modes}
    if state == "on":
        attributes |= {"brightness": brightness, "hs_color": hs}
    add_zha_entity(hass, entry, entity_id, ieee=ieee, state=state, attributes=attributes)
    if model is not None:
        device_id = er.async_get(hass).async_get(entity_id).device_id
        dr.async_get(hass).async_update_device(device_id, model=model)
    return entity_id


def sent(commands) -> list[tuple[int, int, dict]]:
    return [(command.data["cluster_id"], command.data["command"], command.data["params"]) for command in commands]


def to(commands) -> list[str]:
    return [command.data["ieee"] for command in commands]


@pytest.fixture
def two_light_group(hass, zha_groups):
    """light.zha_group, ZHA group 2, of light.a and light.b."""
    entry = zha_entry(hass)
    add_zha_entity(hass, entry, "light.zha_group", unique_id="light_zha_group_0x0002")
    zha_groups[2] = zha_group((A, 11), (B, 11))
    return entry


class Bulbs:
    """zcl.read_attributes for raise, lower and stop: OnOff reads off (a soft off has run), and CurrentLevel answers
    only where a test sets `levels`, so a fade's ramp is fitted to a read only then."""

    def __init__(self) -> None:
        self.on = False
        self.levels: dict[str, int] = {}
        self.read = AsyncMock(side_effect=self._read)

    async def _read(self, hass, addr, cluster_id, attributes, optional=()):
        if cluster_id == zcl.ON_OFF_CLUSTER:
            return {zcl.ON_OFF: self.on}
        if addr.ieee not in self.levels:
            raise LookupError("no answer")
        return {zcl.CURRENT_LEVEL: self.levels[addr.ieee]}


@pytest.fixture
def bulbs(monkeypatch) -> Bulbs:
    fake = Bulbs()
    monkeypatch.setattr(zcl, "read_attributes", fake.read)
    monkeypatch.setattr(zcl, "enhanced_hue", AsyncMock(return_value=True))
    return fake


def on_off_reads(read) -> list:
    """The OnOff reads among the reads, leaving out the Level reads each brightness fade fits its ramp to."""
    return [call for call in read.await_args_list if call.args[2] == zcl.ON_OFF_CLUSTER]


def xy(hue: float, saturation: float) -> dict:
    x, y = color_hs_to_xy(hue, saturation)
    return {"color_x": round(x * 65535), "color_y": round(y * 65535)}
