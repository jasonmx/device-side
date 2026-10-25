"""Parse a Matter entity's node address from its unique_id, and check OnOff cluster features.

No imports from homeassistant.components.matter or chip.clusters at module level: those packages
require matter_server and chip to be installed, but the adapter must import cleanly in test
environments where only the core homeassistant package is present.  All matter-specific operations
are accessed either through hass.config_entries or via deferred imports confined to a single
helper function (make_on_with_timed_off).
"""

from homeassistant.core import HomeAssistant

_MATTER_DOMAIN = "matter"

# OnOff cluster constants (Matter spec, cluster 0x0006)
_ONOFF_CLUSTER_ID = 6
_FEATUREMAP_ATTR_ID = 65532  # 0xFFFC
_LT_FEATURE_BIT = 0x0002  # Lighting (LT) feature per Matter spec sec. 1.5.4.2
_ONTIME_ATTR_ID = 16385  # 0x4001 — counts down to 0 while the timed-on is running


class _OnOffFeatureMapAttr:
    """Minimal attribute descriptor for OnOff.FeatureMap.

    Duck-types the chip.clusters attribute class interface (cluster_id + attribute_id) so
    endpoint.get_attribute_value() can look up the cached value without chip being importable.
    """

    cluster_id = _ONOFF_CLUSTER_ID
    attribute_id = _FEATUREMAP_ATTR_ID


_ONOFF_FEATUREMAP = _OnOffFeatureMapAttr()


def node_id_from_unique_id(unique_id: str) -> int | None:
    """Parse the Matter node_id (int) from an entity unique_id.

    Matter unique_ids are constructed in homeassistant/components/matter/entity.py as:
        {node_device_id}-{endpoint_id}-{key}-{cluster_id}-{attr_id}
    where node_device_id = {fab_hex16}-{node_hex16}-{postfix}.

    fab_hex16 and node_hex16 are exactly 16 hex chars with no hyphens, so parts[0] is always
    fab_hex16 and parts[1] is always node_hex16 regardless of the postfix value.
    """
    parts = unique_id.split("-")
    if len(parts) < 7:
        return None
    try:
        return int(parts[1], 16)
    except ValueError:
        return None


def endpoint_id_from_unique_id(unique_id: str) -> int | None:
    """Parse the Matter endpoint_id (int) from an entity unique_id.

    The key, cluster_id and attr_id occupy the last three positions, so endpoint_id is parts[-4].
    """
    parts = unique_id.split("-")
    if len(parts) < 7:
        return None
    try:
        return int(parts[-4])
    except ValueError:
        return None


def matter_client(hass: HomeAssistant, config_entry_id: str | None = None):
    """Return the MatterClient for a given config entry, or None.

    When config_entry_id is supplied, the client for that specific entry is returned.
    When omitted, the first loaded Matter entry is used (production: there is only one).

    Reads hass.config_entries directly to stay independent of homeassistant.components.matter.
    In production, entry.runtime_data is a MatterEntryData whose .adapter.matter_client is
    the python-matter-server MatterClient.  In tests the fixture provides a mock in that slot.
    """
    if config_entry_id is not None:
        entry = hass.config_entries.async_get_entry(config_entry_id)
        if entry is None or not hasattr(entry, "runtime_data"):
            return None
        return entry.runtime_data.adapter.matter_client

    entries = hass.config_entries.async_loaded_entries(_MATTER_DOMAIN)
    if not entries or not hasattr(entries[0], "runtime_data"):
        return None
    return entries[0].runtime_data.adapter.matter_client


def lt_feature(node, endpoint_id: int) -> bool:
    """True if the OnOff cluster on the endpoint has the Lighting (LT) feature bit set.

    Reads from the node's cached endpoint attribute data.  Sync and cheap: no I/O.
    _OnOffFeatureMapAttr duck-types the chip.clusters attribute descriptor interface so the
    endpoint's attribute lookup works without chip being importable at module level.
    """
    endpoint = node.endpoints.get(endpoint_id)
    if endpoint is None:
        return False
    feature_map = endpoint.get_attribute_value(None, _ONOFF_FEATUREMAP)
    if feature_map is None:
        return False
    return bool(feature_map & _LT_FEATURE_BIT)


def ontime_attr_path(endpoint_id: int) -> str:
    """Attribute path string for OnOff.OnTime on the given endpoint.

    Format used by python-matter-server read_attribute: "{endpoint_id}/{cluster_id}/{attr_id}".
    """
    return f"{endpoint_id}/{_ONOFF_CLUSTER_ID}/{_ONTIME_ATTR_ID}"


def make_on_with_timed_off(on_off_control: int, on_time: int, off_wait_time: int):
    """Create an OnOff.Commands.OnWithTimedOff command object.

    chip.clusters is imported here rather than at module level so the adapter module loads
    cleanly when chip is not installed.  Tests inject a sys.modules mock for chip.clusters
    so the lazy import resolves to the mock without the real package being present.
    """
    from chip.clusters import Objects as clusters  # noqa: PLC0415

    return clusters.OnOff.Commands.OnWithTimedOff(
        onOffControl=on_off_control,
        onTime=on_time,
        offWaitTime=off_wait_time,
    )
