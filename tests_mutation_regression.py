import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('verify_mutation', ROOT / 'scripts' / 'verify_mutation.py')
mutation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mutation)


class MutationRegressionTests(unittest.TestCase):
    def run_case(self, script, only='M01'):
        with tempfile.TemporaryDirectory(prefix='.mutation-test-', dir=ROOT) as directory:
            root = Path(directory)
            (root / '__init__.py').write_text('__version__ = "1"\n', encoding='utf-8')
            (root / 'mcp_server.py').write_text('', encoding='utf-8')
            target = root / 'target.txt'
            target.write_text('original', encoding='utf-8')
            (root / 'check.py').write_text(script, encoding='utf-8')
            entries = [('M01', 'fixture', 'target.txt', 'original', 'mutated', 'check.py')]
            output = io.StringIO()
            with patch.object(mutation, 'ROOT', str(root)), patch.object(mutation, 'MUTATIONS', entries), \
                    patch.dict(mutation.EXPECTED_FAILURES, {'M01': ('target',)}, clear=True), \
                    patch.object(sys, 'argv', ['verify_mutation.py', '--only', only]), \
                    contextlib.redirect_stdout(output):
                result = mutation.main()
            self.assertEqual(target.read_text(encoding='utf-8'), 'original')
            return result, output.getvalue()

    def test_unknown_selector_fails(self):
        result, output = self.run_case('raise SystemExit(0)\n', only='missing')
        self.assertNotEqual(result, 0, output)

    def test_failing_baseline_never_counts_as_killed(self):
        result, output = self.run_case('print("FAIL  baseline")\nraise SystemExit(1)\n')
        self.assertNotEqual(result, 0, output)
        self.assertNotIn('KILLED', output)

    def test_mutant_crash_never_counts_as_killed(self):
        script = ('from pathlib import Path\n'
                  'if Path("target.txt").read_text() == "mutated":\n'
                  '    raise RuntimeError("environment failure")\n')
        result, output = self.run_case(script)
        self.assertNotEqual(result, 0, output)
        self.assertNotIn('KILLED', output)
        self.assertIn('RuntimeError', output)

    def test_failure_followed_by_crash_is_uncertain(self):
        script = ('from pathlib import Path\n'
                  'if Path("target.txt").read_text() == "mutated":\n'
                  '    print("FAIL  first assertion")\n'
                  '    raise RuntimeError("later crash")\n')
        result, output = self.run_case(script)
        self.assertNotEqual(result, 0, output)
        self.assertNotIn('KILLED', output)

    def test_unexplained_nonzero_is_uncertain(self):
        script = ('from pathlib import Path\n'
                  'if Path("target.txt").read_text() == "mutated":\n'
                  '    raise SystemExit(7)\n')
        result, output = self.run_case(script)
        self.assertNotEqual(result, 0, output)
        self.assertNotIn('KILLED', output)

    def test_explicit_failure_kills_mutant(self):
        script = ('from pathlib import Path\n'
                  'if Path("target.txt").read_text() == "mutated":\n'
                  '    print("FAIL  target  mismatch")\n'
                  '    print("0/1 passed")\n'
                  '    raise SystemExit(1)\n'
                  'print("PASS  target  ok")\n'
                  'print("1/1 passed")\n')
        result, output = self.run_case(script)
        self.assertEqual(result, 0, output)
        self.assertIn('KILLED', output)

    def test_mcp_expected_diagnostic_requires_targeted_failure_and_complete_summary(self):
        diagnostic = "Tool 'tick' failed: 'Error executing tool tick: 当前没有进行中的对局：先调用 world_init（新建）或 world_open（续跑）'\n"
        baseline = 'PASS  trade 买入的物品真的进了背包（2 件金疮药）  items=2\n1/1 passed\n'
        failed = 'FAIL  trade 买入的物品真的进了背包（2 件金疮药）  items={}\n0/1 passed\n'
        self.assertTrue(mutation._targeted_mcp_failure('M05', baseline, diagnostic, 1, failed, diagnostic))
        self.assertFalse(mutation._targeted_mcp_failure('M05', baseline, diagnostic, 1, failed, diagnostic + 'Traceback: crash\n'))
        self.assertFalse(mutation._targeted_mcp_failure('M05', baseline, diagnostic, 1, failed.replace('0/1 passed', ''), diagnostic))
        self.assertFalse(mutation._targeted_mcp_failure('M26', baseline, diagnostic, 1, failed, diagnostic))
        self.assertFalse(mutation._targeted_mcp_failure('M05', baseline, diagnostic, 1, failed + 'FAIL  unrelated\n', diagnostic))

    def test_unrelated_failure_does_not_kill(self):
        script = ('from pathlib import Path\n'
                  'if Path("target.txt").read_text() == "mutated":\n'
                  '    print("FAIL  unrelated")\n'
                  '    raise SystemExit(1)\n'
                  'print("PASS  target")\n'
                  'print("1/1 passed")\n')
        result, output = self.run_case(script)
        self.assertNotEqual(result, 0, output)
        self.assertNotIn('KILLED', output)

    def test_target_failure_without_completion_does_not_kill(self):
        script = ('from pathlib import Path\n'
                  'if Path("target.txt").read_text() == "mutated":\n'
                  '    print("FAIL  target")\n'
                  '    raise SystemExit(1)\n'
                  'print("PASS  target")\n'
                  'print("1/1 passed")\n')
        result, output = self.run_case(script)
        self.assertNotEqual(result, 0, output)
        self.assertNotIn('KILLED', output)

    def test_complete_unrelated_failure_does_not_kill(self):
        script = ('from pathlib import Path\n'
                  'if Path("target.txt").read_text() == "mutated":\n'
                  '    print("PASS  target")\n'
                  '    print("FAIL  unrelated")\n'
                  '    print("1/2 passed")\n'
                  '    raise SystemExit(1)\n'
                  'print("PASS  target")\n'
                  'print("PASS  unrelated")\n'
                  'print("2/2 passed")\n')
        result, output = self.run_case(script)
        self.assertNotEqual(result, 0, output)
        self.assertNotIn('KILLED', output)

    def test_target_failure_with_extra_failure_is_uncertain(self):
        script = ('from pathlib import Path\n'
                  'if Path("target.txt").read_text() == "mutated":\n'
                  '    print("FAIL  target")\n'
                  '    print("FAIL  unrelated")\n'
                  '    print("0/2 passed")\n'
                  '    raise SystemExit(1)\n'
                  'print("PASS  target")\n'
                  'print("PASS  unrelated")\n'
                  'print("2/2 passed")\n')
        result, output = self.run_case(script)
        self.assertNotEqual(result, 0, output)
        self.assertNotIn('KILLED', output)

    def test_surviving_mutant_fails(self):
        result, output = self.run_case('print("PASS  behavior")\n')
        self.assertNotEqual(result, 0, output)
        self.assertIn('SURVIVED', output)


def session_name_check():
    spec = importlib.util.spec_from_file_location('mutation_sessions', ROOT / 'sessions.py')
    sessions = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sessions)
    got = sessions.safe_name('雾港/调查/第一局')
    expected = '雾港_调查_第一局'
    if got != expected:
        print('FAIL  N4 局名被安全化  got=%r want=%r' % (got, expected))
        print('0/1 passed')
        return 1
    print('PASS  N4 局名被安全化  got=%r' % got)
    print('1/1 passed')
    return 0


if __name__ == '__main__':
    if sys.argv[1:] == ['--session-name-check']:
        sys.exit(session_name_check())
    unittest.main()
