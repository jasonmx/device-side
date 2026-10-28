"""Zigbee2MQTT color modes: full-color lights and their groups announced to HA with both color modes."""

import asyncio
import json
import logging
from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.device_side.const import CONF_Z2M_COLOR_MODES, DOMAIN
from custom_components.device_side.integrations.zigbee2mqtt import color_modes
from custom_components.device_side.integrations.zigbee2mqtt.color_modes import (
    both_modes,
    default_modes,
    ensure_color_modes,
    light_expose,
    qualifies,
    wanted,
)

from ...conftest import wall_clock_now
from ...fixtures.z2m import GROUPS, IEEE, INFO

DEVICES = "zigbee2mqtt/bridge/devices"
DEVICE_REQUEST = "zigbee2mqtt/bridge/request/device/options"
GROUP_REQUEST = "zigbee2mqtt/bridge/request/group/options"
LOGGER = "custom_components.device_side.integrations.zigbee2mqtt.color_modes"
OTHER = "0x00124b00aaaaaaaa"
CT_ONLY = "0x00124b00bbbbbbbb"


def light(*names: str, endpoint: str | None = None) -> dict:
    expose = {"type": "light", "features": [{"name": "state"}, {"name": "brightness"}, *({"name": n} for n in names)]}
    return expose | ({"endpoint": endpoint} if endpoint else {})


def device(ieee: str, *exposes: dict, name: str | None = None) -> dict:
    return {"ieee_address": ieee, "friendly_name": name or ieee, "definition": {"exposes": list(exposes)}}


FULL = light("color_temp", "color_xy", "color_hs")
ON = {"homeassistant": {"light": {"supported_color_modes": ["xy", "hs", "color_temp"]}}}
OFF = {"homeassistant": {"light": {"supported_color_modes": ["xy", "color_temp"]}}}


def overrides(modes: list[str] | None) -> dict:
    return {"homeassistant": {"light": {"supported_color_modes": modes}}}


@pytest.fixture
def z2m(broker):
    """Z2M with one full-color bulb, one more, a color temperature bulb, and their groups."""
    broker.retained[DEVICES] = [
        {"ieee_address": "0x0000", "type": "Coordinator", "definition": None},
        device(IEEE, FULL, name="lamp"),
        device(OTHER, light("color_xy", "color_hs")),
        device(CT_ONLY, light("color_temp")),
    ]
    broker.retained[GROUPS] = [
        {"id": 1, "friendly_name": "color pair", "members": [{"ieee_address": IEEE}, {"ieee_address": OTHER}]},
        {"id": 2, "friendly_name": "mixed", "members": [{"ieee_address": IEEE}, {"ieee_address": CT_ONLY}]},
        {"id": 3, "friendly_name": "empty", "members": []},
    ]
    return broker


async def settle(hass) -> None:
    """Let the passes device_side runs in the background finish."""
    await hass.async_block_till_done(wait_background_tasks=True)


async def advance(hass, start, seconds: float) -> None:
    """Fire the debounce timers due by start + seconds and let the passes they start finish."""
    async_fire_time_changed(hass, start + timedelta(seconds=seconds))
    await settle(hass)


def sent(broker) -> dict[tuple[str, str], dict]:
    return {(r["topic"].split("/")[-2], r["payload"]["id"]): r["payload"]["options"] for r in broker.requests()}


@pytest.mark.parametrize(
    ("definition", "expected"),
    [
        ({"exposes": [FULL]}, True),
        ({"exposes": [light("color_hs", "color_xy")]}, True),
        ({"exposes": [light("color_xy")]}, False),
        ({"exposes": [light("color_hs")]}, False),
        ({"exposes": [light("color_temp")]}, False),
        ({"exposes": [{"type": "switch", "features": []}]}, False),
        ({"exposes": [light("color_xy", "color_hs", endpoint="l1")]}, False),
        ({"exposes": [light("color_xy", "color_hs"), light("color_xy", "color_hs")]}, False),
        (None, False),
    ],
)
def test_qualifies_only_a_single_light_with_both_color_models(definition, expected):
    assert qualifies(light_expose(definition)) is expected


