"""Zigbee2MQTT move: an end point with a transition per attribute, hue as a rate move, and the end read-backs."""

import pytest

from custom_components.device_side.core.transition import BRIGHTNESS, SATURATION
from custom_components.device_side.integrations.zigbee2mqtt.move import transition_cache

from .conftest import commands, group, light
from ...conftest import advance, call, refusal, wall_clock_now
from ...fixtures.z2m import IEEE, add_z2m_group, z2m_entry

pytestmark = pytest.mark.usefixtures("setup_production", "clock")

SENT = {"status": "sent", "integration": "zigbee2mqtt"}
SET = f"zigbee2mqtt/{IEEE}/set"
GET = f"zigbee2mqtt/{IEEE}/get"
BOTTOM = {"state": "ON", "brightness": 1, "transition": 0}


@pytest.mark.parametrize(
    ("data", "payload"),
    [
        # From 60 %, the top of a 5 s sweep is 2 s away: the speed is the same wherever the move starts.
        pytest.param({"brightness": "up"}, {"state": "ON", "brightness": 254, "transition": 2.0}, id="up_turns_on"),
        pytest.param({"brightness": "down"}, {"state": "OFF", "transition": 3.0}, id="down_to_zero_is_a_soft_off"),
        pytest.param(
            {"brightness": "down", "brightness_limit": 20}, {"brightness": 51, "transition": 2.0}, id="down_to_a_limit"
        ),
        pytest.param(
            {"saturation": "up"},
            {"color": {"hue": 200.0, "saturation": 100.0}, "transition": 2.0},
            id="saturation_at_the_current_hue",
        ),
        pytest.param(
            {"saturation": "down", "saturation_limit": 20, "sweep_time": 10},
            {"color": {"hue": 200.0, "saturation": 20.0}, "transition": 4.0},
            id="saturation_to_a_limit",
        ),
        pytest.param({"hue": "up"}, {"hue_move": 51}, id="hue_up_a_cycle_in_5_s"),
        pytest.param({"hue": "down", "sweep_time": 10}, {"hue_move": -25}, id="hue_down"),
    ],
)
async def test_move_publishes_the_end_point_with_the_time_left(hass, broker, data, payload):
    entity_id = light(hass, broker)

    response = await call(hass, "move", {"entity_id": entity_id, **data})

    assert response == {entity_id: SENT}
    assert commands(broker) == [(SET, payload)]


@pytest.mark.parametrize(
    ("sweep_time", "rate", "clamped_to"),
    [(0.5, 254, 1.0), (1, 254, None), (254, 1, None), (300, 1, 254.0)],
)
async def test_hue_sweep_time_outside_1_to_254_s_is_clamped_and_reported(hass, broker, sweep_time, rate, clamped_to):
    entity_id = light(hass, broker)

    response = await call(hass, "move", {"entity_id": entity_id, "hue": "up", "sweep_time": sweep_time})

    assert response == {entity_id: SENT | ({"clamped_to": clamped_to} if clamped_to else {})}
    assert commands(broker) == [(SET, {"hue_move": rate})]


async def test_up_from_off_starts_at_the_bottom(hass, broker):
    # An off light keeps its level, which a fade from off would start at: it is turned on at the bottom first.
    entity_id = light(hass, broker, state="off")

    await call(hass, "move", {"entity_id": entity_id, "brightness": "up"})

    assert commands(broker) == [(SET, BOTTOM), (SET, {"state": "ON", "brightness": 254, "transition": 5.0})]


@pytest.mark.parametrize(
    ("options", "data", "detail"),
    [
        pytest.param({"brightness": 255}, {"brightness": "up"}, "at_limit", id="brightness_at_the_top"),
        pytest.param(
            {"hs": (200.0, 20.0)}, {"saturation": "down", "saturation_limit": 20}, "at_limit", id="saturation"
        ),
        pytest.param({"state": "off"}, {"brightness": "down"}, "off", id="down_on_an_off_light"),
        pytest.param({"state": "off"}, {"saturation": "up"}, "off", id="saturation_on_an_off_light"),
        pytest.param({"state": "off"}, {"hue": "up"}, "off", id="hue_on_an_off_light"),
        pytest.param({"brightness": 255}, {"brightness": "up", "hue": "down"}, None, id="hue_still_moves"),
    ],
)
async def test_nothing_left_to_move_is_unchanged(hass, broker, options, data, detail):
    entity_id = light(hass, broker, **options)

    response = await call(hass, "move", {"entity_id": entity_id, **data})

    if detail is None:
        assert response == {entity_id: SENT}
        assert commands(broker) == [(SET, {"hue_move": -51})]
    else:
        assert response == {entity_id: {"status": "unchanged", "integration": "zigbee2mqtt", "detail": detail}}
        assert commands(broker) == []


