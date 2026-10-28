import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    CONF_PREDICTED_STATE,
    CONF_Z2M_COLOR_MODES,
    DOMAIN,
    NAME,
    PREDICTED_STATE_DEFAULT,
    Z2M_COLOR_MODES_DEFAULT,
)


class DeviceSideConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Device Side."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> DeviceSideOptionsFlow:
        return DeviceSideOptionsFlow()

    async def async_step_user(self, user_input=None):
        """Handle the initial step when the user clicks 'Add Integration'."""
        if user_input is not None:
            return self.async_create_entry(title=NAME, data={})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
        )


class DeviceSideOptionsFlow(config_entries.OptionsFlowWithReload):
    """One page of options; saving reloads the entry, so the next action runs with them."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PREDICTED_STATE, default=options.get(CONF_PREDICTED_STATE, PREDICTED_STATE_DEFAULT)
                    ): bool,
                    vol.Required(
                        CONF_Z2M_COLOR_MODES, default=options.get(CONF_Z2M_COLOR_MODES, Z2M_COLOR_MODES_DEFAULT)
                    ): bool,
                }
            ),
        )
