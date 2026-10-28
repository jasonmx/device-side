"""A ZHA group's members, for the dispatcher to expand a group entity into."""

from homeassistant.core import HomeAssistant

from . import zcl
from .addressing import group_id
from ...core.models import Target
from ...core.resolver import resolve_members
from ...core.runtime import get_runtime


def expand_group(hass: HomeAssistant, target: Target) -> list[Target]:
    """The group's members that have an entity in the group entity's domain, sorted by entity_id.

    A ZHA group has one entity per domain among its members (a light group, a switch group), so a light group
    expands to its lights only. A member's entity is found by the unique_id the zha library gives it,
    "{ieee}-{endpoint_id}". A group ZHA no longer knows expands to nothing, which the dispatcher skips as an
    empty group: issue_zigbee_group_command would accept the call and send nothing.
    """
    if (gid := group_id(target.entry.unique_id)) is None or (group := zcl.gateway(hass).get_group(gid)) is None:
        return []
    unique_ids = (f"{member.device.ieee}-{member.endpoint_id}" for member in group.members)
    return resolve_members(hass, get_runtime(hass).registry, target, "zha", unique_ids)
