"""Parse a Matter entity's node address from its unique_id, and check OnOff cluster features.

No imports from homeassistant.components.matter or chip.clusters at module level: those packages
require matter_server and chip to be installed, but the adapter must import cleanly in test
environments where only the core homeassistant package is present.  All matter-specific operations
are accessed either through hass.config_entries or via deferred imports confined to a single
helper function (make_on_with_timed_off).
"""

from homeassistant.core import HomeAssistant

from ...core.models import Target

_MATTER_DOMAIN = "matter"

# OnOff cluster constants (Matter spec, cluster 0x0006)
_ONOFF_CLUSTER_ID = 6
_FEATUREMAP_ATTR_ID = 65532  # 0xFFFC
_LT_FEATURE_BIT = 0x0001  # Lighting (LT) is bit 0; bit 1 (0x2) is DeadFrontBehavior
_ONTIME_ATTR_ID = 16385  # 0x4001 — counts down to 0 while the timed-on is running


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


def _onoff_attr_path(endpoint_id: int, attr_id: int) -> str:
    """An OnOff attribute's path as python-matter-server keys it: "{endpoint}/{cluster}/{attribute}"."""
    return f"{endpoint_id}/{_ONOFF_CLUSTER_ID}/{attr_id}"


def lt_feature(node, endpoint_id: int) -> bool:
    """True if the OnOff cluster on the endpoint has the Lighting (LT) feature bit set.

    Reads the node's raw attribute cache. Sync and cheap: no I/O. MatterEndpoint.get_attribute_value
    would need a real chip.clusters descriptor.
    """
    feature_map = node.node_data.attributes.get(_onoff_attr_path(endpoint_id, _FEATUREMAP_ATTR_ID))
    return isinstance(feature_map, int) and bool(feature_map & _LT_FEATURE_BIT)


def unsupported_reason(hass: HomeAssistant, target: Target) -> str | None:
    """Why this entity can't run an OnOff timer, or None: it needs a reachable node whose endpoint has LT."""
    node_id = node_id_from_unique_id(target.entry.unique_id)
    ep_id = endpoint_id_from_unique_id(target.entry.unique_id)
    if node_id is None or ep_id is None:
        return "not_addressable"

    client = matter_client(hass, target.entry.config_entry_id)
    if client is None:
        return "not_addressable"

    try:
        node = client.get_node(node_id)
    except Exception:  # noqa: BLE001 - node lookup can raise if the node no longer exists
        return "not_addressable"

    if node is None:
        return "not_addressable"

    if not lt_feature(node, ep_id):
        return "no_lt_feature"

    return None


def ontime_attr_path(endpoint_id: int) -> str:
    """Attribute path for OnOff.OnTime on the given endpoint, for python-matter-server's read_attribute."""
    return _onoff_attr_path(endpoint_id, _ONTIME_ATTR_ID)


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
