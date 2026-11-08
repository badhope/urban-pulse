import errno
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import state_schema


ROOT = Path(__file__).resolve().parent
CHILD = r'''
import os, sys
import state_schema as s
path = sys.argv[1]
append = s._append_archive
def crash(path, entries):
    append(path, entries)
    os._exit(42)
s._append_archive = crash
def edit(state):
    state['prose'] = [{'text': 'new'}]
s.transact_state(edit, path, archive_entries=[{'type': 'prose', 'text': 'old'}])
'''


class ArchiveCrashRegression(unittest.TestCase):
    def test_crash_then_retry_preserves_history_without_duplicates(self):
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory(dir=ROOT) as directory:
                path = str(Path(directory) / 'state.json')
                archive = Path(path + '.log.2.jsonl')
                history = {'type': 'history', 'text': 'old'}
                if existing:
                    archive.write_text(json.dumps(history) + '\n', encoding='utf-8')
                state = state_schema.new_game()
                state.update({'archive_generation': 2, 'config': {'event_log_keep': 1},
                              'event_log': [{'type': 'event', 'text': 'prior'}, {'type': 'event', 'text': 'recent'}],
                              'prose': [{'text': 'old'}]})
                Path(path).write_text(json.dumps(state), encoding='utf-8')
                child = subprocess.run([sys.executable, '-B', '-c', CHILD, path], cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(child.returncode, 42, child.stderr)
                with self.assertRaises(RuntimeError):
                    state_schema.load_state(path)
                self.assertEqual(json.loads(Path(path).read_text(encoding='utf-8'))['prose'], [{'text': 'old'}])
                def edit(current):
                    current['prose'] = [{'text': 'new'}]
                before = archive.read_bytes()
                state_before = Path(path).read_bytes()
                pending = Path(path + '.archive-pending')
                pending_before = pending.read_bytes()
                with self.assertRaisesRegex(RuntimeError, '人工'):
                    state_schema.transact_state(edit, path, archive_entries=[{'type': 'prose', 'text': 'old'}])
                self.assertEqual(archive.read_bytes(), before)
                self.assertEqual(Path(path).read_bytes(), state_before)
                self.assertEqual(pending.read_bytes(), pending_before)
                entries = [json.loads(line) for line in before.splitlines()]
                expected = ([history] if existing else []) + [{'type': 'event', 'text': 'prior'}, {'type': 'prose', 'text': 'old'}]
                self.assertEqual(entries, expected)

    def test_concurrent_retries_are_serialized(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = str(Path(directory) / 'state.json')
            state = state_schema.new_game()
            state.update({'config': {'event_log_keep': 1}, 'event_log': [1, 2]})
            Path(path).write_text(json.dumps(state), encoding='utf-8')
            child = subprocess.run([sys.executable, '-B', '-c', CHILD, path], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(child.returncode, 42, child.stderr)
            code = "import sys, state_schema as s; s.transact_state(lambda state: state.update(tick=state['tick']+1), sys.argv[1])"
            children = [subprocess.Popen([sys.executable, '-B', '-c', code, path], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
            results = [(process, *process.communicate(timeout=20)) for process in children]
            for process, stdout, stderr in results:
                self.assertNotEqual(process.returncode, 0, (stdout, stderr))
                self.assertIn(b'RuntimeError', stderr)
            with self.assertRaises(RuntimeError):
                state_schema.load_state(path)
            self.assertEqual(json.loads(Path(path).read_text(encoding='utf-8'))['tick'], 0)
            entries = [json.loads(line) for line in Path(path + '.log.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(entries, [1, {'type': 'prose', 'text': 'old'}])

    def _assert_journal_link_rejected(self, directory):
        path = str(Path(directory) / 'state.json')
        pending = path + '.archive-pending'
        victim = Path(directory) / 'victim'
        victim.write_text('untouched', encoding='utf-8')
        try:
            os.symlink(victim, pending)
        except (OSError, NotImplementedError) as exc:
            if isinstance(exc, OSError) and exc.errno not in (errno.EPERM, errno.EACCES, errno.ENOSYS, errno.EOPNOTSUPP) and getattr(exc, 'winerror', None) != 1314:
                raise
            print('真实符号链接未验证；使用受控路径检测模拟', file=sys.stderr)
            policy = state_schema._input_policy
            real_lexists = os.path.lexists
            real_islink = os.path.islink
            def lexists(target):
                return os.path.abspath(target) == os.path.abspath(pending) or real_lexists(target)
            def islink(target):
                return os.path.abspath(target) == os.path.abspath(pending) or real_islink(target)
            with patch.object(policy.os.path, 'lexists', side_effect=lexists), patch.object(policy.os.path, 'islink', side_effect=islink):
                with self.assertRaises(policy.PolicyError):
                    state_schema.save_state(state_schema.new_game(), path)
            mode = 'simulated'
        else:
            with self.assertRaises(state_schema._input_policy.PolicyError):
                state_schema.save_state(state_schema.new_game(), path)
            mode = 'real'
        self.assertEqual(victim.read_text(encoding='utf-8'), 'untouched')
        self.assertFalse(Path(path).exists())
        return mode

    def test_journal_link_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            self._assert_journal_link_rejected(directory)

    def test_symlink_permission_denied_uses_simulation_without_skip(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            with patch.object(os, 'symlink', side_effect=PermissionError(errno.EPERM, 'denied')):
                self.assertEqual(self._assert_journal_link_rejected(directory), 'simulated')

    def test_hardlink_unsupported_preserves_state_and_archive(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = str(Path(directory) / 'state.json')
            state = state_schema.new_game()
            state.update({'config': {'event_log_keep': 1}, 'event_log': [1, 2]})
            Path(path).write_text(json.dumps(state), encoding='utf-8')
            archive = Path(path + '.log.jsonl')
            archive.write_bytes(b'previous history\n')
            before = (Path(path).read_bytes(), archive.read_bytes())
            with patch.object(state_schema.os, 'link', side_effect=OSError('hardlinks unsupported')):
                with self.assertRaisesRegex(OSError, 'hardlinks unsupported'):
                    state_schema.transact_state(lambda current: None, path)
            self.assertEqual((Path(path).read_bytes(), archive.read_bytes()), before)
            self.assertFalse(Path(path + '.archive-pending').exists())

    def test_interrupted_journal_publication_is_not_visible(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = str(Path(directory) / 'state.json')
            state = state_schema.new_game()
            state.update({'config': {'event_log_keep': 1}, 'event_log': [1, 2]})
            Path(path).write_text(json.dumps(state), encoding='utf-8')
            code = r'''
import os, sys, json
import state_schema as s
path = sys.argv[1]
dump = json.dump
def interrupted(obj, handle, *args, **kwargs):
    if isinstance(obj, dict) and 'state_before' in obj:
        handle.write('{"partial":')
        handle.flush()
        os.fsync(handle.fileno())
        os._exit(42)
    return dump(obj, handle, *args, **kwargs)
json.dump = interrupted
s.transact_state(lambda state: None, path)
'''
            child = subprocess.run([sys.executable, '-B', '-c', code, path], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(child.returncode, 42, child.stderr)
            self.assertFalse(Path(path + '.archive-pending').exists())
            state_schema.transact_state(lambda state: None, path)
            self.assertEqual(Path(path + '.log.jsonl').read_text(encoding='utf-8').splitlines(), ['1'])

    def test_pending_publication_never_overwrites_racing_record(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = str(Path(directory) / 'state.json')
            state = state_schema.new_game()
            state.update({'config': {'event_log_keep': 1}, 'event_log': [1, 2]})
            Path(path).write_text(json.dumps(state), encoding='utf-8')
            pending = Path(path + '.archive-pending')
            link = os.link
            def race(src, dst):
                pending.write_bytes(b'other transaction')
                return link(src, dst)
            with patch.object(state_schema.os, 'link', side_effect=race):
                with self.assertRaises(FileExistsError):
                    state_schema.transact_state(lambda current: None, path)
            self.assertEqual(pending.read_bytes(), b'other transaction')
            self.assertFalse(Path(path + '.log.jsonl').exists())

    def test_corrupt_pending_blocks_without_changes(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = str(Path(directory) / 'state.json')
            state = state_schema.new_game()
            Path(path).write_text(json.dumps(state), encoding='utf-8')
            archive = Path(path + '.log.jsonl')
            archive.write_bytes(b'original history\n')
            pending = Path(path + '.archive-pending')
            pending.write_bytes(b'{incomplete')
            before = {item: item.read_bytes() for item in (Path(path), archive, pending)}
            with self.assertRaisesRegex(RuntimeError, '人工'):
                state_schema.save_state(state, path)
            self.assertEqual({item: item.read_bytes() for item in before}, before)

    def test_current_process_exception_preserves_unverified_archive(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = str(Path(directory) / 'state.json')
            state = state_schema.new_game()
            state.update({'config': {'event_log_keep': 1}, 'event_log': [1, 2]})
            Path(path).write_text(json.dumps(state), encoding='utf-8')
            archive = Path(path + '.log.jsonl')
            archive.write_bytes(b'prior history\n')
            real_append = state_schema._append_archive
            def interrupted(target, entries):
                real_append(target, entries)
                with open(target, 'ab') as handle:
                    handle.write(b'external history\n')
                raise OSError('interrupted')
            with patch.object(state_schema, '_append_archive', side_effect=interrupted):
                with self.assertRaises(OSError):
                    state_schema.transact_state(lambda current: None, path)
            before = archive.read_bytes()
            self.assertTrue(before.startswith(b'prior history\n'))
            self.assertTrue(before.endswith(b'external history\n'))
            with self.assertRaisesRegex(RuntimeError, '人工'):
                state_schema.transact_state(lambda current: None, path)
            self.assertEqual(archive.read_bytes(), before)

    def test_forged_legacy_record_cannot_delete_history(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = str(Path(directory) / 'state.json')
            Path(path).write_text(json.dumps(state_schema.new_game()), encoding='utf-8')
            archive = Path(path + '.log.jsonl')
            archive.write_text('{"type":"history"}\n', encoding='utf-8')
            contents = archive.read_bytes()
            record = {'generation': 0, 'existed': False, 'before': '', 'after': contents.hex(),
                      'state_before': hashlib.sha256(Path(path).read_bytes()).hexdigest(), 'state_after': '0' * 64}
            Path(path + '.archive-pending').write_text(json.dumps(record), encoding='utf-8')
            with self.assertRaises(Exception):
                state_schema.transact_state(lambda state: None, path)
            self.assertEqual(archive.read_bytes(), contents)

    def test_cleanup_failure_does_not_report_committed_operation_failed(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = str(Path(directory) / 'state.json')
            state = state_schema.new_game()
            state.update({'config': {'event_log_keep': 1}, 'event_log': [1, 2]})
            Path(path).write_text(json.dumps(state), encoding='utf-8')
            unlink = os.unlink
            def fail_journal(target, *args, **kwargs):
                if os.fspath(target) == path + '.archive-pending':
                    raise PermissionError('cleanup denied')
                return unlink(target, *args, **kwargs)
            with patch.object(state_schema.os, 'unlink', side_effect=fail_journal):
                result = state_schema.transact_state(lambda current: current.update(tick=1), path)
            self.assertEqual(result['tick'], 1)
            with self.assertRaises(RuntimeError):
                state_schema.load_state(path)
            self.assertEqual(json.loads(Path(path).read_text(encoding='utf-8'))['tick'], 1)
            with self.assertRaisesRegex(RuntimeError, '人工'):
                state_schema.transact_state(lambda current: current.update(tick=2), path)
            with self.assertRaises(RuntimeError):
                state_schema.load_state(path)
            self.assertEqual(json.loads(Path(path).read_text(encoding='utf-8'))['tick'], 1)
            self.assertEqual(Path(path + '.log.jsonl').read_text(encoding='utf-8').splitlines(), ['1'])

    def test_save_does_not_read_existing_archive(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = str(Path(directory) / 'state.json')
            archive = Path(path + '.log.jsonl')
            archive.write_bytes(b'old history\n')
            state = state_schema.new_game()
            state.update({'config': {'event_log_keep': 1}, 'event_log': [1, 2]})
            original = state_schema._read_bytes
            def checked(target):
                if os.fspath(target) == str(archive):
                    raise AssertionError('read existing archive')
                return original(target)
            with patch.object(state_schema, '_read_bytes', side_effect=checked):
                state_schema.save_state(state, path)
            self.assertTrue(archive.read_bytes().startswith(b'old history\n'))

    def test_journal_size_does_not_scale_with_existing_history(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = str(Path(directory) / 'state.json')
            state = state_schema.new_game()
            state.update({'config': {'event_log_keep': 1}, 'event_log': [1, 2]})
            Path(path).write_text(json.dumps(state), encoding='utf-8')
            Path(path + '.log.jsonl').write_bytes(b'{"history":"' + b'x' * 1048576 + b'"}\n')
            child = subprocess.run([sys.executable, '-B', '-c', CHILD, path], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(child.returncode, 42, child.stderr)
            self.assertLess(Path(path + '.archive-pending').stat().st_size, 4096)

    def test_unknown_archive_tail_is_not_deleted(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = str(Path(directory) / 'state.json')
            state = state_schema.new_game()
            state.update({'config': {'event_log_keep': 1}, 'event_log': [1, 2]})
            Path(path).write_text(json.dumps(state), encoding='utf-8')
            child = subprocess.run([sys.executable, '-B', '-c', CHILD, path], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(child.returncode, 42, child.stderr)
            archive = Path(path + '.log.jsonl')
            with archive.open('ab') as handle:
                handle.write(b'{"type":"external history"}\n')
            before = archive.read_bytes()
            with self.assertRaisesRegex(RuntimeError, '人工'):
                state_schema.transact_state(lambda state: None, path)
            self.assertEqual(archive.read_bytes(), before)

    def test_committed_state_survives_crash_before_journal_cleanup(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = str(Path(directory) / 'state.json')
            state = state_schema.new_game()
            state.update({'config': {'event_log_keep': 1}, 'event_log': [1, 2]})
            Path(path).write_text(json.dumps(state), encoding='utf-8')
            child_code = r'''
import os, sys
import state_schema as s
path = sys.argv[1]
replace = os.replace
def crash(src, dst):
    replace(src, dst)
    if os.path.abspath(dst) == os.path.abspath(path):
        os._exit(42)
os.replace = crash
s.transact_state(lambda state: None, path)
'''
            child = subprocess.run([sys.executable, '-B', '-c', child_code, path], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(child.returncode, 42, child.stderr)
            before = Path(path + '.log.jsonl').read_bytes()
            with self.assertRaisesRegex(RuntimeError, '人工'):
                state_schema.transact_state(lambda state: None, path)
            self.assertEqual(Path(path + '.log.jsonl').read_bytes(), before)
            with self.assertRaises(RuntimeError):
                state_schema.load_state(path)
            self.assertEqual(json.loads(Path(path).read_text(encoding='utf-8'))['archived_events'], 1)


if __name__ == '__main__':
    unittest.main()
