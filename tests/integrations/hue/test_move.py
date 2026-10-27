"""Hue move and stop for brightness: one PUT per light or room, ported from hue_dimmer's test_core and
test_transition_errors."""

import pytest
from aiohue.v2.controllers.events import EventType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.device_side.integrations.hue.transition_cache import transition_cache

from .conftest import Clock
from ...conftest import call
from ...fixtures.hue import add_hue_entity, add_hue_group, hue_entry

pytestmark = pytest.mark.usefixtures("setup_production")

SENT = {"status": "sent", "integration": "hue"}


@pytest.fixture
def clock(hass) -> Clock:
    clock = Clock()
    transition_cache(hass).clock = clock
    return clock


def percent(value: float) -> int:
    """HA's 0-255 brightness for a Hue percent; multiples of 20 % convert exactly both ways."""
    return round(value * 255 / 100)


async def lamp(hass, bridge, *, state: str = "on", brightness_pct: float | None = 60.0, **light) -> str:
    bridge.light("light-1", on=state == "on", **light)
    entry = await hue_entry(hass, bridge)
    attributes = {"brightness": percent(brightness_pct)} if state == "on" and brightness_pct is not None else {}
    return add_hue_entity(hass, entry, "light.lamp", "light-1", state=state, attributes=attributes)


async def room(hass, bridge, *, state: str = "on", brightness_pct: float = 60.0) -> str:
    on = state == "on"
    bridge.light("one", on=on, brightness=brightness_pct)
    bridge.light("two", on=on, brightness=brightness_pct)
    bridge.room("grouped-1", ["one", "two"], brightness=brightness_pct)
    entry = await hue_entry(hass, bridge)
    members = [add_hue_entity(hass, entry, f"light.{light_id}", light_id, state=state) for light_id in ("one", "two")]
    add_hue_group(hass, entry, "light.room", "grouped-1", members)
    attributes = {"is_hue_group": True, "entity_id": members} | ({"brightness": percent(brightness_pct)} if on else {})
    hass.states.async_set("light.room", state, attributes)
    return "light.room"


def move_put(brightness: float, duration_ms: int, on: bool | None = None) -> dict:
    put: dict = {"dimming": {"brightness": brightness}, "dynamics": {"duration": duration_ms}}
    return put | ({"on": {"on": on}} if on is not None else {})


# No brightness: the bridge keeps the stored one, so the next plain turn_on comes back at it rather than the minimum.
SOFT_OFF_3S = {"on": {"on": False}, "dynamics": {"duration": 3000}}
STOP = {"dimming_delta": {"action": "stop"}}


@pytest.mark.parametrize(
    ("data", "put"),
    [
        pytest.param({"brightness": "up"}, move_put(100.0, 2000, on=True), id="up_to_the_top_turns_on"),
        pytest.param({"brightness": "down"}, SOFT_OFF_3S, id="down_to_zero_is_a_plain_soft_off"),
        pytest.param({"brightness": "down", "brightness_limit": 20}, move_put(20.0, 2000), id="down_to_a_limit"),
        pytest.param({"brightness": "up", "sweep_time": 10}, move_put(100.0, 4000, on=True), id="sweep_time"),
        pytest.param({"brightness": "up", "sweep_time": 0.1}, move_put(100.0, 40, on=True), id="shortest_sweep"),
    ],
)
async def test_move_writes_the_end_point_with_the_time_left(hass, bridge, data, put):
    # 60 % to the top of a 5 s sweep is 2 s: the speed is the same wherever the move starts.
    entity_id = await lamp(hass, bridge)

    response = await call(hass, "move", {"entity_id": entity_id, **data})

    assert response == {entity_id: SENT}
    assert bridge.puts == [("light/light-1", put)]


async def test_up_from_off_starts_at_the_bottom(hass, bridge):
    # HA shows no brightness for a light that is off, so the move takes the whole sweep from 0 %.
    entity_id = await lamp(hass, bridge, state="off")

    await call(hass, "move", {"entity_id": entity_id, "brightness": "up"})

    assert bridge.puts == [("light/light-1", move_put(100.0, 5000, on=True))]


@pytest.mark.parametrize(
    ("brightness_pct", "data"),
    [
        pytest.param(99.9, {"brightness": "up"}, id="at_the_top"),
        pytest.param(20.0, {"brightness": "down", "brightness_limit": 30}, id="already_past_the_limit"),
    ],
)
async def test_at_the_limit_nothing_is_sent(hass, bridge, brightness_pct, data):
    entity_id = await lamp(hass, bridge, brightness_pct=brightness_pct)

    response = await call(hass, "move", {"entity_id": entity_id, **data})

    assert response == {entity_id: {"status": "unchanged", "integration": "hue", "detail": "at_limit"}}
    assert bridge.puts == []


