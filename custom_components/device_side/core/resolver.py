from dataclasses import replace

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, split_entity_id
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .models import Target
from .registry import CellRegistry


def resolve(hass: HomeAssistant, registry: CellRegistry, entity_id: str, via_group: str | None = None) -> Target | str:
    """The Target for an entity, or the reason key it cannot be served.

    Platforms with a detect hook are tried first, so Z2M claims its MQTT entities before a generic MQTT platform.
    """
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None:
        return "not_in_registry"
    candidates = [info for info in registry.available_platforms() if info.ha_integration == entry.platform]
    if not candidates:
        return "no_platform"
    config_entry = hass.config_entries.async_get_entry(entry.config_entry_id) if entry.config_entry_id else None
    if config_entry is None or config_entry.state is not ConfigEntryState.LOADED:
        return "integration_not_loaded"
    device = dr.async_get(hass).async_get(entry.device_id) if entry.device_id else None

    detected = [info for info in candidates if info.detect is not None and info.detect(hass, entry, device)]
    generic = [info for info in candidates if info.detect is None]
    if not (chosen := (detected or generic)):
        return "no_platform"
    platform = chosen[0]

    target = Target(
        entity_id=entity_id,
        domain=split_entity_id(entity_id)[0],
        platform=platform.key,
        entry=entry,
        device=device,
        config_entry=config_entry,
        state=hass.states.get(entity_id),
        via_group=via_group,
    )
    if platform.is_group is not None and platform.is_group(hass, target):
        target = replace(target, is_group=True)
    return target