async def test_hue_from_off_moves_with_brightness_up(hass, broker):
    entity_id = light(hass, broker, state="off")

    await call(hass, "move", {"entity_id": entity_id, "brightness": "up", "hue": "up"})

    assert commands(broker) == [
        (SET, BOTTOM),
        (SET, {"state": "ON", "brightness": 254, "transition": 5.0}),
        (SET, {"hue_move": 51}),
    ]


async def test_hue_and_saturation_are_dropped_without_color_hs(hass, broker):
    entity_id = light(hass, broker, color_hs=False)

    moved = await call(hass, "move", {"entity_id": entity_id, "brightness": "up", "hue": "up"})
    dropped = await call(hass, "move", {"entity_id": entity_id, "saturation": "up", "saturation_limit": 80})

    assert moved == {entity_id: SENT | {"detail": "fields_dropped"}}
    assert dropped == {entity_id: {"status": "unchanged", "integration": "zigbee2mqtt", "detail": "fields_dropped"}}
    assert commands(broker) == [(SET, {"state": "ON", "brightness": 254, "transition": 2.0})]


async def test_a_group_with_a_member_without_color_hs_drops_hue(hass, broker):
    # Z2M gives a group only the features every member shares.
    room = group(hass, broker, one={}, two={"color_hs": False})

    response = await call(hass, "move", {"entity_id": room, "hue": "up"})

    assert response == {room: {"status": "unchanged", "integration": "zigbee2mqtt", "detail": "fields_dropped"}}
    assert commands(broker) == []


async def test_color_temperature_is_refused(hass, broker):
    entity_id = light(hass, broker)

    assert await refusal(hass, "move", {"entity_id": entity_id, "color_temp": "warmer"}) == "fields_not_tested"


@pytest.mark.parametrize("action", [{"service": "move", "brightness": "up"}, {"service": "stop"}])
async def test_a_group_on_another_base_topic_is_refused(hass, broker, action):
    entry = z2m_entry(hass)
    add_z2m_group(hass, entry, "light.room", group_id=7, base_topic="z2m", state="on")
    service, data = action["service"], {k: v for k, v in action.items() if k != "service"}

    assert await refusal(hass, service, {"entity_id": "light.room", **data}) == "not_addressable"


async def test_a_move_after_a_stop_starts_where_it_halted(hass, broker, clock):
    entity_id = light(hass, broker)
    await call(hass, "move", {"entity_id": entity_id, "brightness": "up"})
    hass.states.async_set(entity_id, "on", {"brightness": 255, "hs_color": (200.0, 60.0)})  # Z2M's end value
    clock.now += 1  # halfway from 60 % to 100 %

    await call(hass, "stop", {"entity_id": entity_id})
    await call(hass, "move", {"entity_id": entity_id, "brightness": "down"})

    assert commands(broker)[-1] == (SET, {"state": "OFF", "transition": 4.0})


async def test_a_saturation_move_starts_from_its_prediction(hass, broker, clock):
    entity_id = light(hass, broker)
    await call(hass, "move", {"entity_id": entity_id, "saturation": "up"})
    clock.now += 1  # halfway from 60 % to 100 %

    await call(hass, "move", {"entity_id": entity_id, "saturation": "down"})

    assert commands(broker)[-1] == (SET, {"color": {"hue": 200.0, "saturation": 0.0}, "transition": 4.0})


async def test_a_group_gets_one_publish_and_a_prediction_per_member(hass, broker, clock):
    room = group(hass, broker, one={"brightness": 255}, two={"brightness": 51})

    response = await call(hass, "move", {"entity_id": room, "brightness": "down"})

    assert response == {room: SENT}
    # From the members' mean, 60 %, to off over a 5 s sweep.
    assert commands(broker) == [("zigbee2mqtt/7/set", {"state": "OFF", "transition": 3.0})]
    cache = transition_cache(hass)
    clock.now += 1.5
    assert cache.value("light.one", BRIGHTNESS, 0) == pytest.approx(50.0)
    assert cache.value("light.two", BRIGHTNESS, 0) == pytest.approx(10.0)


