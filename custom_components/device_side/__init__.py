from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .core.dispatcher import Dispatcher
from .core.registry import AdapterRegistry
from .core.runtime import DATA, DeviceSideData
from .core.services import async_setup_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType):
    # Discovery imports every platform module, so it runs in the import executor rather than the event loop.
    registry = await hass.async_add_import_executor_job(AdapterRegistry.discover)
    hass.data[DATA] = DeviceSideData(registry=registry, dispatcher=Dispatcher(hass, registry))
    # Services are registered once per HA run, not per entry; handlers refuse calls until the entry loads.
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    return True
