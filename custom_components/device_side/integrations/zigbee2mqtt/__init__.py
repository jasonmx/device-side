"""Zigbee2MQTT bridge over the core mqtt integration."""

from .addressing import is_z2m_group
from .detect import detect
from .get_attributes import Z2MGetAttributes
from .turn_on_for import Z2MTurnOnFor
from ...core.scope import IntegrationInfo

INTEGRATION = IntegrationInfo(
    key="zigbee2mqtt",
    title="Zigbee2MQTT",
    ha_domain="mqtt",
    detect=detect,
    is_group=is_z2m_group,
    max_concurrency=4,
)

ADAPTERS = [Z2MGetAttributes, Z2MTurnOnFor]
