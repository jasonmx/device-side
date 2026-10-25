from typing import ClassVar

from homeassistant.core import HomeAssistant, ServiceCall

from ..core.action import Action
from ..core.models import ActionKind, Request


class SetScene(Action[Request]):
    """Write a scene's settings to its lights without turning them on; lights already on change straight away."""

    key: ClassVar[str] = "set_scene"
    kind: ClassVar[ActionKind] = ActionKind.COMMAND
    domains: ClassVar[frozenset[str]] = frozenset({"scene"})

    @classmethod
    def parse(cls, hass: HomeAssistant, call: ServiceCall) -> Request:
        return Request()


ACTION = SetScene
