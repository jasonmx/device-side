from collections.abc import Iterable
from dataclasses import replace

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, split_entity_id
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .models import Target
from .registry import AdapterRegistry

SWITCH_AS_X = "switch_as_x"


def resolve(
    hass: HomeAssistant, registry: AdapterRegistry, entity_id: str, via_group: str | None = None
) -> Target | str:
    """The Target for an entity, or the reason key it cannot be served.

    Integrations with a detect hook are tried first, so Z2M takes its MQTT entities before a generic MQTT integration.
    A switch_as_x wrapper resolves to the switch it wraps: it forwards on/off unchanged, so the switch's call is the
    one that reaches the device.
    """
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None:
        return "not_in_registry"
    if entry.platform == SWITCH_AS_X:
        return _resolve_wrapper(hass, registry, entry, via_group)
    candidates = [info for info in registry.available_integrations() if info.ha_domain == entry.platform]
    if not candidates:
        return "integration_not_supported"
    config_entry = hass.config_entries.async_get_entry(entry.config_entry_id) if entry.config_entry_id else None
    if config_entry is None or config_entry.state is not ConfigEntryState.LOADED:
        return "integration_not_loaded"
    device = dr.async_get(hass).async_get(entry.device_id) if entry.device_id else None

    detected = [info for info in candidates if info.detect is not None and info.detect(hass, entry, device)]
    generic = [info for info in candidates if info.detect is None]
    if not (chosen := (detected or generic)):
        return "integration_not_supported"
    integration = chosen[0]

    target = Target(
        entity_id=entity_id,
        domain=split_entity_id(entity_id)[0],
        integration=integration.key,
        entry=entry,
        device=device,
        config_entry=config_entry,
        state=hass.states.get(entity_id),
        via_group=via_group,
    )
    if integration.is_group is not None and integration.is_group(hass, target):
        target = replace(target, is_group=True)
    return target


def resolve_members(
    hass: HomeAssistant, registry: AdapterRegistry, group: Target, platform: str, unique_ids: Iterable[str]
) -> list[Target]:
    """A native group's members, for an integration's expand_group: each unique_id's entity in the group's domain
    on `platform`, resolved with the group as via_group, sorted by entity_id.

    A member with no entity in that domain, or one resolve refuses, is left out.
    """
    entities = er.async_get(hass)
    members = []
    for unique_id in unique_ids:
        entity_id = entities.async_get_entity_id(group.domain, platform, unique_id)
        if entity_id is not None and not isinstance(member := resolve(hass, registry, entity_id, group.entity_id), str):
            members.append(member)
    return sorted(members, key=lambda member: member.entity_id)


def _resolve_wrapper(
    hass: HomeAssistant, registry: AdapterRegistry, entry: er.RegistryEntry, via_group: str | None
) -> Target | str:
    options = entry.options.get(SWITCH_AS_X) or {}
    if options.get("invert"):
        return "inverted_wrapper"
    wrapped = er.async_get(hass).async_get(options["entity_id"]) if options.get("entity_id") else None
    if wrapped is None:
        return "not_in_registry"
    if wrapped.platform == SWITCH_AS_X:
        return "not_addressable"
    target = resolve(hass, registry, wrapped.entity_id, via_group)
    return target if isinstance(target, str) else replace(target, via_wrapper=entry.entity_id)
