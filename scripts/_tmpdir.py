"""Temp-directory helper for verification scripts.

Why this exists
---------------
Several scripts created scratch directories with
`tempfile.mkdtemp(dir=os.path.join(ROOT, '.tmp'))`. That works on a developer
machine where `.tmp/` happens to exist, and fails on a fresh clone — `.tmp/` is
gitignored, so CI checkouts never have it. The failure mode was a bare
`FileNotFoundError: .../.tmp/tmpXXXX` with no hint about what to do.

Keeping scratch space inside the repository is still the right default (the
project rule is "artifacts stay in the workspace"), so the fix is to create the
directory on demand rather than to move the scratch space elsewhere.

Usage:
    from _tmpdir import workspace_tmpdir
    work = workspace_tmpdir("verify-something")
"""

import os
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def workspace_tmpdir(prefix="wg-"):
    """Create a scratch directory under `<repo>/.tmp/`, creating `.tmp` if absent."""
    base = os.path.join(ROOT, ".tmp")
    os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(prefix=prefix, dir=base)
