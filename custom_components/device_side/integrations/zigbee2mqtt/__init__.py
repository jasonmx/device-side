"""Zigbee2MQTT bridge over the core mqtt integration."""

from .detect import detect
from .turn_on_for import Z2MTurnOnFor
from ...core.scope import IntegrationInfo

INTEGRATION = IntegrationInfo(
    key="zigbee2mqtt",
    title="Zigbee2MQTT",
    ha_domain="mqtt",
    detect=detect,
    max_concurrency=4,
)

ADAPTERS = [Z2MTurnOnFor]
