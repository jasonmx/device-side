"""Read ZCL attributes from a ZHA device through the zha integration's gateway."""

from typing import Any

from homeassistant.core import HomeAssistant

from .addressing import Address

ON_OFF_CLUSTER = 0x0006
ON_OFF = 0x0000
ON_TIME = 0x4001


async def read_attributes(
    hass: HomeAssistant, addr: Address, cluster_id: int, attributes: tuple[int, ...]
) -> dict[int, Any]:
    """Read attributes off the device in one request, bypassing zigpy's cache, as
    websocket_read_zigbee_cluster_attributes does.

    That websocket command is the only public route, and it is admin-only; this reaches the same gateway through
    zha's internals. Callers read only after an admin-checked command succeeded, so the read grants no extra rights.
    Raises when the device is unknown or any attribute comes back in the failure dict, so callers handle one
    failure path. The zha library is installed only where ZHA runs, hence the imports here.
    """
    from homeassistant.components.zha.helpers import get_zha_gateway
    from zigpy.types import EUI64

    device = get_zha_gateway(hass).get_device(EUI64.convert(addr.ieee))
    if device is None:
        raise LookupError(f"ZHA device {addr.ieee} not found")
    cluster = device.async_get_cluster(addr.endpoint_id, cluster_id, cluster_type="in")
    success, failure = await cluster.read_attributes(list(attributes), allow_cache=False, only_cache=False)
    for attribute in attributes:
        if attribute not in success:
            raise LookupError(f"Attribute 0x{attribute:04x} not read: {failure.get(attribute)}")
    return {attribute: success[attribute] for attribute in attributes}
