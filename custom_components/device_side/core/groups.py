from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.group import get_entity_ids

MAX_DEPTH = 4


def _is_ha_group(hass: HomeAssistant, entity_id: str) -> bool:
    # Legacy group.* entities are not in the entity registry; group helpers (light, switch, ...) are, on platform
    # "group". Core's own expansion only handles the former (helpers/group.py:expand_entity_ids), so we do both.
    if entity_id.startswith("group."):
        return True
    entry = er.async_get(hass).async_get(entity_id)
    return entry is not None and entry.platform == "group"


def expand_ha_groups(hass: HomeAssistant, entity_ids: list[str]) -> tuple[dict[str, str | None], list[str]]:
    """Replace HA group-platform entities with their members, any domain, recursively.

    Returns (member entity_id -> the group that directly contained it, or None), in first-seen order and deduped,
    plus the groups that expanded to nothing. Integration-native groups are not touched: they are not on the group
    platform, and a device can address them.
    """
    members: dict[str, str | None] = {}
    empty: list[str] = []

    def _walk(entity_id: str, via_group: str | None, depth: int) -> None:
        if depth < MAX_DEPTH and _is_ha_group(hass, entity_id):
            children = [child for child in get_entity_ids(hass, entity_id) if child != entity_id]
            if not children:
                empty.append(entity_id)
            for child in children:
                _walk(child, entity_id, depth + 1)
        elif entity_id not in members:
            members[entity_id] = via_group

    for entity_id in entity_ids:
        _walk(entity_id, None, 0)
    return members, empty
