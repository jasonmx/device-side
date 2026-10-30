"""Zigbee2MQTT raise and lower share their fade: color_hs, addressing, predictions and the end read-backs."""

import pytest

from .conftest import GET, SENT, SET, commands, group, light, unchanged
from ...conftest import advance, call, refusal, wall_clock_now
from ...fixtures.z2m import add_z2m_group, z2m_entry

pytestmark = pytest.mark.usefixtures("setup_production", "clock")

COLOR_ACTIONS = ["raise_saturation", "lower_saturation", "raise_hue", "lower_hue"]


@pytest.mark.parametrize("action", COLOR_ACTIONS)
async def test_color_is_dropped_without_color_hs(hass, broker, action):
    entity_id = light(hass, broker, color_hs=False)

    response = await call(hass, action, {"entity_id": entity_id})

    assert response == {entity_id: unchanged("fields_dropped")}
    assert commands(broker) == []


async def test_brightness_moves_without_color_hs(hass, broker):
    entity_id = light(hass, broker, color_hs=False)

    response = await call(hass, "raise_brightness", {"entity_id": entity_id})

    assert response == {entity_id: SENT}
    assert commands(broker) == [(SET, {"state": "ON", "brightness": 254, "transition": 2.0})]


async def test_a_group_with_a_member_without_color_hs_drops_hue(hass, broker):
    # Z2M gives a group only the features every member shares.
    room = group(hass, broker, one={}, two={"color_hs": False})

    response = await call(hass, "raise_hue", {"entity_id": room})

    assert response == {room: unchanged("fields_dropped")}
    assert commands(broker) == []


@pytest.mark.parametrize("action", ["raise_brightness", "lower_brightness", *COLOR_ACTIONS, "stop"])
async def test_a_group_on_another_base_topic_is_refused(hass, broker, action):
    entry = z2m_entry(hass)
    add_z2m_group(hass, entry, "light.room", group_id=7, base_topic="z2m", state="on")

    assert await refusal(hass, action, {"entity_id": "light.room"}) == "not_addressable"


async def test_a_move_after_a_stop_starts_where_it_halted(hass, broker, clock):
    entity_id = light(hass, broker)
    await call(hass, "raise_brightness", {"entity_id": entity_id})
    hass.states.async_set(entity_id, "on", {"brightness": 255, "hs_color": (200.0, 60.0)})  # Z2M's end value
    clock.now += 1  # halfway from 60 % to 100 %

    await call(hass, "stop", {"entity_id": entity_id})
    await call(hass, "lower_brightness", {"entity_id": entity_id})

    assert commands(broker)[-1] == (SET, {"state": "OFF", "transition": 4.0})


async def test_a_saturation_move_starts_from_its_prediction(hass, broker, clock):
    entity_id = light(hass, broker)
    await call(hass, "raise_saturation", {"entity_id": entity_id})
    clock.now += 1  # halfway from 60 % to 100 %

    await call(hass, "lower_saturation", {"entity_id": entity_id})

    assert commands(broker)[-1] == (SET, {"color": {"hue": 200.0, "saturation": 0.0}, "transition": 4.0})


async def test_an_empty_group_is_skipped(hass, broker):
    room = group(hass, broker, one={}, two={})
    light(hass, broker)
    hass.states.async_set("light.one", "unavailable")
    hass.states.async_set("light.two", "unavailable")

    response = await call(hass, "raise_brightness", {"entity_id": [room, "light.lamp"]})

    assert response == {"light.lamp": SENT}
    assert [topic for topic, _ in commands(broker)] == [SET]


async def test_a_failed_read_back_is_logged(hass, broker, caplog):
    entity_id = light(hass, broker)
    start = wall_clock_now()
    await call(hass, "raise_brightness", {"entity_id": entity_id})

    def refuse(service):
        raise RuntimeError("broker gone")

    hass.services.async_register("mqtt", "publish", refuse)
    with caplog.at_level("DEBUG"):
        await advance(hass, start, 3.5)

    assert "End read-back for light.lamp failed: broker gone" in caplog.text


async def test_a_new_move_replaces_the_pending_read_back(hass, broker):
    entity_id = light(hass, broker)
    start = wall_clock_now()
    await call(hass, "raise_brightness", {"entity_id": entity_id})

    await call(hass, "lower_brightness", {"entity_id": entity_id, "limit": 40})

    # The second fade, from the first's start at the same instant, runs 1 s.
    await advance(hass, start, 2.5)
    assert commands(broker)[2:] == [(GET, {"state": "", "brightness": ""})]
    await advance(hass, start, 3.5)
    assert commands(broker)[2:] == [(GET, {"state": "", "brightness": ""})]


async def test_a_move_of_another_attribute_keeps_the_pending_read_back(hass, broker):
    # Brightness and saturation fades run side by side: each is read back at its own end.
    entity_id = light(hass, broker, color={"colorMode": 1})
    start = wall_clock_now()
    await call(hass, "raise_brightness", {"entity_id": entity_id})  # 2 s
    await call(hass, "lower_saturation", {"entity_id": entity_id, "limit": 20})  # 2 s

    await advance(hass, start, 3.5)

    assert sorted(commands(broker)[2:], key=str) == [
        (GET, {"color": ""}),
        (GET, {"state": "", "brightness": ""}),
    ]
