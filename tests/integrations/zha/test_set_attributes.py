"""ZHA set_attributes: MoveTo commands with the ExecuteIfOff override, one light at a time, then update_entity."""

from unittest.mock import AsyncMock

import probatio
import pytest
from homeassistant.core import Context, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.util.color import color_hs_to_xy, color_RGB_to_xy, color_temperature_to_hs, color_xy_to_hs
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.device_side.const import DOMAIN
from custom_components.device_side.integrations.zha import zcl

from ...conftest import call, refusal
from ...fixtures.zha import IEEE, add_zha_entity, zha_entry, zha_group

pytestmark = pytest.mark.usefixtures("setup_production")

SENT = {"status": "sent", "integration": "zha"}
OVERRIDE = {"transition_time": 4, "options_mask": 1, "options_override": 1}
ONOFF = {"supported_color_modes": ["onoff"]}
DIMMABLE = {"supported_color_modes": ["brightness"]}
CT = {"supported_color_modes": ["color_temp"], "min_color_temp_kelvin": 2202, "max_color_temp_kelvin": 6535}
COLOR = {**CT, "supported_color_modes": ["color_temp", "xy"]}
HS = {"supported_color_modes": ["hs"]}


@pytest.fixture(autouse=True)
def level_read(monkeypatch):
    """zcl.read_attributes, reading CurrentLevel 127 (50 %) unless a test sets its own."""
    read = AsyncMock(return_value={zcl.CURRENT_LEVEL: 127})
    monkeypatch.setattr(zcl, "read_attributes", read)
    return read


@pytest.fixture
def commands(hass):
    return async_mock_service(hass, "zha", "issue_zigbee_cluster_command")


@pytest.fixture
def refreshes(hass):
    return async_mock_service(hass, "homeassistant", "update_entity")


def sent(commands) -> list[tuple[int, int, dict]]:
    """Each command as (cluster, command, params), after checking it went to the bulb's in cluster as a server one."""
    for command in commands:
        assert {k: command.data[k] for k in ("ieee", "endpoint_id", "cluster_type", "command_type")} == {
            "ieee": IEEE, "endpoint_id": 11, "cluster_type": "in", "command_type": "server"
        }
    return [(command.data["cluster_id"], command.data["command"], command.data["params"]) for command in commands]


def level(value: int) -> tuple[int, int, dict]:
    return 0x0008, 0x00, {"level": value, **OVERRIDE}


def mireds(value: int) -> tuple[int, int, dict]:
    return 0x0300, 0x0A, {"color_temp_mireds": value, **OVERRIDE}


def xy(x: float, y: float) -> tuple[int, int, dict]:
    return 0x0300, 0x07, {"color_x": round(x * 65535), "color_y": round(y * 65535), **OVERRIDE}


def bulb(hass, attributes: dict, entity_id: str = "light.bulb") -> str:
    return add_zha_entity(hass, zha_entry(hass), entity_id, attributes=attributes)


@pytest.mark.parametrize(
    ("data", "attributes", "expected"),
    [
        pytest.param({"brightness": 40}, DIMMABLE, [level(102)], id="brightness"),
        pytest.param({"brightness": 0}, DIMMABLE, [level(1)], id="brightness_0_is_the_lowest_level"),
        pytest.param({"brightness": 100}, DIMMABLE, [level(254)], id="brightness_100"),
        pytest.param({"color_temp_kelvin": 2700}, CT, [mireds(370)], id="ct"),
        pytest.param({"color_temp_kelvin": 1000}, CT, [mireds(454)], id="ct_clamped_warm"),
        pytest.param({"color_temp_kelvin": 9000}, CT, [mireds(153)], id="ct_clamped_cool"),
        pytest.param(
            {"color_temp_kelvin": 9000}, {"supported_color_modes": ["color_temp"]}, [mireds(111)], id="ct_no_range"
        ),
        pytest.param(
            {"brightness": 40, "color_temp_kelvin": 2700}, CT, [level(102), mireds(370)], id="brightness_and_ct"
        ),
        pytest.param({"xy_color": [0.369, 0.445]}, COLOR, [xy(0.369, 0.445)], id="xy"),
        pytest.param({"hs_color": [30, 80]}, COLOR, [xy(*color_hs_to_xy(30, 80))], id="hs_on_xy_bulb"),
        pytest.param({"rgb_color": [255, 128, 0]}, COLOR, [xy(*color_RGB_to_xy(255, 128, 0))], id="rgb_on_xy_bulb"),
        pytest.param(
            {"xy_color": [0.369, 0.445], "color_temp_kelvin": 2700}, COLOR, [xy(0.369, 0.445)], id="color_wins_over_ct"
        ),
        pytest.param(
            {"color_temp_kelvin": 2700},
            {"supported_color_modes": ["xy"]},
            [xy(*color_hs_to_xy(*color_temperature_to_hs(2700)))],
            id="ct_as_a_color_without_ct_mode",
        ),
    ],
)
async def test_writes_with_the_override(hass, commands, refreshes, data, attributes, expected):
    bulb(hass, attributes)

    assert await call(hass, "set_attributes", {"entity_id": "light.bulb", **data}) == {"light.bulb": SENT}
    assert sent(commands) == expected
    assert [refresh.data for refresh in refreshes] == [{"entity_id": "light.bulb"}]


