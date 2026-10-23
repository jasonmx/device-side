import importlib
import logging
from collections.abc import Iterable, Iterator
from types import ModuleType

from .capabilities import PlatformInfo
from .cell import Cell
from .feature import Feature
from .. import features as features_pkg
from .. import platforms as platforms_pkg

_LOGGER = logging.getLogger(__name__)


class CellRegistry:
    """Features, platforms and the cells joining them, built from module data with no side effects and no hass.

    That is what lets gen_docs.py and the rig runner import it offline, and tests build one from an explicit list.
    """

    def __init__(self, features: Iterable[type[Feature]], platform_modules: Iterable[str | ModuleType]):
        self.features: dict[str, type[Feature]] = {feature.key: feature for feature in features}
        self.platforms: dict[str, PlatformInfo] = {}
        self._cells: dict[tuple[str, str], Cell] = {}
        for module in platform_modules:
            self._add_platform(module)

    @classmethod
    def discover(cls) -> CellRegistry:
        """The production registry. Imports modules, so run it in the import executor."""
        return cls(features_pkg.discover(), platforms_pkg.discover())

    def _add_platform(self, module: str | ModuleType) -> None:
        if isinstance(module, str):
            name = module
            try:
                module = importlib.import_module(module)
            except ImportError as err:
                # The core integration (and so its library) is absent; the other platforms still load.
                key = name.rpartition(".")[2]
                _LOGGER.debug("Platform %s unavailable: %s", key, err)
                self.platforms[key] = PlatformInfo(
                    key=key, title=key, ha_integration=key, available=False, unavailable_reason=str(err)
                )
                return
        info: PlatformInfo = module.PLATFORM
        self.platforms[info.key] = info
        for cell_cls in module.CELLS:
            if cell_cls.platform != info.key:
                raise ValueError(f"{cell_cls.__name__} declares platform {cell_cls.platform}, module is {info.key}")
            if cell_cls.feature not in self.features:
                raise ValueError(f"{cell_cls.__name__} serves unknown feature {cell_cls.feature}")
            self._cells[(cell_cls.feature, info.key)] = cell_cls()

    def cell(self, feature: str, platform: str) -> Cell | None:
        return self._cells.get((feature, platform))

    def available_platforms(self) -> list[PlatformInfo]:
        return [info for info in self.platforms.values() if info.available]

    def matrix(self) -> Iterator[tuple[str, str, Cell | None]]:
        """Every feature x platform pair, sorted, with its cell or None."""
        for feature in sorted(self.features):
            for platform in sorted(self.platforms):
                yield feature, platform, self.cell(feature, platform)
