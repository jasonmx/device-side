"""Fabricate Shelly entities the way the core shelly integration registers them, with a mocked RPC device."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

MAC = "AABBCCDDEEFF"


# When a fixture timer starts, on the device's clock: 2026-10-27T12:00:00Z.
TIMER_STARTED_AT = 1793102400.0


def timer_running(status: dict | None = None):
    """call_rpc side effect: Set returns the API's result; GetStatus reports `status` (an RGBCCT bulb's brightness,
    mode, ct and rgb, say) under the output and any timer the last Set started, at TIMER_STARTED_AT."""
    sets: dict[tuple[str, int], dict] = {}

    def respond(method: str, params: dict) -> dict:
        component, _, verb = method.partition(".")
        key = (component, params["id"])
        if verb == "GetStatus":
            return {"id": params["id"], "output": False, **(status or {}), **sets.get(key, {})}
        sets[key] = {"output": params["on"]}
        if "toggle_after" in params:
            sets[key] |= {"timer_started_at": TIMER_STARTED_AT, "timer_duration": params["toggle_after"]}
        return {"was_on": not params["on"]}

    return respond


def shelly_device(
    hass: HomeAssistant, gen1: bool = False, mac: str = MAC, status: dict | None = None
) -> tuple[MockConfigEntry, AsyncMock]:
    """A loaded Shelly entry whose runtime_data.rpc.device.call_rpc is the returned mock; status as timer_running's."""
    call_rpc = AsyncMock(side_effect=timer_running(status))
    entry = MockConfigEntry(domain="shelly", unique_id=mac)
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    rpc = None if gen1 else SimpleNamespace(device=SimpleNamespace(call_rpc=call_rpc))
    entry.runtime_data = SimpleNamespace(rpc=rpc, block=SimpleNamespace() if gen1 else None)
    return entry, call_rpc


def add_shelly_entity(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    entity_id: str,
    key: str,
    state: str = "off",
    attributes: dict | None = None,
) -> str:
    """key is the RPC key (switch:0, light:0, rgbcct:0) or, for Gen1 and non-timer entities, any unique_id suffix."""
    domain, object_id = entity_id.split(".")
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, connections={(dr.CONNECTION_NETWORK_MAC, entry.unique_id)}
    )
    er.async_get(hass).async_get_or_create(
        domain,
        "shelly",
        f"{entry.unique_id}-{key}",
        suggested_object_id=object_id,
        config_entry=entry,
        device_id=device.id,
    )
    hass.states.async_set(entity_id, state, attributes or {})
    return entity_id
