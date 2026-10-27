from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import CONF_PREDICTED_STATE, DOMAIN, PREDICTED_STATE_DEFAULT
from .core.actions import async_setup_services
from .core.dispatcher import Dispatcher
from .core.registry import AdapterRegistry
from .core.runtime import DATA, DeviceSideData, get_runtime

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType):
    # Discovery imports every integration module, so it runs in the import executor rather than the event loop.
    registry = await hass.async_add_import_executor_job(AdapterRegistry.discover)
    hass.data[DATA] = DeviceSideData(registry=registry, dispatcher=Dispatcher(hass, registry))
    # Services are registered once per HA run, not per entry; handlers refuse calls until the entry loads.
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    # An entry saved before the option existed has no options: it gets the default.
    get_runtime(hass).predicted_state = entry.options.get(CONF_PREDICTED_STATE, PREDICTED_STATE_DEFAULT)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    runtime = get_runtime(hass)
    runtime.cancel_pending()
    runtime.detach_all()
    return True
