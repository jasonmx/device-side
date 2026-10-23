import pkgutil


def discover() -> list[str]:
    """Return each platform module's dotted name, sorted so discovery order is stable.

    Names, not modules: the registry imports each one behind a guard, since a platform whose core integration is
    absent fails to import and must not stop the others loading.
    """
    return [f"{__name__}.{module.name}" for module in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name)]
