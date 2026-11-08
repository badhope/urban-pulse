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

    # Register a finder that resolves bare top-level names (`import mcp_server`)
    # to the already-loaded package submodules. Without this, the same file can be
    # imported twice under two names and module-level side effects run twice —
    # which for mcp_server.py means every @server.tool() registers again.
    _install_alias_finder(directory)

    # Execute __init__.py for real: package metadata lives there, and merely
    # registering the object leaves `__version__` undefined.
    spec.loader.exec_module(module)
    return directory


def _install_alias_finder(directory: str) -> None:
    """Route bare-name imports of package modules to the package copy."""
    if getattr(sys, '_wg_alias_finder', False):
        return
    import importlib.abc
    import importlib.machinery

    names = {'mcp_server', 'engine', 'panel', 'sessions', 'templates',
             'settings_loader', 'state_schema', 'input_policy', 'viz_series',
             'init_game', 'cli', 'action_log', 'mcp_primitives'}
    package = _PACKAGE

    class _AliasLoader(importlib.abc.Loader):
        def __init__(self, name):
            self.name = name

        def create_module(self, spec):
            return sys.modules.get(package + '.' + self.name)

        def exec_module(self, module):
            # Already executed as a package submodule; nothing to redo.
            return None

    class _AliasFinder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname not in names:
                return None
            if fullname in sys.modules:
                return None
            # Only alias when the package submodule is ALREADY loaded. Returning a
            # spec that resolves to None makes Python install an empty module —
            # which is exactly how `import panel` once produced a module with no
            # __file__ and no view_model (v1.8.0 regression, caught by the gate).
            if (_PACKAGE + '.' + fullname) not in sys.modules:
                return None
            return importlib.machinery.ModuleSpec(fullname, _AliasLoader(fullname))

    sys.meta_path.insert(0, _AliasFinder())
    sys._wg_alias_finder = True


def ensure_parent_on_path(script_dir: str | None = None) -> None:
    """Put the directory above the package on sys.path (needed by CLI shims)."""
    directory = script_dir or os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(directory)
    if parent and parent not in sys.path:
        sys.path.insert(0, parent)


def alias_top_level(names=('mcp_server', 'engine', 'panel', 'sessions', 'templates',
                           'settings_loader', 'state_schema', 'input_policy',
                           'viz_series', 'init_game', 'cli', 'action_log',
                           'mcp_primitives')) -> int:
    """Make `import x` and `import game_engine.x` resolve to ONE module object.

    Why: without this, a process that imports the package on one path and the
    bare name on another loads the file twice, so module-level registration runs
    twice. For `mcp_server.py` that means every `@server.tool()` executes again
    and the SDK logs "Tool already exists" for each tool — which is exactly what
    broke the mutation harness (its baseline assumes an empty stderr).

    Aliasing is safe because both names then share one module dict, one server
    instance and one set of counters.
    """
    import importlib
    aliased = 0
    for name in names:
        full = _PACKAGE + '.' + name
        module = sys.modules.get(full)
        if module is None:
            try:
                module = importlib.import_module(full)
            except Exception:  # nosec B112; aqg: boundary — optional module may not exist
                continue
        if sys.modules.get(name) is not module:
            sys.modules[name] = module
            aliased += 1
    return aliased
