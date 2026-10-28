"""Read ZCL attributes from a ZHA device through the zha integration's gateway."""

from typing import Any

from homeassistant.core import HomeAssistant

from .addressing import Address

ON_OFF_CLUSTER = 0x0006
ON_OFF = 0x0000
ON_TIME = 0x4001


def gateway(hass: HomeAssistant) -> Any:
    """The zha library's gateway, read from hass.data as zha's get_zha_gateway does; raises ValueError without one.

    Not imported from homeassistant.components.zha: hassfest would then require zha in after_dependencies, and HA
    holds an integration's setup until its after_dependencies' entries finish setting up, so a ZHA stuck in setup
    would take device_side's actions down for every integration.
    """
    if (data := hass.data.get("zha")) is None or (proxy := data.gateway_proxy) is None:
        raise ValueError("No ZHA gateway")
    return proxy.gateway


async def read_attributes(
    hass: HomeAssistant, addr: Address, cluster_id: int, attributes: tuple[int, ...], optional: tuple[int, ...] = ()
) -> dict[int, Any]:
    """Read attributes off the device in one request, bypassing zigpy's cache, as
    websocket_read_zigbee_cluster_attributes does.

    That websocket command is the only public route, and it is admin-only; this reaches the same gateway through
    zha's internals. Callers read only after an admin-checked command succeeded, so the read grants no extra rights.
    Raises when the device is unknown or any of `attributes` comes back in the failure dict, so callers handle one
    failure path. `optional` ones ride the same request and are left out of the result when the device lacks them.
    The zha library is installed only where ZHA runs, hence the imports here.
    """
    from zigpy.types import EUI64

    device = gateway(hass).get_device(EUI64.convert(addr.ieee))
    if device is None:
        raise LookupError(f"ZHA device {addr.ieee} not found")
    cluster = device.async_get_cluster(addr.endpoint_id, cluster_id, cluster_type="in")
    wanted = [*attributes, *optional]
    success, failure = await cluster.read_attributes(wanted, allow_cache=False, only_cache=False)
    for attribute in attributes:
        if attribute not in success:
            raise LookupError(f"Attribute 0x{attribute:04x} not read: {failure.get(attribute)}")
    return {attribute: success[attribute] for attribute in wanted if attribute in success}
