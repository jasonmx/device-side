"""The Hue report filter: the bridge's reports of our fades told from real changes, which forget the prediction."""

from types import SimpleNamespace

import pytest
from aiohue.v2.controllers.events import EventType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.device_side.core.runtime import get_runtime
from custom_components.device_side.integrations.hue.report_filter import Report, applies_later, classify
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


def moving_up(cache, clock) -> None:
    """light "one" moving 20 % to 80 % over 10 s, 5 s in."""
    cache.moving("one", BRIGHTNESS, 20.0, 80.0, 10.0)
    clock.now += 5.0


@pytest.mark.parametrize(
    ("event", "report"),
    [
        pytest.param(light_event("one", brightness=79.84), Report.OURS, id="end_value"),
        pytest.param(light_event("one", brightness=35.18), Report.OURS, id="stale_mid_ramp_report"),
        pytest.param(light_event("one", brightness=95.0), Report.OURS, id="past_the_target"),
        pytest.param(light_event("one", brightness=10.0), Report.OURS, id="below_the_start"),
        pytest.param(light_event("one", on=True), Report.OURS, id="on_while_lit"),
        pytest.param(light_event("one", on=False), Report.REAL, id="off_from_elsewhere"),
        pytest.param(light_event("one", brightness=35.0, on=False), Report.REAL, id="off_with_a_brightness"),
        pytest.param(light_event("one", color={"xy": {"x": 0.3, "y": 0.3}}), None, id="a_key_nothing_owns"),
        pytest.param(light_event("two", brightness=35.0), None, id="untracked_light"),
        pytest.param(light_event("one", dimming={"min_dim_level": 0.2}), None, id="dimming_without_brightness"),
    ],
)
async def test_classify_a_light_mid_move(hass, bridge, cache, clock, event, report):
    await setup_room(hass, bridge)
    moving_up(cache, clock)

    assert classify(cache, bridge.api, event) is report


async def test_the_move_is_recorded_before_its_write(hass, bridge, cache):
    # The bridge may report before the write returns.
    await setup_room(hass, bridge)
    request = bridge.api.request
    followed = []

    async def recording(*args, **kwargs):
        followed.append(cache.follows("one"))
        return await request(*args, **kwargs)

    bridge.api.request = recording
    await call(hass, "move", {"entity_id": "light.one", "brightness": "up"})

    assert followed == [True]


async def test_soft_off_reports_are_ours(hass, bridge, cache, clock):
    await setup_room(hass, bridge)
    cache.moving("one", BRIGHTNESS, 100.0, 0.0, 10.0)
    clock.now += 1.0

    assert classify(cache, bridge.api, light_event("one", on=False)) is Report.OURS
    clock.now += 7.0  # at 20 %, the bulb reports a second-old point lit
    assert classify(cache, bridge.api, light_event("one", on=True, brightness=21.0)) is Report.OURS


async def test_up_from_off_reports_are_ours(hass, bridge, cache, clock):
    await setup_room(hass, bridge)
    cache.moving("one", BRIGHTNESS, 0.0, 100.0, 10.0)

    assert classify(cache, bridge.api, light_event("one", on=True)) is Report.OURS
    assert classify(cache, bridge.api, light_event("one", brightness=100.0)) is Report.OURS


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
    assert classify(cache, bridge.api, room_event) is Report.OURS


async def test_a_real_change_from_the_bridge_forgets_the_light(hass, bridge, cache, clock):
    await setup_room(hass, bridge)
    await call(hass, "move", {"entity_id": "light.one", "brightness": "up", "sweep_time": 10})
    clock.now += 2.0
    api = bridge.api

    api.events.emit(EventType.RESOURCE_UPDATED, light_event("one", brightness=100.0))  # the bridge's end value
    api.events.emit(EventType.RESOURCE_UPDATED, light_event("one", brightness=25.0))  # the bulb, late
    await hass.async_block_till_done()
    assert cache.follows("one")

    api.events.emit(EventType.RESOURCE_UPDATED, light_event("one", on=False))  # the Hue app
    await hass.async_block_till_done()
    assert not cache.follows("one")
    assert not api.lights["one"].on.on  # aiohue applies every event: observe only


async def test_a_refused_move_records_nothing(hass, bridge, cache):
    await setup_room(hass, bridge)
    bridge.failing.add("one")

    with pytest.raises(HomeAssistantError):
        await call(hass, "move", {"entity_id": "light.one", "brightness": "up"})

    assert not cache.follows("one")


@pytest.mark.parametrize(("action", "data"), [("move", {"brightness": "up"}), ("stop", {})])
async def test_a_refused_write_puts_back_the_prediction_it_replaced(hass, bridge, cache, clock, action, data):
    await setup_room(hass, bridge)
    await call(hass, "move", {"entity_id": "light.one", "brightness": "down", "brightness_limit": 10})
    clock.now += 0.5
    before = cache.live("one", BRIGHTNESS)
    bridge.failing.add("one")

    with pytest.raises(HomeAssistantError):
        await call(hass, action, {"entity_id": "light.one", **data})

    assert cache.live("one", BRIGHTNESS) == before


async def test_a_refused_write_from_set_attributes_keeps_the_prediction(hass, bridge, cache, clock):
    await setup_room(hass, bridge)
    await call(hass, "move", {"entity_id": "light.one", "brightness": "up"})
    clock.now += 1.0
    bridge.failing.add("one")

    with pytest.raises(HomeAssistantError):
        await call(hass, "set_attributes", {"entity_id": "light.one", "brightness": 40})

    assert cache.running("one", BRIGHTNESS) is not None


def test_an_aiohue_without_the_private_handler_is_taken_to_apply_events_at_once():
    api = SimpleNamespace(lights=SimpleNamespace(), groups=SimpleNamespace(grouped_light=SimpleNamespace()))

    assert not applies_later(api)


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


@pytest.mark.parametrize("brightness", [41.3, 56.13])
async def test_any_brightness_after_a_stop_is_ours_until_its_window_ends(hass, bridge, cache, clock, brightness):
    # The rig saw a halt reported 0.9 from the prediction, and a stale report from before the move 16 above it.
    await setup_room(hass, bridge)
    cache.stopped("one", BRIGHTNESS, 40.4)
    clock.now += 5.0

    assert classify(cache, bridge.api, light_event("one", brightness=brightness)) is Report.OURS
    clock.now += API_SETTLE_SECONDS
    assert classify(cache, bridge.api, light_event("one", brightness=brightness)) is None


async def test_off_after_a_lit_halt_is_real(hass, bridge, cache, clock):
    await setup_room(hass, bridge)
    cache.stopped("one", BRIGHTNESS, 40.4)
    clock.now += 5.0

    assert classify(cache, bridge.api, light_event("one", on=False)) is Report.REAL
