"""Fabricate a Hue bridge and its HA entities the way the core hue integration registers them.

The bridge is a real aiohue HueBridgeV2 loaded from CLIP v2 resource dicts, so adapters read real aiohue models;
its request() is replaced, so writes are recorded as the PUTs that would go to the bridge.
"""

from types import SimpleNamespace

from aiohue.v2 import HueBridgeV2
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

MIREK_SCHEMA = {"mirek_minimum": 153, "mirek_maximum": 454}

# The bridge and its device: aiohue checks the software version before a grouped_light write.
BRIDGE_RESOURCES = [
    {"id": "bridge", "type": "bridge", "bridge_id": "001788fffe000000", "time_zone": {"time_zone": "UTC"}},
    {
        "id": "device-bridge",
        "type": "device",
        "services": [{"rid": "bridge", "rtype": "bridge"}],
        "product_data": {
            "model_id": "BSB002",
            "manufacturer_name": "Signify Netherlands B.V.",
            "product_name": "Hue Bridge",
            "product_archetype": "bridge_v2",
            "certified": True,
            "software_version": "1.70.1970000000",
        },
        "metadata": {"archetype": "bridge_v2", "name": "Bridge"},
    },
]


class HueBridge:
    """Resources to load, PUTs sent, and light ids whose writes the bridge refuses."""

    def __init__(self) -> None:
        self.resources: list[dict] = []
        self.puts: list[tuple[str, dict]] = []
        self.failing: set[str] = set()
        self.api: HueBridgeV2 | None = None

    def light(
        self,
        light_id: str,
        *,
        on: bool = False,
        brightness: float | None = 50.0,
        mirek: int | None = 370,
        mirek_valid: bool = True,
        xy: tuple[float, float] | None = None,
        gamut: dict | None = None,
        mirek_schema: dict = MIREK_SCHEMA,
    ) -> str:
        """A bulb and its device. brightness/mirek/xy None leave out the dimming/color_temperature/color feature;
        gamut is the color feature's red/green/blue points, left out when None."""
        device_id = f"device-{light_id}"
        light: dict = {
            "id": light_id,
            "type": "light",
            "owner": {"rid": device_id, "rtype": "device"},
            "on": {"on": on},
            "mode": "normal",
        }
        if brightness is not None:
            light["dimming"] = {"brightness": brightness}
        if mirek is not None:
            light["color_temperature"] = {"mirek": mirek, "mirek_valid": mirek_valid, "mirek_schema": mirek_schema}
        if xy is not None:
            light["color"] = {"xy": {"x": xy[0], "y": xy[1]}, "gamut_type": "C"}
            if gamut is not None:
                light["color"]["gamut"] = gamut
        device = {
            "id": device_id,
            "type": "device",
            "services": [{"rid": light_id, "rtype": "light"}],
            "product_data": {
                "model_id": "LCT015",
                "manufacturer_name": "Signify Netherlands B.V.",
                "product_name": "Hue color lamp",
                "product_archetype": "sultan_bulb",
                "certified": True,
                "software_version": "1.0.0",
            },
            "metadata": {"archetype": "sultan_bulb", "name": light_id},
        }
        self.resources += [device, light]
        return light_id

    def room(self, grouped_light_id: str, light_ids: list[str], *, brightness: float | None = None) -> str:
        """A room over the lights' devices and its grouped_light; brightness is what the bridge reports for it."""
        room_id = f"room-{grouped_light_id}"
        on = any(r["on"]["on"] for r in self.resources if r["type"] == "light" and r["id"] in light_ids)
        grouped: dict = {"id": grouped_light_id, "type": "grouped_light", "owner": {"rid": room_id, "rtype": "room"}}
        grouped["on"] = {"on": on}
        if brightness is not None:
            grouped["dimming"] = {"brightness": brightness}
        room = {
            "id": room_id,
            "type": "room",
            "children": [{"rid": f"device-{light_id}", "rtype": "device"} for light_id in light_ids],
            "services": [{"rid": grouped_light_id, "rtype": "grouped_light"}],
            "metadata": {"archetype": "living_room", "name": "Room"},
        }
        self.resources += [room, grouped]
        return grouped_light_id

    def scene(self, scene_id: str, actions: list[dict], smart: bool = False) -> str:
        """actions: (rid, rtype, action) as the CLIP API lists them; a smart scene has timeslots instead."""
        scene: dict = {
            "id": scene_id,
            "type": "smart_scene" if smart else "scene",
            "metadata": {"name": scene_id},
            "group": {"rid": "room-1", "rtype": "room"},
        }
        if smart:
            scene |= {"week_timeslots": [], "state": "inactive"}
        else:
            scene |= {"actions": actions, "speed": 0.5}
        self.resources.append(scene)
        return scene_id

    async def load(self) -> HueBridgeV2:
        api = HueBridgeV2("bridge.invalid", "app-key")
        api.request = self._request
        for controller in (api.devices, api.lights, api.groups, api.scenes, api.config):
            await controller.initialize([*self.resources, *BRIDGE_RESOURCES])
        self.api = api
        return api

    async def _request(self, method: str, path: str, json: dict | None = None, **kwargs) -> list[dict]:
        if method == "put":
            self.puts.append((path.removeprefix("clip/v2/resource/"), json))
            if path.rpartition("/")[2] in self.failing:
                raise RuntimeError("bridge refused the write")
        return []


def light_action(rid: str, rtype: str = "light", **action) -> dict:
    return {"target": {"rid": rid, "rtype": rtype}, "action": action}


async def hue_entry(hass: HomeAssistant, bridge: HueBridge, api_version: int = 2) -> MockConfigEntry:
    """A loaded hue entry whose runtime_data is the bridge, as core's HueBridge carries it."""
    entry = MockConfigEntry(domain="hue")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    entry.runtime_data = SimpleNamespace(api=await bridge.load(), api_version=api_version)
    return entry


def add_hue_entity(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    entity_id: str,
    resource_id: str,
    state: str = "off",
    attributes: dict | None = None,
) -> str:
    """A light, room or scene entity; core's hue integration uses the bridge resource id as the unique_id."""
    domain, object_id = entity_id.split(".")
    er.async_get(hass).async_get_or_create(
        domain, "hue", resource_id, suggested_object_id=object_id, config_entry=entry
    )
    hass.states.async_set(entity_id, state, attributes or {})
    return entity_id


def add_hue_group(
    hass: HomeAssistant, entry: MockConfigEntry, entity_id: str, grouped_light_id: str, members: list[str]
) -> str:
    """A room or zone light, with the attributes core's hue integration gives one."""
    return add_hue_entity(
        hass, entry, entity_id, grouped_light_id, state="on", attributes={"is_hue_group": True, "entity_id": members}
    )
