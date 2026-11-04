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


def main():
    success = True
    for name in MODULES:
        print(f"\n=== {name} ===", flush=True)
        suite = unittest.defaultTestLoader.loadTestsFromName(name)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        if not result.wasSuccessful() or not result.testsRun or result.skipped:
            print(f"FAIL: {name} failed, ran no tests, or skipped tests", file=sys.stderr)
            success = False
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
