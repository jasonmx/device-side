"""predicted_state: the bridge's reports of our fades hidden from aiohue (so HA), and device_side's predictions sent."""

import asyncio
import logging

import pytest
from aiohue.v2.controllers.events import EventType
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.device_side.core.runtime import get_runtime
from custom_components.device_side.integrations.hue.move import end_echo
from custom_components.device_side.integrations.hue.transition_cache import MIN_BRIGHTNESS_STEP, transition_cache

from .conftest import light_event, setup_room
from ...conftest import advance, call, wall_clock_now
from ...fixtures.hue import add_hue_entity, add_hue_group, hue_entry

pytestmark = pytest.mark.usefixtures("setup_production")

# light "one" from 20 % to full at sweep_time 10 takes 8 s.
FADE_S = 8.0


async def settle(hass) -> None:
    """Let HA's tasks finish, then aiohue's: it applies events in bare tasks, which block_till_done doesn't wait on."""
    await hass.async_block_till_done()
    for _ in range(3):
        await asyncio.sleep(0)


def report(bridge, event: dict) -> None:
    bridge.api.events.emit(EventType.RESOURCE_UPDATED, event)


def shown(bridge, light_id: str) -> tuple[bool, float]:
    """What aiohue holds for the light, which is what HA shows."""
    light = bridge.api.lights[light_id]
    return light.on.on, light.dimming.brightness


def room_shown(bridge) -> tuple[bool, float | None]:
    group = bridge.api.groups.grouped_light["1"]
    return group.on.on, group.dimming.brightness if group.dimming else None


async def raise_one(hass) -> None:
    await call(hass, "move", {"entity_id": "light.one", "brightness": "up", "sweep_time": 10})


async def test_aiohue_applies_an_event_after_a_synchronous_subscriber(bridge):
    # Hiding rests on this: aiohue's controllers apply an event in a task, so a synchronous subscriber edits it first.
    bridge.light("one", on=True, brightness=20.0)
    api = await bridge.load()

    def edit(_event_type, data):
        data["dimming"]["brightness"] = 33.0

    api.events.subscribe(edit, event_filter=EventType.RESOURCE_UPDATED)
    report(bridge, light_event("one", brightness=90.0))
    assert api.lights["one"].dimming.brightness == 20.0
    await asyncio.sleep(0)

    assert api.lights["one"].dimming.brightness == 33.0


async def test_ha_holds_the_start_value_while_the_fade_runs(hass, bridge, clock):
    await setup_room(hass, bridge)
    await raise_one(hass)

    report(bridge, light_event("one", brightness=100.0))  # the bridge's end value, at the start
    clock.now += 3.0
    report(bridge, light_event("one", brightness=45.0))  # the bulb, a little late
    await settle(hass)

    assert shown(bridge, "one") == (True, 20.0)


async def test_the_end_is_shown_once_the_fade_has_run(hass, bridge, clock):
    await setup_room(hass, bridge)
    start = wall_clock_now()
    await raise_one(hass)
    report(bridge, light_event("one", brightness=100.0))

    await advance(hass, start, FADE_S - 0.5)
    assert shown(bridge, "one") == (True, 20.0)
    await advance(hass, start, FADE_S + 0.1)
    assert shown(bridge, "one") == (True, 100.0)


async def test_a_stop_shows_the_halt_and_drops_the_end(hass, bridge, clock):
    await setup_room(hass, bridge)
    start = wall_clock_now()
    await raise_one(hass)
    clock.now += 4.0

    await call(hass, "stop", {"entity_id": "light.one"})
    await settle(hass)
    assert shown(bridge, "one") == (True, 60.0)

    await advance(hass, start, FADE_S + 1)
    assert shown(bridge, "one") == (True, 60.0)


async def test_a_real_change_shows_at_once_and_drops_the_end(hass, bridge, clock):
    await setup_room(hass, bridge)
    start = wall_clock_now()
    await raise_one(hass)

    report(bridge, light_event("one", brightness=90.0))  # the Hue app
    await advance(hass, start, FADE_S + 1)

    assert shown(bridge, "one") == (True, 90.0)