async def test_color_on_an_hs_only_bulb_sends_hue_and_saturation(hass, commands, refreshes):
    bulb(hass, HS)

    await call(hass, "set_attributes", {"entity_id": "light.bulb", "xy_color": [0.369, 0.445]})

    hue, saturation = color_xy_to_hs(0.369, 0.445)
    assert sent(commands) == [
        (0x0300, 0x06, {"hue": round(hue * 254 / 360), "saturation": round(saturation * 254 / 100), **OVERRIDE})
    ]


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        pytest.param({"min_brightness": 60}, [level(152)], id="min_raises"),
        pytest.param({"max_brightness": 30}, [level(76)], id="max_lowers"),
        pytest.param({"min_brightness": 20, "brightness": 10}, [level(25)], id="brightness_wins"),
    ],
)
async def test_limits_clamp_the_current_level(hass, commands, refreshes, level_read, data, expected):
    bulb(hass, DIMMABLE)

    assert await call(hass, "set_attributes", {"entity_id": "light.bulb", **data}) == {"light.bulb": SENT}
    assert sent(commands) == expected
    if "brightness" in data:
        level_read.assert_not_awaited()
    else:
        level_read.assert_awaited_once_with(hass, (IEEE, 11), 0x0008, (0x0000,))


async def test_within_limits_sends_nothing(hass, commands, refreshes):
    bulb(hass, DIMMABLE)

    data = {"entity_id": "light.bulb", "min_brightness": 20, "max_brightness": 80}
    response = await call(hass, "set_attributes", data)

    assert response == {"light.bulb": {"status": "unchanged", "integration": "zha", "detail": "within_limits"}}
    assert not commands
    assert not refreshes


async def test_a_field_the_light_cant_take_is_dropped(hass, commands, refreshes):
    bulb(hass, CT)

    response = await call(hass, "set_attributes", {"entity_id": "light.bulb", "brightness": 40, "hs_color": [30, 80]})

    assert response == {"light.bulb": {**SENT, "detail": "fields_dropped"}}
    assert sent(commands) == [level(102)]


@pytest.mark.parametrize(
    ("attributes", "data"),
    [
        pytest.param(ONOFF, {"brightness": 40, "color_temp_kelvin": 2700}, id="onoff_light"),
        pytest.param(ONOFF, {"min_brightness": 40}, id="onoff_light_limits"),
        pytest.param(DIMMABLE, {"rgb_color": [255, 0, 0], "color_temp_kelvin": 2700}, id="every_field_dropped"),
        pytest.param({}, {"brightness": 40, "rgb_color": [255, 0, 0], "color_temp_kelvin": 2700}, id="no_color_modes"),
    ],
)
async def test_a_light_that_takes_no_field_is_unchanged(hass, commands, refreshes, level_read, attributes, data):
    bulb(hass, attributes)

    response = await call(hass, "set_attributes", {"entity_id": "light.bulb", **data})

    assert response == {"light.bulb": {"status": "unchanged", "integration": "zha", "detail": "fields_dropped"}}
    assert not commands
    level_read.assert_not_awaited()


