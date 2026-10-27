"""The Hue report filter: the bridge's reports of our fades told from real changes, which forget the prediction."""

import pytest
from aiohue.v2.controllers.events import EventType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.device_side.core.runtime import get_runtime
from custom_components.device_side.integrations.hue.report_filter import Report, classify
from custom_components.device_side.integrations.hue.transition_cache import (
    API_SETTLE_SECONDS,
    BRIGHTNESS,
    transition_cache,
)

from .conftest import light_event, setup_room
from ...conftest import call

pytestmark = pytest.mark.usefixtures("setup_production")


@pytest.fixture
def cache(hass, clock):
    return transition_cache(hass)


def moving_up(cache, clock, *, armed: dict | None = None) -> None:
    """light "one" moving 20 % to 80 % over 10 s, 5 s in: the bulb may report anything from 20 to 80 %."""
    cache.arm("one", armed if armed is not None else {BRIGHTNESS: 80.0}, 10.0)
    cache.moving("one", BRIGHTNESS, 20.0, 80.0, 10.0)
    clock.now += 5.0


@pytest.mark.parametrize(
    ("event", "report"),
    [
        pytest.param(light_event("one", brightness=79.84), Report.ECHO, id="armed_end_value"),
        pytest.param(light_event("one", brightness=35.18), Report.PATH, id="stale_mid_ramp_report"),
        pytest.param(light_event("one", brightness=70.0), Report.PATH, id="ahead_of_the_prediction"),
        pytest.param(light_event("one", brightness=19.5), Report.PATH, id="path_lower_edge"),
        pytest.param(light_event("one", brightness=80.6), Report.REAL, id="past_the_target"),
        pytest.param(light_event("one", brightness=19.4), Report.REAL, id="below_the_start"),
        pytest.param(light_event("one", on=True), Report.PATH, id="on_while_lit"),
        pytest.param(light_event("one", on=False), Report.REAL, id="off_from_elsewhere"),
        pytest.param(light_event("one", brightness=35.0, on=False), Report.REAL, id="any_real_value_makes_it_real"),
        pytest.param(light_event("one", color={"xy": {"x": 0.3, "y": 0.3}}), None, id="no_brightness_or_on"),
        pytest.param(light_event("two", brightness=35.0), None, id="untracked_light"),
        pytest.param(light_event("one", dimming={"min_dim_level": 0.2}), None, id="dimming_without_brightness"),
    ],
)
async def test_classify_a_light_mid_move(hass, bridge, cache, clock, event, report):
    await setup_room(hass, bridge)
    moving_up(cache, clock)

    assert classify(cache, bridge.api, event) is report


async def test_an_end_value_is_echoed_once(hass, bridge, cache, clock):
    await setup_room(hass, bridge)
    moving_up(cache, clock)

    assert classify(cache, bridge.api, light_event("one", brightness=80.0)) is Report.ECHO
    assert not cache.echoed("one", BRIGHTNESS, 80.0)


async def test_the_echo_counts_before_the_move_is_recorded(hass, bridge, cache):
    # Armed before the write; the bridge may report before the write returns and the move is recorded.
    await setup_room(hass, bridge)
    cache.arm("two", {BRIGHTNESS: 80.0}, 10.0)

    assert classify(cache, bridge.api, light_event("two", brightness=79.84)) is Report.ECHO


async def test_soft_off_echo_and_the_lit_report_during_it(hass, bridge, cache, clock):
    await setup_room(hass, bridge)
    cache.arm("one", {"on": False}, 10.0)
    cache.moving("one", BRIGHTNESS, 100.0, 0.0, 10.0)
    clock.now += 1.0

    assert classify(cache, bridge.api, light_event("one", on=False)) is Report.ECHO
    clock.now += 7.0  # at 20 %, the bulb reports a second-old point lit
    assert classify(cache, bridge.api, light_event("one", on=True, brightness=21.0)) is Report.PATH
    clock.now += 2.0  # at 0 %: off is on the path
    assert classify(cache, bridge.api, light_event("one", on=False)) is Report.PATH


async def test_up_from_off_echoes_on_and_the_end_value(hass, bridge, cache, clock):
    await setup_room(hass, bridge)
    cache.arm("one", {BRIGHTNESS: 100.0, "on": True}, 10.0)
    cache.moving("one", BRIGHTNESS, 0.0, 100.0, 10.0)

    assert classify(cache, bridge.api, light_event("one", on=True)) is Report.ECHO
    assert classify(cache, bridge.api, light_event("one", brightness=100.0)) is Report.ECHO


async def test_after_the_window_every_event_is_untracked(hass, bridge, cache, clock):
    await setup_room(hass, bridge)
    moving_up(cache, clock)
    clock.now += 5.0 + API_SETTLE_SECONDS + 0.1

    assert classify(cache, bridge.api, light_event("one", brightness=79.84)) is None


async def test_a_grouped_light_is_decided_by_its_lights(hass, bridge, cache, clock):
    await setup_room(hass, bridge)
    room_event = {"id": "1", "type": "grouped_light", "dimming": {"brightness": 99.0}}

    assert classify(cache, bridge.api, room_event) is None
    moving_up(cache, clock)
    assert classify(cache, bridge.api, room_event) is Report.PATH


