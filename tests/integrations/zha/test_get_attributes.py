"""ZHA get_attributes: live OnOff, Level and Color reads per light, shaped as Hue's row plus the shared timer row."""

from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from homeassistant.util.color import color_hs_to_RGB, color_hs_to_xy, color_xy_to_hs, color_xy_to_RGB

from custom_components.device_side.integrations.zha import zcl

from ...conftest import call, refusal
from ...fixtures.zha import IEEE, add_zha_entity, zha_entry, zha_group

pytestmark = pytest.mark.usefixtures("setup_production")

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
ONOFF = {"supported_color_modes": ["onoff"]}
DIMMABLE = {"supported_color_modes": ["brightness"]}
COLOR = {"supported_color_modes": ["color_temp", "xy"]}


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch):
    monkeypatch.setattr(dt_util, "utcnow", lambda: NOW)


@pytest.fixture
def requests() -> list[tuple[str, int]]:
    """Each read request as (ieee, cluster), in order."""
    return []


@pytest.fixture
def bulb(monkeypatch, requests) -> dict:
    """The fake light's attributes by cluster, read through a fake zcl.read_attributes that records each request.

    Like the real one, it raises when a required attribute is missing and leaves out missing optional ones.
    """
    clusters: dict[int, dict[int, int]] = {zcl.ON_OFF_CLUSTER: {zcl.ON_OFF: 0, zcl.ON_TIME: 0}}

    async def read_attributes(hass, addr, cluster_id, attributes, optional=()):
        requests.append((addr.ieee, cluster_id))
        values = clusters[cluster_id]
        for attribute in attributes:
            if attribute not in values:
                raise LookupError(f"Attribute 0x{attribute:04x} not read")
        return {attribute: values[attribute] for attribute in (*attributes, *optional) if attribute in values}

    monkeypatch.setattr(zcl, "read_attributes", read_attributes)
    return clusters


def clusters_read(requests) -> list[int]:
    return [cluster for _, cluster in requests]


def timer(remaining_s: float) -> dict:
    return {"turns": "off", "ends_at": (NOW + timedelta(seconds=remaining_s)).isoformat(), "remaining_s": remaining_s}


def xy_row(x: float, y: float) -> dict:
    return {"xy_color": [x, y], "rgb_color": list(color_xy_to_RGB(x, y)), "hs_color": list(color_xy_to_hs(x, y))}


def hs_row(h: float, s: float) -> dict:
    return {"hs_color": [h, s], "rgb_color": list(color_hs_to_RGB(h, s)), "xy_color": list(color_hs_to_xy(h, s))}


async def test_on_off_light_reads_only_on_off(hass, bulb, requests):
    add_zha_entity(hass, zha_entry(hass), "light.bulb", attributes=ONOFF)

    assert await call(hass, "get_attributes", {"entity_id": "light.bulb"}) == {"light.bulb": {}}
    assert clusters_read(requests) == [zcl.ON_OFF_CLUSTER]


@pytest.mark.parametrize("on", [1, 0])
async def test_dimmable_light_reads_brightness_on_or_off(hass, bulb, requests, on):
    add_zha_entity(hass, zha_entry(hass), "light.bulb", state="on" if on else "off", attributes=DIMMABLE)
    bulb[zcl.ON_OFF_CLUSTER][zcl.ON_OFF] = on
    bulb[zcl.LEVEL_CLUSTER] = {zcl.CURRENT_LEVEL: 102}

    assert await call(hass, "get_attributes", {"entity_id": "light.bulb"}) == {"light.bulb": {"brightness": 40.2}}
    assert clusters_read(requests) == [zcl.ON_OFF_CLUSTER, zcl.LEVEL_CLUSTER]


