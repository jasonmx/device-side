"""Shelly Gen2+ over the core shelly integration's RPC connection. Gen1 (CoIoT) devices are unsupported."""

from .get_attributes import ShellyGetAttributes
from .turn_off_for import ShellyTurnOffFor
from .turn_on_for import ShellyTurnOnFor
from ...core.scope import IntegrationInfo

INTEGRATION = IntegrationInfo(key="shelly", title="Shelly", ha_domain="shelly", max_concurrency=4)

ADAPTERS = [ShellyGetAttributes, ShellyTurnOffFor, ShellyTurnOnFor]