def test_both_modes_add_color_temp_only_where_exposed():
    assert both_modes([FULL]) == ["xy", "hs", "color_temp"]
    assert both_modes([light("color_xy", "color_hs")]) == ["xy", "hs"]
    assert both_modes([light("color_xy", "color_hs"), FULL]) == ["xy", "hs", "color_temp"]


@pytest.mark.parametrize(
    ("exposes", "expected"),
    [
        ([FULL], ["xy", "color_temp"]),
        ([light("color_hs", "color_xy")], ["hs"]),
        ([light("color_xy", "color_hs"), light("color_hs", "color_xy", "color_temp")], ["hs", "color_temp"]),
        ([light("color_hs")], ["hs"]),
        ([light("color_temp")], ["color_temp"]),
    ],
)
def test_default_modes_match_z2m_discovery(exposes, expected):
    assert default_modes(exposes) == expected


@pytest.mark.parametrize(
    ("current", "enabled", "expected"),
    [
        ({}, True, ON),
        ({"homeassistant": {"name": "Lamp", "light": {"name": "Main"}}}, True, ON),
        (OFF, True, ON),
        (overrides(["color_temp", "hs", "xy"]), True, {}),  # ours, in another order
        (ON, False, OFF),
        (OFF, False, {}),
        ({}, False, {}),
        (overrides(["hs", "color_temp"]), True, {}),  # the user's own
        (overrides(["hs", "color_temp"]), False, {}),
        (overrides(None), True, {}),  # the user strips the modes from discovery
        ({"homeassistant": {"light": None}}, True, {}),  # the light isn't announced
        ({"homeassistant": None}, True, {}),  # the device isn't announced
        ({"homeassistant": {"light": "odd"}}, True, {}),
    ],
)
def test_wanted_writes_only_device_sides_own_values(current, enabled, expected):
    assert wanted(current, [FULL], enabled) == expected


async def test_enabled_announces_qualifying_lights_and_groups_with_both_modes(hass, z2m, caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER):
        await ensure_color_modes(hass, True)

    assert sent(z2m) == {
        ("device", IEEE): ON,
        ("device", OTHER): overrides(["xy", "hs"]),
        ("group", "1"): ON,
    }
    assert "color modes for lamp to xy, hs, color_temp, so Home Assistant shows its color" in caplog.text
    assert "for color pair to xy, hs, color_temp" in caplog.text
    assert not z2m.subscribers.get(DEVICES) and not z2m.subscribers.get(INFO)


async def test_a_users_own_value_is_left_alone(hass, z2m):
    z2m.retained[INFO]["config"]["devices"][IEEE] = overrides(["hs"])
    z2m.retained[INFO]["config"]["groups"]["1"] = ON

    await ensure_color_modes(hass, True)

    assert sent(z2m) == {("device", OTHER): overrides(["xy", "hs"])}


async def test_disabled_puts_back_z2m_defaults_only_where_device_side_set_them(hass, z2m, caplog):
    z2m.retained[INFO]["config"]["devices"][IEEE] = ON
    z2m.retained[INFO]["config"]["devices"][OTHER] = overrides(["hs"])
    z2m.retained[INFO]["config"]["groups"]["1"] = ON

    with caplog.at_level(logging.INFO, logger=LOGGER):
        await ensure_color_modes(hass, False)

    assert sent(z2m) == {("device", IEEE): OFF, ("group", "1"): OFF}
    assert "for lamp to xy, color_temp, as Zigbee2MQTT announces it" in caplog.text


async def test_no_z2m_does_nothing_quietly(hass, broker, caplog):
    await ensure_color_modes(hass, True)

    assert broker.published == []
    assert "WARNING" not in caplog.text


