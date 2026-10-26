import pytest
from homeassistant.config_entries import ConfigEntryState

from ...fixtures.hue import HueBridge


class Clock:
    """A TransitionCache clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def bridge() -> HueBridge:
    return HueBridge()


@pytest.fixture(autouse=True)
async def unload_mock_hue_entries(hass):
    """Mark mocked hue entries not loaded before teardown, so HA doesn't run the real hue unload on them."""
    yield
    for entry in hass.config_entries.async_entries("hue"):
        entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