async def test_down_from_off_is_at_the_limit(hass, bridge):
    entity_id = await lamp(hass, bridge, state="off")

    response = await call(hass, "move", {"entity_id": entity_id, "brightness": "down"})

    assert response[entity_id]["detail"] == "at_limit"


async def test_room_moves_with_one_grouped_light_write(hass, bridge):
    entity_id = await room(hass, bridge)

    response = await call(hass, "move", {"entity_id": entity_id, "brightness": "up"})

    assert response == {entity_id: SENT}
    assert bridge.puts == [("grouped_light/grouped-1", move_put(100.0, 2000, on=True))]


@pytest.mark.parametrize(("target", "path"), [("light", "light/light-1"), ("room", "grouped_light/grouped-1")])
async def test_move_after_a_stop_continues_from_where_it_halted(hass, bridge, clock, target, path):
    # The bridge reports the end value at once; the next move must start from the predicted one.
    entity_id = await (lamp if target == "light" else room)(hass, bridge, brightness_pct=20.0)
    await call(hass, "move", {"entity_id": entity_id, "brightness": "up", "sweep_time": 10})
    hass.states.async_set(entity_id, "on", {**hass.states.get(entity_id).attributes, "brightness": 255})
    clock.now += 3

    await call(hass, "stop", {"entity_id": entity_id})
    clock.now += 5
    await call(hass, "move", {"entity_id": entity_id, "brightness": "up", "sweep_time": 10})

    assert bridge.puts[1] == (path, {"dimming_delta": {"action": "stop"}})
    assert bridge.puts[2] == (path, move_put(100.0, 5000, on=True))  # from 50 %


async def test_a_refused_move_is_rejected_and_not_cached(hass, bridge, clock):
    entity_id = await lamp(hass, bridge, brightness_pct=20.0)
    bridge.failing.add("light-1")

    with pytest.raises(HomeAssistantError):
        await call(hass, "move", {"entity_id": entity_id, "brightness": "up"})
    bridge.failing.clear()
    clock.now += 1
    await call(hass, "move", {"entity_id": entity_id, "brightness": "up"})

    # Started from HA's 20 %, not from a phantom move's prediction.
    assert bridge.puts[-1] == ("light/light-1", move_put(100.0, 4000, on=True))


async def test_light_without_dimming_is_unsupported(hass, bridge):
    entity_id = await lamp(hass, bridge, brightness=None, mirek=None)

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "move", {"entity_id": entity_id, "brightness": "up"})

    assert raised.value.translation_placeholders["summary"] == "light.lamp: fields_not_supported"


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        pytest.param({"color_temp": "warmer"}, "fields_not_tested", id="color_temp_not_yet"),
        pytest.param({"hue": "up"}, "fields_not_tested", id="hue_unsupported_on_hue"),
    ],
)
async def test_attributes_out_of_scope_are_refused(hass, bridge, data, reason):
    entity_id = await lamp(hass, bridge)

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "move", {"entity_id": entity_id, **data})

    assert raised.value.translation_placeholders["summary"] == f"light.lamp: {reason}"
    assert bridge.puts == []


@pytest.mark.parametrize(
    ("data", "key"),
    [
        pytest.param({"sweep_time": 5}, "nothing_to_move", id="no_direction"),
        pytest.param({"color_temp": "warmer", "brightness_limit": 20}, "limit_without_direction", id="orphan_limit"),
    ],
)
async def test_parse_refuses_a_call_with_nothing_to_move(hass, bridge, data, key):
    entity_id = await lamp(hass, bridge)

    with pytest.raises(ServiceValidationError) as raised:
        await call(hass, "move", {"entity_id": entity_id, **data})

    assert raised.value.translation_key == key


async def test_stop_halts_a_room_with_one_write(hass, bridge):
    entity_id = await room(hass, bridge)

    response = await call(hass, "stop", {"entity_id": entity_id})

    assert response == {entity_id: SENT}
    assert bridge.puts == [("grouped_light/grouped-1", {"dimming_delta": {"action": "stop"}})]


async def test_stop_on_a_light_without_dimming_is_unsupported(hass, bridge):
    entity_id = await lamp(hass, bridge, brightness=None, mirek=None)

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "stop", {"entity_id": entity_id})

    assert raised.value.translation_placeholders["summary"] == "light.lamp: not_dimmable"


