"""The xy write-back after a hue or saturation stop: HA drops the hs color Z2M publishes for a light listed with xy."""

import logging

import pytest

from custom_components.device_side.integrations.zigbee2mqtt import xy_writeback

from .conftest import commands, group, light
from ...conftest import advance, call, wall_clock_now
from ...fixtures.z2m import IEEE

pytestmark = pytest.mark.usefixtures("setup_production", "clock")

SENT = {"status": "sent", "integration": "zigbee2mqtt"}
SET = f"zigbee2mqtt/{IEEE}/set"
GET = f"zigbee2mqtt/{IEEE}/get"
COLOR_READ = {"cluster": "lightingColorCtrl", "attributes": ["colorMode", "currentX", "currentY"]}
# The bulb's own x/y from conftest.COLOR, with no transition: the bulb doesn't change, and Z2M publishes xy.
WRITE_BACK = (SET, {"color": {"x": 0.3, "y": 0.4}, "transition": 0})
COLOR_GET = (GET, {"color": ""})
LOGGER = "custom_components.device_side.integrations.zigbee2mqtt.xy_writeback"


async def stop_after(hass, broker, entity_id: str, move: dict) -> list:
    """Move, stop, then let the write-back run: what it published after the stop."""
    start = wall_clock_now()
    await call(hass, "move", {"entity_id": entity_id, **move})
    response = await call(hass, "stop", {"entity_id": entity_id})
    assert response == {entity_id: SENT}
    stopped = len(commands(broker))
    await advance(hass, start, xy_writeback.DELAY_S + 0.5)
    return commands(broker)[stopped:]


def color_reads(broker) -> list[tuple[str, dict]]:
    return [(topic, {k: v for k, v in read.items() if k != "state_property"}) for topic, read in broker.reads()]


async def test_a_light_in_hs_mode_gets_its_own_xy_written_back(hass, broker):
    entity_id = light(hass, broker)

    published = await stop_after(hass, broker, entity_id, {"hue": "up"})

    assert color_reads(broker) == [(SET, COLOR_READ)]
    assert published == [WRITE_BACK]


async def test_a_light_not_in_hs_mode_gets_a_color_get_and_no_write(hass, broker):
    # After a stop of an xy fade, Z2M's read-back carries its cached x/y, the fade's end point.
    entity_id = light(hass, broker, color={"colorMode": 1})

    published = await stop_after(hass, broker, entity_id, {"saturation": "down"})

    assert color_reads(broker) == [(SET, COLOR_READ)]
    assert published == [COLOR_GET]


async def test_a_light_listed_with_hs_gets_nothing_after_a_hue_stop(hass, broker):
    # Z2M's own read-back publishes hs, which HA takes for it.
    entity_id = light(hass, broker, modes=["hs"])

    published = await stop_after(hass, broker, entity_id, {"hue": "up"})

    assert broker.reads() == []
    assert published == []


async def test_a_light_listed_with_hs_gets_a_color_get_after_a_saturation_stop(hass, broker):
    # The raw stopMoveStep publishes nothing.
    entity_id = light(hass, broker, modes=["hs"])

    published = await stop_after(hass, broker, entity_id, {"saturation": "up"})

    assert broker.reads() == []
    assert published == [COLOR_GET]


async def test_a_brightness_stop_brings_no_color_in_line(hass, broker):
    entity_id = light(hass, broker)

    published = await stop_after(hass, broker, entity_id, {"brightness": "up"})

    assert broker.reads() == []
    assert published == []


async def test_each_group_member_is_read_and_written_on_its_own(hass, broker):
    # Z2M reads a group's stop back from its first member only, so a member listed with hs gets a color get too.
    room = group(hass, broker, one={}, two={"modes": ["hs"]})

    published = await stop_after(hass, broker, room, {"hue": "up"})

    assert color_reads(broker) == [("zigbee2mqtt/0x01/set", COLOR_READ)]
    assert published == [
        ("zigbee2mqtt/0x02/get", {"color": ""}),
        ("zigbee2mqtt/0x01/set", {"color": {"x": 0.3, "y": 0.4}, "transition": 0}),
    ]


async def test_a_failed_read_is_logged_and_the_group_carries_on(hass, broker, caplog):
    room = group(hass, broker, one={}, two={})
    broker.read_errors[("0x01", "lightingColorCtrl")] = "UNSUPPORTED_ATTRIBUTE"

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        published = await stop_after(hass, broker, room, {"hue": "up"})

    assert "Couldn't bring Home Assistant's color for light.one in line" in caplog.text
    assert published == [("zigbee2mqtt/0x02/set", {"color": {"x": 0.3, "y": 0.4}, "transition": 0})]


async def test_a_failed_write_is_logged(hass, broker, caplog, monkeypatch):
    entity_id = light(hass, broker)

    async def refuse(hass, mqtt_topic, payload):
        raise RuntimeError("broker gone")

    monkeypatch.setattr(xy_writeback, "publish", refuse)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        await stop_after(hass, broker, entity_id, {"hue": "up"})

    assert "color for light.lamp in line, so it may be stale: broker gone" in caplog.text


async def test_no_bridge_groups_is_logged(hass, broker, caplog):
    room = group(hass, broker, one={}, two={})
    start = wall_clock_now()
    await call(hass, "move", {"entity_id": room, "hue": "up"})
    await call(hass, "stop", {"entity_id": room})
    del broker.retained["zigbee2mqtt/bridge/groups"]

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        await advance(hass, start, xy_writeback.DELAY_S + 0.5)

    assert "Couldn't bring Home Assistant's color for light.room in line" in caplog.text
