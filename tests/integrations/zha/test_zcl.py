"""zcl.read_attributes against a fake zha gateway, since the zha library isn't a dev dependency."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.device_side.integrations.zha import zcl
from custom_components.device_side.integrations.zha.addressing import Address

from ...fixtures.zha import IEEE

ADDR = Address(IEEE, 11)


@pytest.fixture
def cluster():
    return SimpleNamespace(read_attributes=AsyncMock(return_value=({zcl.ON_OFF: True, zcl.ON_TIME: 48}, {})))


@pytest.fixture
def gateway(monkeypatch, cluster):
    """Fake helpers.get_zha_gateway and zigpy.types.EUI64; EUI64.convert passes the IEEE through."""
    device = MagicMock()
    device.async_get_cluster.return_value = cluster
    gw = MagicMock()
    gw.get_device.return_value = device
    helpers = SimpleNamespace(get_zha_gateway=lambda hass: gw)
    types = SimpleNamespace(EUI64=SimpleNamespace(convert=lambda ieee: ieee))
    monkeypatch.setitem(sys.modules, "homeassistant.components.zha.helpers", helpers)
    monkeypatch.setitem(sys.modules, "zigpy.types", types)
    return gw


async def test_reads_the_values_uncached_in_one_request(hass, gateway, cluster):
    read = await zcl.read_attributes(hass, ADDR, zcl.ON_OFF_CLUSTER, (zcl.ON_OFF, zcl.ON_TIME))

    assert read == {zcl.ON_OFF: True, zcl.ON_TIME: 48}

    gateway.get_device.assert_called_once_with(IEEE)
    gateway.get_device.return_value.async_get_cluster.assert_called_once_with(11, 0x0006, cluster_type="in")
    cluster.read_attributes.assert_awaited_once_with([0x0000, 0x4001], allow_cache=False, only_cache=False)


async def test_failed_attribute_raises(hass, gateway, cluster):
    cluster.read_attributes.return_value = ({zcl.ON_OFF: True}, {zcl.ON_TIME: "UNSUPPORTED_ATTRIBUTE"})

    with pytest.raises(LookupError, match="0x4001 not read: UNSUPPORTED_ATTRIBUTE"):
        await zcl.read_attributes(hass, ADDR, zcl.ON_OFF_CLUSTER, (zcl.ON_OFF, zcl.ON_TIME))


async def test_missing_device_raises(hass, gateway):
    gateway.get_device.return_value = None

    with pytest.raises(LookupError, match="not found"):
        await zcl.read_attributes(hass, ADDR, zcl.ON_OFF_CLUSTER, (zcl.ON_TIME,))


async def test_without_zha_installed_raises_import_error(hass, monkeypatch):
    monkeypatch.setitem(sys.modules, "homeassistant.components.zha.helpers", None)

    with pytest.raises(ImportError):
        await zcl.read_attributes(hass, ADDR, zcl.ON_OFF_CLUSTER, (zcl.ON_TIME,))
