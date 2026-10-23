import importlib
import pkgutil


def discover() -> list:
    """Return each feature module's FEATURE, sorted by module name so registration order is stable."""
    names = sorted(module.name for module in pkgutil.iter_modules(__path__))
    return [importlib.import_module(f"{__name__}.{name}").FEATURE for name in names]