@pytest.mark.parametrize("action", ["move", "stop"])
async def test_resource_missing_from_the_bridge_is_rejected(hass, bridge, action):
    entry = await hue_entry(hass, bridge)
    add_hue_entity(hass, entry, "light.gone", "light-gone", state="on")
    data = {"brightness": "up"} if action == "move" else {}

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, action, {"entity_id": "light.gone", **data})

    assert raised.value.translation_placeholders["summary"] == "light.gone: not_on_bridge"


@pytest.mark.parametrize("action", ["move", "stop"])
async def test_v1_bridge_is_refused(hass, bridge, action):
    bridge.light("light-1")
    entry = await hue_entry(hass, bridge, api_version=1)
    add_hue_entity(hass, entry, "light.lamp", "light-1")
    data = {"brightness": "up"} if action == "move" else {}

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, action, {"entity_id": "light.lamp", **data})

    assert raised.value.translation_placeholders["summary"] == "light.lamp: bridge_v1"


@pytest.mark.parametrize("target", ["light", "room"])
async def test_get_attributes_predicts_brightness_mid_move(hass, bridge, clock, target):
    # hue_dimmer RELEASE_CHECKLIST §4.2: the bridge reports the end value; get_attributes reports the predicted one.
    if target == "light":
        entity_id = await lamp(hass, bridge, brightness_pct=20.0)
    else:
        entity_id = await room(hass, bridge, brightness_pct=20.0)
    await call(hass, "move", {"entity_id": entity_id, "brightness": "up", "sweep_time": 10})
    clock.now += 3

    response = await call(hass, "get_attributes", {"entity_id": entity_id})

    assert response[entity_id]["brightness"] == 50.0


async def test_get_attributes_predicts_a_room_moving_up_from_all_off(hass, bridge, clock):
    # aiohue still shows every light off until the bridge's event arrives; the room row is predicted anyway.
    entity_id = await room(hass, bridge, state="off")
    await call(hass, "move", {"entity_id": entity_id, "brightness": "up", "sweep_time": 10})
    clock.now += 4

    response = await call(hass, "get_attributes", {"entity_id": entity_id})

    assert response[entity_id]["brightness"] == 40.0


async def mixed_room(hass, bridge, one_pct: float | None, two_pct: float | None) -> str:
    """A room whose lights are on at the given percent, or off for None."""
    for light_id, pct in (("one", one_pct), ("two", two_pct)):
        bridge.light(light_id, on=pct is not None, brightness=pct or 40.0)
    lit = [pct for pct in (one_pct, two_pct) if pct is not None]
    bridge.room("grouped-1", ["one", "two"], brightness=sum(lit) / len(lit) if lit else 0.0)
    entry = await hue_entry(hass, bridge)
    for light_id, pct in (("one", one_pct), ("two", two_pct)):
        attributes = {"brightness": percent(pct)} if pct is not None else {}
        add_hue_entity(hass, entry, f"light.{light_id}", light_id, state="on" if pct else "off", attributes=attributes)
    add_hue_group(hass, entry, "light.room", "grouped-1", ["light.one", "light.two"])
    return "light.room"


async def test_room_move_predicts_each_light(hass, bridge, clock):
    entity_id = await mixed_room(hass, bridge, 20.0, 60.0)
    await call(hass, "move", {"entity_id": entity_id, "brightness": "up", "sweep_time": 10})
    clock.now += 3  # 6 s from the average 40 %: each light covers half of its own distance to 100 %

    response = await call(hass, "get_attributes", {"entity_id": [entity_id, "light.one", "light.two"]})

    assert bridge.puts == [("grouped_light/grouped-1", move_put(100.0, 6000, on=True))]
    assert response["light.one"]["brightness"] == 60.0
    assert response["light.two"]["brightness"] == 80.0
    assert response["light.room"]["brightness"] == 70.0


@pytest.mark.parametrize("first", ["move", "stop"])
async def test_a_light_moved_mid_room_move_starts_where_it_is(hass, bridge, clock, first):
    # The bridge already reports the room's end value for the light; its own prediction says 60 %.
    entity_id = await mixed_room(hass, bridge, 100.0, 100.0)
    await call(hass, "move", {"entity_id": entity_id, "brightness": "down", "sweep_time": 10})
    hass.states.async_set("light.one", "off", {})
    clock.now += 4
    if first == "stop":
        await call(hass, "stop", {"entity_id": "light.one"})
        clock.now += 2

    await call(hass, "move", {"entity_id": "light.one", "brightness": "up", "sweep_time": 10})

    assert bridge.puts[-1] == ("light/one", move_put(100.0, 4000, on=True))


