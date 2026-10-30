import importlib
import pkgutil


def discover() -> list:
    """Return each action module's ACTION, sorted by module name so registration order is stable. A module without
    one holds what several actions share."""
    names = sorted(module.name for module in pkgutil.iter_modules(__path__))
    modules = [importlib.import_module(f"{__name__}.{name}") for name in names]
    return [module.ACTION for module in modules if hasattr(module, "ACTION")]