@pytest.mark.parametrize(
    ("color", "expected"),
    [
        ({zcl.COLOR_MODE: 2, zcl.COLOR_TEMPERATURE: 370}, {"color_temp_kelvin": 2702}),
        # EnhancedColorMode wins over ColorMode.
        ({zcl.COLOR_MODE: 0, zcl.ENHANCED_COLOR_MODE: 2, zcl.COLOR_TEMPERATURE: 250}, {"color_temp_kelvin": 4000}),
        ({zcl.COLOR_MODE: 1, zcl.CURRENT_X: 45875, zcl.CURRENT_Y: 19661}, xy_row(0.7, 0.3)),
        ({zcl.COLOR_MODE: 0, zcl.CURRENT_HUE: 127, zcl.CURRENT_SATURATION: 254}, hs_row(180.0, 100.0)),
        (
            {
                zcl.COLOR_MODE: 0,
                zcl.ENHANCED_COLOR_MODE: 3,
                zcl.ENHANCED_CURRENT_HUE: 0x4000,
                zcl.CURRENT_SATURATION: 127,
            },
            hs_row(90.001, 50.0),
        ),
        # A mode whose values the light didn't return reports no color.
        ({zcl.COLOR_MODE: 1}, {}),
        ({zcl.COLOR_MODE: 0, zcl.CURRENT_HUE: 127}, {}),
        ({zcl.COLOR_MODE: 2, zcl.COLOR_TEMPERATURE: 0}, {}),
        ({zcl.COLOR_MODE: 7}, {}),
    ],
)
async def test_color_light_reports_its_active_mode(hass, bulb, requests, color, expected):
    add_zha_entity(hass, zha_entry(hass), "light.bulb", attributes=COLOR)
    bulb[zcl.LEVEL_CLUSTER] = {zcl.CURRENT_LEVEL: 254}
    bulb[zcl.COLOR_CLUSTER] = color

    response = await call(hass, "get_attributes", {"entity_id": "light.bulb"})

    assert response == {"light.bulb": {"brightness": 100.0, **expected}}
    assert clusters_read(requests) == [zcl.ON_OFF_CLUSTER, zcl.LEVEL_CLUSTER, zcl.COLOR_CLUSTER]


@pytest.mark.parametrize(
    ("on_off", "expected"),
    [
        ({zcl.ON_OFF: 1, zcl.ON_TIME: 48}, {"timer": timer(4.8)}),
        # A TS011F counts OnTime down while off: no timer.
        ({zcl.ON_OFF: 0, zcl.ON_TIME: 48}, {}),
        ({zcl.ON_OFF: 1, zcl.ON_TIME: 0}, {}),
        ({zcl.ON_OFF: 1}, {}),
    ],
)
async def test_timer_from_on_time_while_on(hass, bulb, on_off, expected):
    add_zha_entity(hass, zha_entry(hass), "light.bulb", state="on", attributes=ONOFF)
    bulb[zcl.ON_OFF_CLUSTER] = on_off

    assert await call(hass, "get_attributes", {"entity_id": "light.bulb"}) == {"light.bulb": expected}


async def test_light_without_an_address_is_refused(hass, bulb, requests):
    add_zha_entity(hass, zha_entry(hass), "light.bulb", unique_id=f"{IEEE}-1-6")

    assert await refusal(hass, "get_attributes", {"entity_id": "light.bulb"}) == "not_addressable"
    assert not requests


async def test_read_error_raises(hass, bulb):
    add_zha_entity(hass, zha_entry(hass), "light.bulb", attributes=DIMMABLE)  # no Level cluster to read

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "get_attributes", {"entity_id": "light.bulb"})

    assert raised.value.translation_key == "targets_failed"
    assert raised.value.translation_placeholders == {"summary": "light.bulb: error"}


async def test_group_reads_each_member(hass, bulb, requests, zha_groups):
    a, b = "00:00:00:00:00:00:00:0a", "00:00:00:00:00:00:00:0b"
    entry = zha_entry(hass)
    add_zha_entity(hass, entry, "light.zha_group", unique_id="light_zha_group_0x0002", attributes=DIMMABLE)
    add_zha_entity(hass, entry, "light.a", ieee=a, attributes=DIMMABLE)
    add_zha_entity(hass, entry, "light.b", ieee=b, attributes=DIMMABLE)
    zha_groups[2] = zha_group((a, 11), (b, 11))
    bulb[zcl.LEVEL_CLUSTER] = {zcl.CURRENT_LEVEL: 127}

    response = await call(hass, "get_attributes", {"entity_id": "light.zha_group"})

    assert response == {"light.a": {"brightness": 50.0}, "light.b": {"brightness": 50.0}}
    assert sorted({ieee for ieee, _ in requests}) == [a, b]
