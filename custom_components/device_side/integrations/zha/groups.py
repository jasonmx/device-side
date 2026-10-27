"""A ZHA group's members, for the dispatcher to expand a group entity into."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import zcl
from .addressing import group_id
from ...core.models import Target
from ...core.resolver import resolve
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
    entities = er.async_get(hass)
    registry = get_runtime(hass).registry
    members = []
    for member in group.members:
        unique_id = f"{member.device.ieee}-{member.endpoint_id}"
        entity_id = entities.async_get_entity_id(target.domain, "zha", unique_id)
        if entity_id is not None and not isinstance(
            resolved := resolve(hass, registry, entity_id, target.entity_id), str
        ):
            members.append(resolved)
    return sorted(members, key=lambda member: member.entity_id)
