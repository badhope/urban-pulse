"""Behaviour regressions runner.

Why this file exists
--------------------
The gate needs one command that runs every regression module and fails loudly
when any of them is broken. It used to treat *any* skip as failure, which made
the whole CI job red on Linux for a test that can only run on Windows
(`test_windows_case_alias_reentrant_lock` guards case-insensitive filesystem
behaviour). A gate that goes red for a legitimate platform guard trains people
to ignore it, which is worse than not having the check.

What is still forbidden
-----------------------
- a module that fails                       -> red
- a module that runs zero tests             -> red (a silently empty suite is a lie)
- a module where *every* test was skipped   -> red (nothing was actually verified)
- a module with an undeclared skip          -> red

Declared skips are the narrow exception. Each entry names the platform it is
allowed on, so a skip can never silently spread to a platform where the test
should actually run.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MODULES = (
    "tests_checks_regression",
    "tests_turn_regression",
    "tests_mutation_regression",
    "tests_mcp_regression",
    "tests_archive_crash_regression",
    "tests_pending_sessions",
    "tests_panel_rejection_regression",
)

# test id -> set of platform families where skipping is legitimate.
# The Windows-only case-insensitive-lock test can only run on Windows, so on
# POSIX it is allowed to skip; on Windows it must actually execute.
ALLOWED_SKIPS = {
    'tests_pending_sessions.PendingSessions.test_windows_case_alias_reentrant_lock': {'posix'},
}


def _platform_family():
    return 'windows' if sys.platform.startswith('win') else 'posix'


def main():
    success = True
    family = _platform_family()
    for name in MODULES:
        print(f"\n=== {name} ===", flush=True)
        suite = unittest.defaultTestLoader.loadTestsFromName(name)
        result = unittest.TextTestRunner(verbosity=2).run(suite)

        problems = []
        if not result.wasSuccessful():
            problems.append('failed')
        if not result.testsRun:
            problems.append('ran no tests')
        if result.testsRun and len(result.skipped) >= result.testsRun:
            problems.append('every test was skipped')

        for test, reason in result.skipped:
            test_id = test.id()
            allowed = ALLOWED_SKIPS.get(test_id)
            if allowed is None:
                problems.append('undeclared skip %s (%s)' % (test_id, reason))
            elif family not in allowed:
                problems.append('skipped on a platform where it must run (%s): %s'
                                % (family, test_id))

        if problems:
            print('FAIL: %s: %s' % (name, '; '.join(problems)), file=sys.stderr)
            success = False
        elif result.skipped:
            print('OK: %s (%d ran, %d platform-declared skip)'
                  % (name, result.testsRun, len(result.skipped)))
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
