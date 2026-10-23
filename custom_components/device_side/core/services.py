import functools

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, callback
from homeassistant.exceptions import ServiceValidationError

from .feature import Feature
from .runtime import get_runtime
from ..const import DOMAIN


async def _call_if_loaded(feature: type[Feature], hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    if not hass.config_entries.async_loaded_entries(DOMAIN):
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")
    return await get_runtime(hass).dispatcher.handle(feature, call)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    for feature in get_runtime(hass).registry.features.values():
        hass.services.async_register(
            DOMAIN,
            feature.key,
            functools.partial(_call_if_loaded, feature, hass),
            schema=feature.schema(),
            supports_response=feature.supports_response,
        )