async def test_a_group_with_an_off_member_moves_it_up_from_the_bottom(hass, broker, clock):
    room = group(hass, broker, one={"brightness": 204}, two={"state": "off"})

    await call(hass, "move", {"entity_id": room, "brightness": "up"})

    # From the lit member's 80 %: 1 s. Only the off member is put at the bottom first.
    assert commands(broker) == [
        ("zigbee2mqtt/0x02/set", BOTTOM),
        ("zigbee2mqtt/7/set", {"state": "ON", "brightness": 254, "transition": 1.0}),
    ]
    cache = transition_cache(hass)
    clock.now += 0.5
    assert cache.value("light.two", BRIGHTNESS, -1) == pytest.approx(50.0)


async def test_a_group_all_off_is_put_at_the_bottom_with_one_publish(hass, broker):
    room = group(hass, broker, one={"state": "off"}, two={"state": "off"})

    await call(hass, "move", {"entity_id": room, "brightness": "up"})

    assert commands(broker) == [
        ("zigbee2mqtt/7/set", BOTTOM),
        ("zigbee2mqtt/7/set", {"state": "ON", "brightness": 254, "transition": 5.0}),
    ]


async def test_a_group_saturation_move_records_each_lit_member(hass, broker, clock):
    room = group(hass, broker, one={"hs": (200.0, 40.0)}, two={"hs": (200.0, 80.0)})

    await call(hass, "move", {"entity_id": room, "saturation": "up"})

    payload = {"color": {"hue": 200.0, "saturation": 100.0}, "transition": 2.0}
    assert commands(broker) == [("zigbee2mqtt/7/set", payload)]
    cache = transition_cache(hass)
    assert cache.value("light.one", SATURATION, 0) == 40.0
    assert cache.value("light.two", SATURATION, 0) == 80.0


async def test_an_empty_group_is_skipped(hass, broker):
    room = group(hass, broker, one={}, two={})
    light(hass, broker)
    hass.states.async_set("light.one", "unavailable")
    hass.states.async_set("light.two", "unavailable")

    response = await call(hass, "move", {"entity_id": [room, "light.lamp"], "brightness": "up"})

    assert response == {"light.lamp": SENT}
    assert [topic for topic, _ in commands(broker)] == [SET]


async def test_brightness_is_read_back_once_the_fade_has_run(hass, broker):
    entity_id = light(hass, broker)
    start = wall_clock_now()

    await call(hass, "move", {"entity_id": entity_id, "brightness": "up"})

    await advance(hass, start, 2.5)
    assert commands(broker)[1:] == []
    await advance(hass, start, 3.5)
    assert commands(broker)[1:] == [(GET, {"state": "", "brightness": ""})]


async def test_a_group_is_read_back_member_by_member(hass, broker):
    room = group(hass, broker, one={}, two={})
    start = wall_clock_now()

    await call(hass, "move", {"entity_id": room, "brightness": "up"})

    await advance(hass, start, 3.5)
    assert commands(broker)[1:] == [
        ("zigbee2mqtt/0x01/get", {"state": "", "brightness": ""}),
        ("zigbee2mqtt/0x02/get", {"state": "", "brightness": ""}),
    ]


async def test_a_failed_read_back_is_logged(hass, broker, caplog, monkeypatch):
    entity_id = light(hass, broker)
    start = wall_clock_now()
    await call(hass, "move", {"entity_id": entity_id, "brightness": "up"})

    def refuse(service):
        raise RuntimeError("broker gone")

    hass.services.async_register("mqtt", "publish", refuse)
    with caplog.at_level("DEBUG"):
        await advance(hass, start, 3.5)

    assert "End read-back for light.lamp failed: broker gone" in caplog.text


async def test_a_saturation_move_brings_the_color_in_line_at_its_end(hass, broker):
    entity_id = light(hass, broker, color={"colorMode": 1})
    start = wall_clock_now()

    await call(hass, "move", {"entity_id": entity_id, "saturation": "up"})

    await advance(hass, start, 3.5)
    assert commands(broker)[1:] == [(GET, {"color": ""})]


async def test_a_new_move_replaces_the_pending_read_back(hass, broker):
    entity_id = light(hass, broker)
    start = wall_clock_now()
    await call(hass, "move", {"entity_id": entity_id, "brightness": "up"})

    await call(hass, "move", {"entity_id": entity_id, "brightness": "down", "brightness_limit": 40})

    # The second fade, from the first's start at the same instant, runs 1 s.
    await advance(hass, start, 2.5)
    assert commands(broker)[2:] == [(GET, {"state": "", "brightness": ""})]
    await advance(hass, start, 3.5)
    assert commands(broker)[2:] == [(GET, {"state": "", "brightness": ""})]
