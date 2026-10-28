"""Send ZCL commands to a ZHA device through the zha integration's cluster command action, and read its attributes
through the zha integration's gateway."""

from typing import Any

from homeassistant.core import Context, HomeAssistant

from .addressing import Address

ON_OFF_CLUSTER = 0x0006
ON_OFF = 0x0000
ON_TIME = 0x4001

LEVEL_CLUSTER = 0x0008
CURRENT_LEVEL = 0x0000
MOVE_TO_LEVEL = 0x00
STOP = 0x03
MOVE_TO_LEVEL_WITH_ON_OFF = 0x04

COLOR_CLUSTER = 0x0300
CURRENT_HUE = 0x0000
CURRENT_SATURATION = 0x0001
CURRENT_X = 0x0003
CURRENT_Y = 0x0004
COLOR_TEMPERATURE = 0x0007
COLOR_MODE = 0x0008
ENHANCED_CURRENT_HUE = 0x4000
ENHANCED_COLOR_MODE = 0x4001
COLOR_CAPABILITIES = 0x400A
ENHANCED_HUE = 0x02  # ColorCapabilities bit 1
MOVE_TO_HUE_AND_SATURATION = 0x06
MOVE_TO_COLOR = 0x07
MOVE_TO_COLOR_TEMP = 0x0A
ENHANCED_MOVE_HUE = 0x41
STOP_MOVE_STEP = 0x47

# Models that don't store a MoveToLevel while off: the Sengled E11-G13 jumps CurrentLevel to 255 with or without the
# override and comes on at full (docs/integrations.md, ZHA tested behavior).
DROPS_WHILE_OFF = frozenset({"E11-G13"})


def level(percent: float) -> int:
    """CurrentLevel for a brightness percent; 0 is the lowest level, 1, as Hue sets its lowest."""
    return max(1, round(percent * 254 / 100))


def execute_if_off(transition_tenths: int) -> dict[str, int]:
    """A MoveTo command's transition and the ExecuteIfOff override, which makes a light that is off store the value
    and stay off. It applies to this command only; the light's Options attribute stays untouched."""
    return {"transition_time": transition_tenths, "options_mask": 1, "options_override": 1}


async def command(
    hass: HomeAssistant,
    addr: Address,
    cluster_id: int,
    command_id: int,
    params: dict[str, Any],
    context: Context | None,
) -> None:
    """Send a server command to the device's in cluster through zha.issue_zigbee_cluster_command; params by zigpy name.

    The action is admin-only, so it carries the caller's context: a non-admin caller gets Unauthorized from ZHA rather
    than Device Side's own rights. The zha library raises on a delivery failure or a non-success ZCL status, so a call
    that returns was accepted.
    """
    await hass.services.async_call(
        "zha",
        "issue_zigbee_cluster_command",
        {
            "ieee": addr.ieee,
            "endpoint_id": addr.endpoint_id,
            "cluster_id": cluster_id,
            "cluster_type": "in",
            "command": command_id,
            "command_type": "server",
            "params": params,
        },
        blocking=True,
        context=context,
    )


async def group_command(
    hass: HomeAssistant, gid: int, cluster_id: int, command_id: int, args: list[Any], context: Context | None
) -> None:
    """Groupcast a server command to a Zigbee group through zha.issue_zigbee_group_command; args are positional.

    Admin-only, like command(), so it carries the caller's context. A groupcast returns at once with no delivery
    feedback: a member that can't run the command drops it silently.
    """
    await hass.services.async_call(
        "zha",
        "issue_zigbee_group_command",
        {"group": gid, "cluster_id": cluster_id, "command": command_id, "args": args},
        blocking=True,
        context=context,
    )


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
    zha's internals. Callers read only OnOff, Level and Color values, which HA already shows any user in the light's
    state, so the read grants no extra rights.
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