async def test_room_down_leaves_its_off_lights_out(hass, bridge, clock):
    # Only the lit light sets the duration and is predicted; the off one stays off and out of the average.
    entity_id = await mixed_room(hass, bridge, 80.0, None)
    await call(hass, "move", {"entity_id": entity_id, "brightness": "down", "brightness_limit": 20})
    clock.now += 1.5

    response = await call(hass, "get_attributes", {"entity_id": [entity_id, "light.two"]})

    assert bridge.puts == [("grouped_light/grouped-1", move_put(20.0, 3000))]
    assert response["light.room"]["brightness"] == 50.0
    assert response["light.two"]["brightness"] == 40.0


async def test_room_reads_a_light_moved_on_its_own(hass, bridge, clock):
    entity_id = await mixed_room(hass, bridge, 40.0, 40.0)
    await call(hass, "move", {"entity_id": "light.one", "brightness": "up", "sweep_time": 10})
    clock.now += 3

    response = await call(hass, "get_attributes", {"entity_id": entity_id})

    assert response["light.room"]["brightness"] == 55.0


async def test_room_stop_mid_move_up_from_off_holds_each_light(hass, bridge, clock):
    # aiohue still shows both lights off; they count as lit because they are still moving.
    entity_id = await mixed_room(hass, bridge, None, None)
    await call(hass, "move", {"entity_id": entity_id, "brightness": "up", "sweep_time": 10})
    clock.now += 3
    await call(hass, "stop", {"entity_id": entity_id})
    clock.now += 10

    response = await call(hass, "get_attributes", {"entity_id": [entity_id, "light.one"]})

    assert bridge.puts[1] == ("grouped_light/grouped-1", STOP)
    assert response["light.one"]["brightness"] == 30.0
    assert response["light.room"]["brightness"] == 30.0


def report_off(bridge, *light_ids: str) -> None:
    """What the bridge reports at the start of a soft off: each light off, at once."""
    for light_id in light_ids:
        bridge.api.lights[light_id].on.on = False


async def test_stop_cuts_our_soft_off_with_on_and_the_predicted_brightness(hass, bridge, clock):
    # The bridge refuses a dimming stop during a soft off; on: true with a brightness and no duration ends it there.
    entity_id = await lamp(hass, bridge, brightness_pct=100.0)
    await call(hass, "move", {"entity_id": entity_id, "brightness": "down", "sweep_time": 10})
    report_off(bridge, "light-1")
    hass.states.async_set(entity_id, "off", {})
    clock.now += 3

    response = await call(hass, "stop", {"entity_id": entity_id})
    clock.now += 10
    read = await call(hass, "get_attributes", {"entity_id": entity_id})

    assert response == {entity_id: SENT}
    assert bridge.puts[1] == ("light/light-1", {"on": {"on": True}, "dimming": {"brightness": 70.0}})
    assert read[entity_id]["brightness"] == 70.0


async def test_stop_cuts_a_rooms_soft_off_light_by_light(hass, bridge, clock):
    # Measured on a single light only, so each light gets its own write at its own prediction.
    entity_id = await mixed_room(hass, bridge, 100.0, 50.0)
    await call(hass, "move", {"entity_id": entity_id, "brightness": "down", "sweep_time": 10})
    report_off(bridge, "one", "two")
    clock.now += 2.5  # 7.5 s from the average 75 %: a third of the way down for each light

    response = await call(hass, "stop", {"entity_id": entity_id})

    assert response == {entity_id: SENT}
    assert bridge.puts[0] == ("grouped_light/grouped-1", {"on": {"on": False}, "dynamics": {"duration": 7500}})
    assert sorted(bridge.puts[1:]) == [
        ("light/one", {"on": {"on": True}, "dimming": {"brightness": pytest.approx(200 / 3)}}),
        ("light/two", {"on": {"on": True}, "dimming": {"brightness": pytest.approx(100 / 3)}}),
    ]


async def test_room_cut_stops_a_light_moving_on_its_own(hass, bridge, clock):
    # One light turned back up mid soft off isn't fading off: it takes the dimming stop, not the cut.
    entity_id = await mixed_room(hass, bridge, 100.0, 100.0)
    await call(hass, "move", {"entity_id": entity_id, "brightness": "down", "sweep_time": 10})
    report_off(bridge, "one", "two")
    clock.now += 4
    await call(hass, "move", {"entity_id": "light.one", "brightness": "up", "sweep_time": 10})
    clock.now += 1

    await call(hass, "stop", {"entity_id": entity_id})

    assert sorted(bridge.puts[2:]) == [
        ("light/one", STOP),
        ("light/two", {"on": {"on": True}, "dimming": {"brightness": pytest.approx(50.0)}}),
    ]