async def test_a_failed_refresh_still_reports_sent(hass, commands):
    bulb(hass, DIMMABLE)

    async def handler(service: ServiceCall) -> None:
        raise ValueError("entity gone")

    hass.services.async_register("homeassistant", "update_entity", handler)

    assert await call(hass, "set_attributes", {"entity_id": "light.bulb", "brightness": 40}) == {"light.bulb": SENT}


async def test_a_command_error_rejects_that_light(hass, refreshes):
    entry = zha_entry(hass)
    add_zha_entity(hass, entry, "light.gone", ieee="00:00:00:00:00:00:00:01", attributes=DIMMABLE)
    add_zha_entity(hass, entry, "light.bulb", attributes=DIMMABLE)

    # A plain handler, since a mock service can't raise.
    async def handler(service: ServiceCall) -> None:
        if service.data["ieee"] != IEEE:
            raise ValueError(f"Device with IEEE {service.data['ieee']} not found")

    hass.services.async_register("zha", "issue_zigbee_cluster_command", handler)

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "set_attributes", {"entity_id": ["light.bulb", "light.gone"], "brightness": 40})

    assert raised.value.translation_key == "targets_failed"
    assert raised.value.translation_placeholders["summary"] == "light.gone: error"
    assert sorted(refresh.data["entity_id"] for refresh in refreshes) == ["light.bulb", "light.gone"]


async def test_a_failed_level_read_rejects_that_light(hass, commands, level_read):
    bulb(hass, DIMMABLE)
    level_read.side_effect = LookupError("Attribute 0x0000 not read")

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "set_attributes", {"entity_id": "light.bulb", "min_brightness": 60})

    assert raised.value.translation_placeholders["summary"] == "light.bulb: error"
    assert not commands


async def test_non_admin_caller_is_refused_by_zha(hass, refreshes, hass_read_only_user):
    bulb(hass, DIMMABLE)
    calls: list[ServiceCall] = []

    async def handler(service: ServiceCall) -> None:
        calls.append(service)

    schema = probatio.Schema({}, extra=probatio.ALLOW_EXTRA)
    async_register_admin_service(hass, "zha", "issue_zigbee_cluster_command", handler, schema)

    with pytest.raises(HomeAssistantError) as raised:
        await hass.services.async_call(
            DOMAIN,
            "set_attributes",
            {"entity_id": "light.bulb", "brightness": 40},
            blocking=True,
            return_response=True,
            context=Context(user_id=hass_read_only_user.id),
        )

    assert raised.value.translation_placeholders["summary"] == "light.bulb: admin_required"
    assert not calls


async def test_entity_without_a_light_unique_id_is_not_addressable(hass, commands):
    add_zha_entity(hass, zha_entry(hass), "light.quirk", unique_id=f"{IEEE}-1-6-child_lock", attributes=DIMMABLE)

    assert await refusal(hass, "set_attributes", {"entity_id": "light.quirk", "brightness": 40}) == "not_addressable"


async def test_a_model_that_drops_writes_while_off_is_refused(hass, commands):
    bulb(hass, DIMMABLE)
    device_id = er.async_get(hass).async_get("light.bulb").device_id
    dr.async_get(hass).async_update_device(device_id, model="E11-G13")

    data = {"entity_id": "light.bulb", "brightness": 40}
    assert await refusal(hass, "set_attributes", data) == "execute_if_off_unsupported"
    assert not commands


A, B = "00:00:00:00:00:00:00:0a", "00:00:00:00:00:00:00:0b"


async def test_a_zha_group_writes_each_member(hass, zha_groups, commands, refreshes):
    entry = zha_entry(hass)
    add_zha_entity(hass, entry, "light.zha_group", unique_id="light_zha_group_0x0002", attributes=DIMMABLE)
    add_zha_entity(hass, entry, "light.a", ieee=A, attributes=DIMMABLE)
    add_zha_entity(hass, entry, "light.b", ieee=B, attributes=DIMMABLE)
    zha_groups[2] = zha_group((A, 11), (B, 11))

    response = await call(hass, "set_attributes", {"entity_id": "light.zha_group", "brightness": 40})

    assert response == {"light.a": SENT, "light.b": SENT}
    assert sorted(command.data["ieee"] for command in commands) == [A, B]
    assert sorted(refresh.data["entity_id"] for refresh in refreshes) == ["light.a", "light.b"]
