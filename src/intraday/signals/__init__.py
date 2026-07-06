"""Signal plugins. Import this package to auto-register all signals."""

import importlib
import pkgutil


def load_all() -> None:
    """Import every module in this package so @signal decorators run."""
    for mod in pkgutil.iter_modules(__path__):
        if mod.name != "registry":
            importlib.import_module(f"{__name__}.{mod.name}")