@pytest.mark.parametrize("target", ["light", "room"])
async def test_stop_on_an_off_light_sends_nothing(hass, bridge, target):
    # Off, or fading off from elsewhere (the bridge reports off at the start): nothing to predict or stop.
    entity_id = await (lamp if target == "light" else room)(hass, bridge, state="off")

    response = await call(hass, "stop", {"entity_id": entity_id})

    assert response == {entity_id: {"status": "unchanged", "integration": "hue", "detail": "off"}}
    assert bridge.puts == []


async def test_stop_after_our_soft_off_ends_sends_nothing(hass, bridge, clock):
    entity_id = await lamp(hass, bridge, brightness_pct=100.0)
    await call(hass, "move", {"entity_id": entity_id, "brightness": "down", "sweep_time": 2})
    report_off(bridge, "light-1")
    hass.states.async_set(entity_id, "off", {})
    clock.now += 3

    response = await call(hass, "stop", {"entity_id": entity_id})

    assert response[entity_id]["detail"] == "off"
    assert bridge.puts == [("light/light-1", {"on": {"on": False}, "dynamics": {"duration": 2000}})]


async def test_up_after_our_soft_off_starts_at_the_bottom(hass, bridge, clock):
    entity_id = await lamp(hass, bridge, brightness_pct=60.0)
    await call(hass, "move", {"entity_id": entity_id, "brightness": "down", "sweep_time": 5})
    hass.states.async_set(entity_id, "off", {})
    clock.now += 4

    await call(hass, "move", {"entity_id": entity_id, "brightness": "up", "sweep_time": 5})

    assert bridge.puts[1] == ("light/light-1", move_put(100.0, 5000, on=True))


async def test_a_change_from_elsewhere_mid_move_starts_the_next_move_from_it(hass, bridge, clock):
    # The Hue app sets 80 % 3 s into a 20 % to 100 % fade: the next move starts there, not at the predicted 50 %.
    entity_id = await lamp(hass, bridge, brightness_pct=20.0)
    await call(hass, "move", {"entity_id": entity_id, "brightness": "up", "sweep_time": 10})
    clock.now += 3
    bridge.api.events.emit(
        EventType.RESOURCE_UPDATED, {"id": "light-1", "type": "light", "dimming": {"brightness": 80}}
    )
    hass.states.async_set(entity_id, "on", {"brightness": percent(80.0)})
    await hass.async_block_till_done()

    await call(hass, "move", {"entity_id": entity_id, "brightness": "down", "sweep_time": 10})

    assert bridge.puts[-1] == ("light/light-1", {"on": {"on": False}, "dynamics": {"duration": 8000}})


async def test_a_late_stop_report_keeps_the_prediction(hass, bridge, clock):
    entity_id = await lamp(hass, bridge, brightness_pct=20.0)
    await call(hass, "move", {"entity_id": entity_id, "brightness": "up", "sweep_time": 10})
    clock.now += 3
    await call(hass, "stop", {"entity_id": entity_id})
    clock.now += 5
    bridge.api.events.emit(
        EventType.RESOURCE_UPDATED, {"id": "light-1", "type": "light", "dimming": {"brightness": 50.2}}
    )
    await hass.async_block_till_done()

    await call(hass, "move", {"entity_id": entity_id, "brightness": "down", "sweep_time": 10})

    assert bridge.puts[-1] == ("light/light-1", {"on": {"on": False}, "dynamics": {"duration": 5000}})  # from 50 %


@pytest.mark.parametrize(
    ("service", "data"),
    [
        pytest.param("set_attributes", {"brightness": 80}, id="set_attributes"),
        pytest.param("turn_on", {}, id="ha_light_call"),
    ],
)
async def test_a_write_mid_move_starts_the_next_move_from_the_report(hass, bridge, clock, service, data):
    entity_id = await lamp(hass, bridge, brightness_pct=20.0)
    async_mock_service(hass, "light", "turn_on")
    await call(hass, "move", {"entity_id": entity_id, "brightness": "up", "sweep_time": 10})
    clock.now += 3
    if service == "turn_on":
        await hass.services.async_call("light", "turn_on", {"entity_id": entity_id}, blocking=True)
    else:
        await call(hass, service, {"entity_id": entity_id, **data})
    hass.states.async_set(entity_id, "on", {"brightness": percent(80.0)})

    await call(hass, "move", {"entity_id": entity_id, "brightness": "down", "sweep_time": 10})

    assert bridge.puts[-1] == ("light/light-1", {"on": {"on": False}, "dynamics": {"duration": 8000}})