async def test_a_real_change_from_the_bridge_forgets_the_light(hass, bridge, cache, clock):
    await setup_room(hass, bridge)
    await call(hass, "move", {"entity_id": "light.one", "brightness": "up", "sweep_time": 10})
    clock.now += 2.0
    api = bridge.api

    api.events.emit(EventType.RESOURCE_UPDATED, light_event("one", brightness=100.0))  # our echo
    api.events.emit(EventType.RESOURCE_UPDATED, light_event("one", brightness=25.0))  # the bulb, late
    await hass.async_block_till_done()
    assert cache.follows("one")

    api.events.emit(EventType.RESOURCE_UPDATED, light_event("one", brightness=10.0))  # the Hue app
    await hass.async_block_till_done()
    assert not cache.follows("one")
    assert api.lights["one"].dimming.brightness == 10.0  # aiohue applies every event: observe only


async def test_a_refused_move_disarms_its_echo(hass, bridge, cache):
    await setup_room(hass, bridge)
    bridge.failing.add("one")

    with pytest.raises(HomeAssistantError):
        await call(hass, "move", {"entity_id": "light.one", "brightness": "up"})

    assert not cache.follows("one")


@pytest.mark.parametrize(
    ("service_data", "forgotten"),
    [
        pytest.param({"entity_id": "light.one"}, {"one"}, id="light"),
        pytest.param({"entity_id": "light.room"}, {"one", "two"}, id="room"),
        pytest.param({"area_id": "office"}, {"two"}, id="area"),
        pytest.param({"device_id": "DEVICE"}, {"one"}, id="device"),
        pytest.param({"entity_id": "all"}, {"one", "two"}, id="all"),
        pytest.param({"entity_id": "light.other"}, set(), id="not_hue"),
        pytest.param(None, set(), id="no_target"),
    ],
)
async def test_a_light_call_from_ha_forgets_its_hue_lights(hass, bridge, cache, service_data, forgotten):
    entry = await setup_room(hass, bridge)
    entities = er.async_get(hass)
    area = ar.async_get(hass).async_create("office")
    entities.async_update_entity("light.two", area_id=area.id)
    device = dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, identifiers={("hue", "one")})
    entities.async_update_entity("light.one", device_id=device.id)
    entities.async_get_or_create("light", "demo", "other", suggested_object_id="other")
    async_mock_service(hass, "light", "turn_on")
    for light_id in ("one", "two"):
        cache.stopped(light_id, BRIGHTNESS, 42.0)
    await call(hass, "stop", {"entity_id": "light.one"})  # attaches the filter
    if service_data is not None:
        service_data = {
            key: area.id if value == "office" else device.id if value == "DEVICE" else value
            for key, value in service_data.items()
        }

    await hass.services.async_call("light", "turn_on", service_data, blocking=True)

    assert {light_id for light_id in ("one", "two") if not cache.follows(light_id)} == forgotten


async def test_a_scene_from_ha_forgets_its_rooms_lights(hass, bridge, cache):
    await setup_room(hass, bridge)
    async_mock_service(hass, "scene", "turn_on")
    async_mock_service(hass, "switch", "turn_on")
    for light_id in ("one", "two"):
        cache.stopped(light_id, BRIGHTNESS, 42.0)
    await call(hass, "stop", {"entity_id": "light.room"})

    await hass.services.async_call("switch", "turn_on", {"entity_id": "light.one"}, blocking=True)
    assert cache.follows("one")
    await hass.services.async_call("scene", "turn_on", {"entity_id": "scene.relax"}, blocking=True)

    assert not cache.follows("one")
    assert not cache.follows("two")


async def test_the_filter_attaches_once_per_bridge_and_detaches_on_unload(hass, bridge, setup_production):
    entry = await setup_room(hass, bridge)
    api = bridge.api
    before = len(api.events._subscribers)

    await call(hass, "move", {"entity_id": "light.one", "brightness": "up"})
    await call(hass, "move", {"entity_id": "light.two", "brightness": "up"})
    assert len(api.events._subscribers) == before + 1

    # A reloaded hue entry is a new aiohue bridge: the old one's filter is detached and a new one attached.
    entry.runtime_data.api = await bridge.load()
    await call(hass, "stop", {"entity_id": "light.one"})
    assert len(api.events._subscribers) == before
    assert len(bridge.api.events._subscribers) == before + 1

    assert await hass.config_entries.async_unload(setup_production.entry_id)
    assert len(bridge.api.events._subscribers) == before
    assert get_runtime(hass).listeners == {}


async def test_a_failing_filter_never_stops_aiohue_applying_the_event(hass, bridge, cache, monkeypatch, caplog):
    await setup_room(hass, bridge)
    await call(hass, "stop", {"entity_id": "light.one"})  # attaches the filter

    def broken(*_args):
        raise RuntimeError("boom")

    monkeypatch.setattr("custom_components.device_side.integrations.hue.report_filter.classify", broken)
    bridge.api.events.emit(EventType.RESOURCE_UPDATED, light_event("one", brightness=90.0))
    await hass.async_block_till_done()

    assert bridge.api.lights["one"].dimming.brightness == 90.0
    assert "Hue report filter failed" in caplog.text


@pytest.mark.parametrize(("brightness", "report"), [(39.5, Report.PATH), (41.9, Report.PATH), (38.8, Report.REAL)])
async def test_a_late_halt_report_is_ours_within_the_halt_tolerance(hass, bridge, cache, clock, brightness, report):
    # The rig saw a halt reported 0.9 from the prediction.
    await setup_room(hass, bridge)
    cache.stopped("one", BRIGHTNESS, 40.4)
    clock.now += 5.0

    assert classify(cache, bridge.api, light_event("one", brightness=brightness)) is report
