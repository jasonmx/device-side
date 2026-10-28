"""Parse a ZHA entity's Zigbee address from its unique_id."""

from typing import NamedTuple

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from ...core.models import Target

# ZHA group entities are "{platform}_zha_group_0x{group_id:04x}" (zha library, GroupEntity).
_GROUP_MARKER = "_zha_group_0x"


class Address(NamedTuple):
    ieee: str
    endpoint_id: int


def address(unique_id: str) -> Address | None:
    """The IEEE and endpoint of a ZHA light, or None.

    The zha library gives a light the unique_id "{ieee}-{endpoint_id}" (platforms/light, Light.__init__); the IEEE
    is colon-separated, so it holds no hyphen. Anything longer is another entity on the endpoint (a quirk's
    suffixed entity, or a cluster-keyed one) and is refused rather than guessed at.
    """
    parts = unique_id.split("-")
    if len(parts) != 2:
        return None
    ieee, endpoint = parts
    try:
        return Address(ieee, int(endpoint))
    except ValueError:
        return None


def group_id(unique_id: str) -> int | None:
    """The Zigbee group ID of a ZHA group entity, or None for any other entity."""
    _, marker, hex_id = unique_id.partition(_GROUP_MARKER)
    try:
        return int(hex_id, 16) if marker else None
    except ValueError:
        return None


def via_zha_group(hass: HomeAssistant, target: Target) -> int | None:
    """The Zigbee group ID of the ZHA group the target was expanded from, or None."""
    if target.via_group is None or (entry := er.async_get(hass).async_get(target.via_group)) is None:
        return None
    return group_id(entry.unique_id) if entry.platform == "zha" else None


def unsupported_reason(target: Target) -> str | None:
    """Why this entity can't be addressed, or None."""
    return "not_addressable" if address(target.entry.unique_id) is None else None


def is_zha_group(hass: HomeAssistant, target: Target) -> bool:
    return _GROUP_MARKER in target.entry.unique_id
