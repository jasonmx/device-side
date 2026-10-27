from typing import ClassVar

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse

from ..core.action import Action
from ..core.models import ActionKind, Request


class GetAttributes(Action[Request]):
    """Read brightness, color temperature and color from the device side, including for a light that is off, and
    any on/off timer running on a light or switch (core.timer.timer_row)."""

    key: ClassVar[str] = "get_attributes"
    kind: ClassVar[ActionKind] = ActionKind.QUERY
    domains: ClassVar[frozenset[str]] = frozenset({"light", "switch"})
    supports_response: ClassVar[SupportsResponse] = SupportsResponse.ONLY

    @classmethod
    def parse(cls, hass: HomeAssistant, call: ServiceCall) -> Request:
        return Request()


ACTION = GetAttributes