async def test_an_error_reply_warns_and_the_rest_still_go(hass, z2m, caplog):
    z2m.refused.add(IEEE)

    await ensure_color_modes(hass, True)

    assert set(sent(z2m)) == {("device", IEEE), ("device", OTHER), ("group", "1")}
    assert "Couldn't set Zigbee2MQTT's Home Assistant color modes for lamp: refused" in caplog.text


async def test_unexpected_bridge_devices_warns_and_does_nothing(hass, z2m, caplog):
    z2m.retained[DEVICES] = "not a list of devices"

    await ensure_color_modes(hass, True)

    assert z2m.requests() == []
    assert "Couldn't read Zigbee2MQTT's devices to check their color modes" in caplog.text


async def test_watch_runs_at_once_and_again_when_z2m_announces_a_device(hass, z2m):
    start = wall_clock_now()
    stop = await color_modes.async_watch(hass)
    await settle(hass)  # the retained messages, which start the first pass
    await advance(hass, start, 3)
    assert len(z2m.requests()) == 3

    newcomer = "0x00124b00cccccccc"
    z2m.retained[DEVICES].append(device(newcomer, FULL))
    z2m.deliver(DEVICES, json.dumps(z2m.retained[DEVICES]))
    await advance(hass, start, 6)

    assert sent(z2m)[("device", newcomer)] == ON
    stop()
    assert not z2m.subscribers.get(DEVICES) and not z2m.subscribers.get(GROUPS)


@pytest.fixture
def mqtt_ready(monkeypatch):
    ready = asyncio.Event()
    ready.set()

    async def wait_for_client(hass):
        await ready.wait()
        return True

    monkeypatch.setattr(color_modes.mqtt, "async_wait_for_mqtt_client", wait_for_client)
    return ready


async def setup_entry(hass, options: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, options=options or {})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    return entry


async def test_setup_watches_z2m_by_default(hass, z2m, mqtt_ready):
    start = wall_clock_now()
    entry = await setup_entry(hass)
    await settle(hass)
    await advance(hass, start, 3)

    assert len(z2m.requests()) == 3
    assert z2m.subscribers.get(DEVICES)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await settle(hass)
    assert not z2m.subscribers.get(DEVICES)
    assert len(z2m.requests()) == 3  # unloading, which HA's shutdown does too, puts nothing back


async def test_setup_isnt_held_back_while_mqtt_comes_up(hass, z2m, mqtt_ready):
    mqtt_ready.clear()

    entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert z2m.topics == []
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_setup_without_mqtt_does_nothing(hass, z2m, monkeypatch):
    async def no_client(hass):
        return False

    monkeypatch.setattr(color_modes.mqtt, "async_wait_for_mqtt_client", no_client)

    await setup_entry(hass)
    await settle(hass)

    assert z2m.topics == []


async def test_saving_the_option_off_puts_back_z2m_defaults(hass, z2m, mqtt_ready):
    entry = await setup_entry(hass)
    await settle(hass)
    z2m.retained[INFO]["config"]["devices"][IEEE] = ON

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["data_schema"]({})[CONF_Z2M_COLOR_MODES] is True
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**result["data_schema"]({}), CONF_Z2M_COLOR_MODES: False}
    )
    await settle(hass)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert sent(z2m) == {("device", IEEE): OFF}
    assert not z2m.subscribers.get(DEVICES)


async def test_deleting_device_side_puts_back_z2m_defaults(hass, z2m, mqtt_ready):
    entry = await setup_entry(hass, {CONF_Z2M_COLOR_MODES: False})
    await settle(hass)
    z2m.retained[INFO]["config"]["devices"][IEEE] = ON

    assert await hass.config_entries.async_remove(entry.entry_id)
    await settle(hass)

    assert sent(z2m) == {("device", IEEE): OFF}


async def test_deleting_device_side_without_mqtt_does_nothing(hass, z2m, monkeypatch):
    async def no_client(hass):
        return False

    monkeypatch.setattr(color_modes.mqtt, "async_wait_for_mqtt_client", no_client)
    entry = await setup_entry(hass)

    assert await hass.config_entries.async_remove(entry.entry_id)

    assert z2m.topics == []
