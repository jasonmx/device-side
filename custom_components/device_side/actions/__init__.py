import importlib
import pkgutil


def discover() -> list:
    """Return each action module's ACTION, sorted by module name so registration order is stable."""
    names = sorted(module.name for module in pkgutil.iter_modules(__path__))
    return [importlib.import_module(f"{__name__}.{name}").ACTION for name in names]
