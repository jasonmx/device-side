from typing import ClassVar

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse

from ..core.action import Action
from ..core.models import ActionKind, Request


class GetAttributes(Action[Request]):
    """Read brightness, color temperature and color from the device side, including for a light that is off."""

    key: ClassVar[str] = "get_attributes"
    kind: ClassVar[ActionKind] = ActionKind.QUERY
    domains: ClassVar[frozenset[str]] = frozenset({"light"})
    supports_response: ClassVar[SupportsResponse] = SupportsResponse.ONLY

    @classmethod
    def parse(cls, hass: HomeAssistant, call: ServiceCall) -> Request:
        return Request()


ACTION = GetAttributes
