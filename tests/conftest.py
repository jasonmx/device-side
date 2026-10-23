import os
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_side import features
from custom_components.device_side.const import DOMAIN
from custom_components.device_side.core.registry import AdapterRegistry

from .fakes.scripted import SCRIPT

FAKE_PLATFORMS = ["tests.fakes.broken_platform", "tests.fakes.fake_platform", "tests.fakes.fake_special"]

RIG_DIR = Path(__file__).parent / "rig"


def pytest_ignore_collect(collection_path: Path, config):
    """Unit runs never import the rig: it talks to the live HA. scripts/rig.py sets DEVICE_SIDE_RIG=1."""
    if collection_path == RIG_DIR and os.environ.get("DEVICE_SIDE_RIG") != "1":
        return True
    return None


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def reset_script():
    SCRIPT.reset()
    yield SCRIPT


@pytest.fixture
def fake_registry():
    """Production features over the fake platforms, in place of discovery."""
    with patch.object(AdapterRegistry, "discover", lambda: AdapterRegistry(features.discover(), FAKE_PLATFORMS)):
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
    """The integration over the real discovered platforms, for platform adapter tests."""
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def call(hass: HomeAssistant, service: str, data: dict, return_response: bool = True):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=return_response
    )
