"""Dynamic dependency resolver for cross-submodule lookups and test mock interception.

Tests in this repository load ``ogame_ctl`` as an isolated module object via
``importlib.util.module_from_spec`` and apply unittest ``patch.object(ogame_ctl, ...)``
to mock out functions or override paths (like MEMORY_DIR, RUN_LEASE_FILE, etc.).

This resolver provides a central registry of active controller module namespaces
so that all domain submodules (browser, lifecycle, matrix, execution, legacy_commands)
can resolve dependencies dynamically, honoring test mocks and path overrides.
"""

from __future__ import annotations

import sys
from typing import Any, Callable, Dict, List, Optional

_ACTIVE_CONTROLLERS: List[Dict[str, Any]] = []

OVERRIDABLE_PATHS = frozenset({
    "MEMORY_DIR",
    "PLAN_FILE",
    "RATES_FILE",
    "NEXT_WAKE_FILE",
    "RUN_LEASE_FILE",
    "RUN_LEASE_GUARD_FILE",
    "WORKFLOW_DIR",
    "QUERY_TRACE_FILE",
    "EXPORT_PROBE_FILE",
    "DEFAULT_STRATEGY_PATH",
})


def register_controller(mod_globals: Dict[str, Any]) -> None:
    """Register a controller module's globals for dynamic dependency resolution."""
    if not any(c is mod_globals for c in _ACTIVE_CONTROLLERS):
        _ACTIVE_CONTROLLERS.append(mod_globals)


def _is_mock(val: Any) -> bool:
    if val is None:
        return False
    if hasattr(val, "assert_called") or hasattr(val, "_mock_return_value"):
        return True
    tname = type(val).__name__
    return tname in ("Mock", "MagicMock", "AsyncMock", "NonCallableMock", "NonCallableMagicMock")


def get_dep(name: str, default: Any = None) -> Any:
    """Look up a dependency from registered controllers (detecting mocks and overrides) or fallback."""
    # 1. Check registered controllers for explicit Mocks or non-default path overrides
    for c in reversed(_ACTIVE_CONTROLLERS):
        if name in c:
            val = c[name]
            if _is_mock(val):
                return val
            if name in OVERRIDABLE_PATHS:
                if default is not None and val != default:
                    return val
                if default is None and val is not None:
                    return val

    # 2. Check sys.modules for ogame_ctl
    for mod_name in ("ogame_ctl", "scripts.ogame_ctl"):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, name):
            val = getattr(mod, name)
            if _is_mock(val):
                return val
            if name in OVERRIDABLE_PATHS:
                if default is not None and val != default:
                    return val
                if default is None and val is not None:
                    return val

    return default
