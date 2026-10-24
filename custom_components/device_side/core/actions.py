import functools

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, callback
from homeassistant.exceptions import ServiceValidationError

from .action import Action
from .runtime import get_runtime
from ..const import DOMAIN


async def _call_if_loaded(action: type[Action], hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    if not hass.config_entries.async_loaded_entries(DOMAIN):
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")
    return await get_runtime(hass).dispatcher.handle(action, call)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    for action in get_runtime(hass).registry.actions.values():
        hass.services.async_register(
            DOMAIN,
            action.key,
            functools.partial(_call_if_loaded, action, hass),
            schema=action.schema(),
            supports_response=action.supports_response,
        )
