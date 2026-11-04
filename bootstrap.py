"""Package bootstrap for direct script execution.

Why this exists: the repository root *is* the `game_engine` package, so
`python mcp_server.py` has no parent directory on `sys.path` and `import
game_engine.rules.combat` would fail. Historically every entry point carried
its own copy of this ~15-line `spec_from_file_location` dance, which meant a
fix in one copy silently missed the others.

`bootstrap.install()` registers the running directory as the `game_engine`
package, executing `__init__.py` so package metadata (`__version__`) is real.
It is idempotent and safe to call from any entry point or test harness.

After `pip install -e .` the package is importable normally; this module is
only the fallback that makes a bare checkout work without installation.
"""

from __future__ import annotations

import importlib.util
import os
import sys

_PACKAGE = 'game_engine'


def install(script_dir: str | None = None) -> str:
    """Register `script_dir` as the `game_engine` package. Returns the directory used.

    Idempotent: a second call is a no-op once the package is importable.
    """
    if _PACKAGE in sys.modules:
        return script_dir or os.path.dirname(os.path.abspath(__file__))

    directory = script_dir or os.path.dirname(os.path.abspath(__file__))
    init_path = os.path.join(directory, '__init__.py')
    if not os.path.isfile(init_path):
        # Installed package: nothing to do, let the normal import machinery work.
        return directory

    spec = importlib.util.spec_from_file_location(
        _PACKAGE, init_path, submodule_search_locations=[directory])
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError('cannot build an import spec for %s' % init_path)
    module = importlib.util.module_from_spec(spec)
    module.__path__ = [directory]
    sys.modules[_PACKAGE] = module
    # Execute __init__.py for real: package metadata lives there, and merely
    # registering the object leaves `__version__` undefined.
    spec.loader.exec_module(module)
    return directory


def ensure_parent_on_path(script_dir: str | None = None) -> None:
    """Put the directory above the package on sys.path (needed by CLI shims)."""
    directory = script_dir or os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(directory)
    if parent and parent not in sys.path:
        sys.path.insert(0, parent)