async def test_a_change_from_ha_drops_the_end(hass, bridge, clock):
    await setup_room(hass, bridge)
    async_mock_service(hass, "light", "turn_on")
    start = wall_clock_now()
    await raise_one(hass)

    await hass.services.async_call("light", "turn_on", {"entity_id": "light.one"}, blocking=True)
    report(bridge, light_event("one", brightness=55.0))  # what the turn_on set, though on the path
    await advance(hass, start, FADE_S + 1)

    assert shown(bridge, "one") == (True, 55.0)


async def test_a_color_change_from_ha_mid_fade_hands_ha_back_to_the_bridge(hass, bridge, clock):
    # Nothing will show the fade's end now, so HA shows the end the bridge reported at its start.
    await setup_room(hass, bridge)
    async_mock_service(hass, "light", "turn_on")
    await raise_one(hass)
    report(bridge, light_event("one", brightness=100.0))
    clock.now += 2.0

    warmer = {"entity_id": "light.one", "color_temp_kelvin": 3000}
    await hass.services.async_call("light", "turn_on", warmer, blocking=True)
    await settle(hass)

    assert shown(bridge, "one") == (True, 100.0)


async def test_a_change_from_ha_after_a_stop_keeps_the_halt(hass, bridge, clock):
    await setup_room(hass, bridge)
    async_mock_service(hass, "light", "turn_on")
    await raise_one(hass)
    report(bridge, light_event("one", brightness=100.0))
    clock.now += 4.0
    await call(hass, "stop", {"entity_id": "light.one"})

    warmer = {"entity_id": "light.one", "color_temp_kelvin": 3000}
    await hass.services.async_call("light", "turn_on", warmer, blocking=True)
    await settle(hass)

    assert shown(bridge, "one") == (True, 60.0)


async def test_unloading_mid_fade_hands_ha_back_to_the_bridge(hass, bridge, clock, setup_production):
    await setup_room(hass, bridge)
    await raise_one(hass)
    report(bridge, light_event("one", brightness=100.0))
    await settle(hass)

    assert await hass.config_entries.async_unload(setup_production.entry_id)
    await settle(hass)

    assert shown(bridge, "one") == (True, 100.0)


async def test_set_attributes_mid_fade_reaches_ha(hass, bridge, clock):
    await setup_room(hass, bridge)
    start = wall_clock_now()
    await raise_one(hass)
    clock.now += 4.0

    await call(hass, "set_attributes", {"entity_id": "light.one", "brightness": 40})
    report(bridge, light_event("one", brightness=40.0))  # on the path, but a write of its own
    await advance(hass, start, FADE_S + 1)

    assert shown(bridge, "one") == (True, 40.0)


async def test_a_soft_off_stays_on_until_its_end(hass, bridge, clock):
    await setup_room(hass, bridge)
    start = wall_clock_now()
    await call(hass, "move", {"entity_id": "light.one", "brightness": "down", "sweep_time": 10})  # 2 s

    report(bridge, light_event("one", on=False))
    await settle(hass)
    assert shown(bridge, "one") == (True, 20.0)

    await advance(hass, start, 2.1)
    assert shown(bridge, "one") == (False, 20.0)  # the bridge keeps the brightness through a soft off


async def test_up_from_off_shows_on_at_the_dimmest(hass, bridge, clock):
    bridge.light("one", on=False, brightness=60.0)
    entry = await hue_entry(hass, bridge)
    add_hue_entity(hass, entry, "light.one", "one")
    bridge.api.lights["one"].dimming.min_dim_level = 2.0

    await call(hass, "move", {"entity_id": "light.one", "brightness": "up", "sweep_time": 10})
    report(bridge, light_event("one", on=True, brightness=100.0))
    await settle(hass)

    assert shown(bridge, "one") == (True, 2.0)


