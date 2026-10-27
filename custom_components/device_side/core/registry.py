import importlib
import logging
from collections.abc import Iterable, Iterator
from types import ModuleType

from .action import Action
from .adapter import Adapter
from .scope import IntegrationInfo
from .. import actions as actions_pkg
from .. import integrations as integrations_pkg

_LOGGER = logging.getLogger(__name__)


class AdapterRegistry:
    """Actions, integrations and the adapters joining them, built from module data with no side effects and no hass.

    That is what lets check_release.py and the rig runner import it offline, and tests build one from an explicit list.
    """

    def __init__(self, actions: Iterable[type[Action]], integration_modules: Iterable[str | ModuleType]):
        self.actions: dict[str, type[Action]] = {action.key: action for action in actions}
        self.integrations: dict[str, IntegrationInfo] = {}
        self._adapters: dict[tuple[str, str], Adapter] = {}
        for module in integration_modules:
            self._add_integration(module)

    @classmethod
    def discover(cls) -> AdapterRegistry:
        """The production registry. Imports modules, so run it in the import executor."""
        return cls(actions_pkg.discover(), integrations_pkg.discover())

    def _add_integration(self, module: str | ModuleType) -> None:
        if isinstance(module, str):
            name = module
            try:
                module = importlib.import_module(module)
            except ImportError as err:
                # The core integration (and so its library) is absent; the other integrations still load.
                key = name.rpartition(".")[2]
                _LOGGER.debug("Integration %s unavailable: %s", key, err)
                self.integrations[key] = IntegrationInfo(
                    key=key, title=key, ha_domain=key, available=False, unavailable_reason=str(err)
                )
                return
        info: IntegrationInfo = module.INTEGRATION
        self.integrations[info.key] = info
        for cls in module.ADAPTERS:
            if cls.integration != info.key:
                raise ValueError(f"{cls.__name__} declares integration {cls.integration}, module is {info.key}")
            if cls.action not in self.actions:
                raise ValueError(f"{cls.__name__} serves unknown action {cls.action}")
            self._adapters[(cls.action, info.key)] = cls()

    def adapter(self, action: str, integration: str) -> Adapter | None:
        return self._adapters.get((action, integration))

    def available_integrations(self) -> list[IntegrationInfo]:
        return [info for info in self.integrations.values() if info.available]

    def matrix(self) -> Iterator[tuple[str, str, Adapter | None]]:
        """Every action x integration pair, sorted, with its adapter or None."""
        for action in sorted(self.actions):
            for integration in sorted(self.integrations):
                yield action, integration, self.adapter(action, integration)
