from typing import ClassVar

from homeassistant.core import HomeAssistant, ServiceCall

from ..core.action import Action
from ..core.models import ActionKind, Request


class Stop(Action[Request]):
    """Halt every raise and lower in flight on the target, whichever attribute, where it is now."""

    key: ClassVar[str] = "stop"
    kind: ClassVar[ActionKind] = ActionKind.COMMAND
    domains: ClassVar[frozenset[str]] = frozenset({"light"})

    @classmethod
    def parse(cls, hass: HomeAssistant, call: ServiceCall) -> Request:
        return Request()


ACTION = Stop
