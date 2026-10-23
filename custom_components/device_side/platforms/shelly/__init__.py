"""Shelly Gen2+ over the core shelly integration's RPC connection. Gen1 (CoIoT) devices are unsupported."""

from .turn_off_for import ShellyTurnOffFor
from .turn_on_for import ShellyTurnOnFor
from ...core.capabilities import PlatformInfo

PLATFORM = PlatformInfo(key="shelly", title="Shelly", ha_integration="shelly", max_concurrency=4)

ADAPTERS = [ShellyTurnOffFor, ShellyTurnOnFor]
