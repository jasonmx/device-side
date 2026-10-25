from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_side import actions
from custom_components.device_side.const import DOMAIN
from custom_components.device_side.core.registry import AdapterRegistry

from .fakes.scripted import SCRIPT

FAKE_INTEGRATIONS = ["tests.fakes.broken_integration", "tests.fakes.fake_integration", "tests.fakes.fake_special"]

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def reset_script():
    SCRIPT.reset()
    yield SCRIPT


@pytest.fixture
def fake_registry():
    """Production actions over the fake integrations, in place of discovery."""
    with patch.object(AdapterRegistry, "discover", lambda: AdapterRegistry(actions.discover(), FAKE_INTEGRATIONS)):
        yield


@pytest.fixture
async def setup_integration(hass: HomeAssistant, fake_registry) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.fixture
async def setup_production(hass: HomeAssistant) -> MockConfigEntry:
    """The integration over the real discovered integrations, for adapter tests."""
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def call(hass: HomeAssistant, service: str, data: dict, return_response: bool = True):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=return_response
    )
