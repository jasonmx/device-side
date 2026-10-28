"""Matter get_attributes: one live OnTime read per target, shaped as the shared timer row."""

from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from ...conftest import call, refusal
from ...fixtures.matter import NODE_ID, add_matter_entity, matter_device, on_time_reads

pytestmark = pytest.mark.usefixtures("setup_production")

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
EP = 1


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch):
    monkeypatch.setattr(dt_util, "utcnow", lambda: NOW)


def timer(remaining_s: float) -> dict:
    ends_at = (NOW + timedelta(seconds=remaining_s)).isoformat()
    return {"turns": "off", "ends_at": ends_at, "remaining_s": remaining_s}


async def test_running_timer_is_read_live(hass):
    entry, _, read_attr = matter_device(hass, endpoint_id=EP)
    read_attr.side_effect = on_time_reads(125).side_effect  # tenths of a second
    add_matter_entity(hass, entry, "switch.plug", endpoint_id=EP, state="on")

    response = await call(hass, "get_attributes", {"entity_id": "switch.plug"})

    assert response == {"switch.plug": {"timer": timer(12.5)}}
    read_attr.assert_awaited_once_with(node_id=NODE_ID, attribute_path=f"{EP}/6/16385")


@pytest.mark.parametrize("answer", [{f"{EP}/6/16385": 0}, {}], ids=["zero", "path_missing"])
async def test_no_timer_reports_an_empty_row(hass, answer):
    entry, _, read_attr = matter_device(hass, endpoint_id=EP)
    read_attr.side_effect = None
    read_attr.return_value = answer
    add_matter_entity(hass, entry, "switch.plug", endpoint_id=EP)

    assert await call(hass, "get_attributes", {"entity_id": "switch.plug"}) == {"switch.plug": {}}


async def test_no_lt_feature_is_refused(hass):
    entry, _, read_attr = matter_device(hass, endpoint_id=EP, feature_map=0x0000)
    add_matter_entity(hass, entry, "switch.no_lt", endpoint_id=EP)

    assert await refusal(hass, "get_attributes", {"entity_id": "switch.no_lt"}) == "no_lt_feature"
    read_attr.assert_not_awaited()


async def test_light_is_out_of_scope(hass):
    entry, _, read_attr = matter_device(hass, endpoint_id=EP)
    add_matter_entity(hass, entry, "light.bulb", endpoint_id=EP)

    assert await refusal(hass, "get_attributes", {"entity_id": "light.bulb"}) == "domain_not_tested"
    read_attr.assert_not_awaited()


async def test_unparsable_unique_id_is_refused(hass):
    entry, _, read_attr = matter_device(hass, endpoint_id=EP)
    add_matter_entity(hass, entry, "switch.broken", unique_id="bad-uid")

    assert await refusal(hass, "get_attributes", {"entity_id": "switch.broken"}) == "not_addressable"
    read_attr.assert_not_awaited()


async def test_unreachable_node_is_refused(hass):
    entry, _, read_attr = matter_device(hass, endpoint_id=EP)
    entry.runtime_data.adapter.matter_client.get_node.return_value = None
    add_matter_entity(hass, entry, "switch.gone", endpoint_id=EP)

    assert await refusal(hass, "get_attributes", {"entity_id": "switch.gone"}) == "not_addressable"
    read_attr.assert_not_awaited()


async def test_read_error_raises(hass):
    entry, _, read_attr = matter_device(hass, endpoint_id=EP)
    read_attr.side_effect = ConnectionError("device unreachable")
    add_matter_entity(hass, entry, "switch.plug", endpoint_id=EP)

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "get_attributes", {"entity_id": "switch.plug"})

    assert raised.value.translation_key == "targets_failed"
    assert raised.value.translation_placeholders == {"summary": "switch.plug: error"}


async def test_two_targets_read_in_one_call(hass):
    entry, _, read_attr = matter_device(hass, endpoint_id=EP)
    on_times = {"1/6/16385": 50, "2/6/16385": 0}
    read_attr.side_effect = lambda node_id, attribute_path: {attribute_path: on_times[attribute_path]}
    entry.runtime_data.adapter.matter_client.get_node.return_value.node_data.attributes["2/6/65532"] = 0x0001
    add_matter_entity(hass, entry, "switch.timed", endpoint_id=1, state="on")
    add_matter_entity(hass, entry, "switch.idle", endpoint_id=2)

    response = await call(hass, "get_attributes", {"entity_id": ["switch.timed", "switch.idle"]})

    assert response == {"switch.timed": {"timer": timer(5.0)}, "switch.idle": {}}