async def test_up_from_off_without_a_min_dim_level_shows_the_dimmest_step(hass, bridge, clock):
    bridge.light("one", on=False, brightness=60.0)
    entry = await hue_entry(hass, bridge)
    add_hue_entity(hass, entry, "light.one", "one")

    await call(hass, "move", {"entity_id": "light.one", "brightness": "up", "sweep_time": 10})
    report(bridge, light_event("one", on=True))
    await settle(hass)

    assert shown(bridge, "one") == (True, MIN_BRIGHTNESS_STEP)


async def test_a_room_shows_the_mean_of_its_lit_lights(hass, bridge, clock):
    await setup_room(hass, bridge)
    await call(hass, "move", {"entity_id": "light.room", "brightness": "up", "sweep_time": 10})
    report(bridge, {"id": "1", "type": "grouped_light", "dimming": {"brightness": 100.0}})
    await settle(hass)
    assert room_shown(bridge) == (True, 20.0)

    clock.now += 4.0
    await call(hass, "stop", {"entity_id": "light.room"})
    await settle(hass)

    assert room_shown(bridge) == (True, 60.0)
    assert shown(bridge, "one") == shown(bridge, "two") == (True, 60.0)


async def test_a_room_up_from_off_shows_on(hass, bridge, clock):
    bridge.light("one", on=False, brightness=60.0)
    bridge.light("two", on=False, brightness=60.0)
    bridge.room("1", ["one", "two"], brightness=60.0)
    entry = await hue_entry(hass, bridge)
    members = [add_hue_entity(hass, entry, f"light.{light_id}", light_id) for light_id in ("one", "two")]
    add_hue_group(hass, entry, "light.room", "1", members)

    await call(hass, "move", {"entity_id": "light.room", "brightness": "up", "sweep_time": 10})
    report(bridge, {"id": "1", "type": "grouped_light", "on": {"on": True}, "dimming": {"brightness": 100.0}})
    for light_id in ("one", "two"):
        report(bridge, light_event(light_id, on=True, brightness=100.0))
    await settle(hass)

    assert room_shown(bridge) == (True, MIN_BRIGHTNESS_STEP)


async def test_a_hidden_end_value_is_what_the_next_echo_is_worked_out_from(hass, bridge, clock):
    # aiohue holds the halt; the bridge still holds the end value it reported, so a move back to it reports nothing.
    await setup_room(hass, bridge)
    cache = transition_cache(hass)
    await raise_one(hass)
    report(bridge, light_event("one", brightness=100.0))
    clock.now += 4.0
    await call(hass, "stop", {"entity_id": "light.one"})
    await settle(hass)
    light = bridge.api.lights["one"]

    assert light.dimming.brightness == 60.0
    assert end_echo(cache, light, 100.0, up=True) == {}
    assert end_echo(cache, light, 80.0, up=True) == {"brightness": 80.0}

    report(bridge, light_event("one", brightness=62.0))  # a report that reaches aiohue: it holds the bridge's again
    clock.now += 60.0
    report(bridge, light_event("one", brightness=62.0))
    await settle(hass)
    assert end_echo(cache, light, 100.0, up=True) == {"brightness": 100.0}


async def test_option_off_shows_what_the_bridge_reports(hass, bridge, clock):
    get_runtime(hass).predicted_state = False
    await setup_room(hass, bridge)
    start = wall_clock_now()
    await raise_one(hass)

    report(bridge, light_event("one", brightness=100.0))
    await settle(hass)
    assert shown(bridge, "one") == (True, 100.0)

    clock.now += 4.0
    await call(hass, "stop", {"entity_id": "light.one"})
    await advance(hass, start, FADE_S + 1)
    assert shown(bridge, "one") == (True, 100.0)


async def test_an_aiohue_that_applies_events_at_once_falls_back_to_the_bridge(hass, bridge, clock, caplog):
    await setup_room(hass, bridge)
    bridge.api.lights._handle_event = lambda *_args: None

    with caplog.at_level(logging.WARNING):
        await raise_one(hass)
    report(bridge, light_event("one", brightness=100.0))
    await settle(hass)

    assert "Hue fades show what the bridge reports" in caplog.text
    assert shown(bridge, "one") == (True, 100.0)
