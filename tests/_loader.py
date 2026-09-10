"""Load the integration's modules without a Home Assistant installation.

The component package imports Home Assistant at module level, so the modules
under test are loaded individually into a synthetic package that provides the
relative-import machinery they rely on.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

PACKAGE = "netatmo_presence_local_under_test"
COMPONENT_DIR = (
    pathlib.Path(__file__).resolve().parents[1]
    / "custom_components"
    / "netatmo_presence_local"
)


def _ensure_package() -> types.ModuleType:
    """Register the synthetic package that relative imports resolve against."""
    if PACKAGE not in sys.modules:
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(COMPONENT_DIR)]
        sys.modules[PACKAGE] = package
    return sys.modules[PACKAGE]


def load(module_name: str) -> types.ModuleType:
    """Import one module of the integration by file name."""
    _ensure_package()
    qualified = f"{PACKAGE}.{module_name}"
    if qualified in sys.modules:
        return sys.modules[qualified]

    spec = importlib.util.spec_from_file_location(
        qualified, COMPONENT_DIR / f"{module_name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module
