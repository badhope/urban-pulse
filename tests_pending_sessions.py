import contextlib
import importlib.util
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('pending_helpers', ROOT / 'scripts' / 'verify_audit_fix.py')
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)
helpers._install_mcp_stubs()
spec = importlib.util.spec_from_file_location('pending_server', ROOT / 'mcp_server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
from game_engine import sessions, state_schema


class PendingSessions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.root = Path(self.temp.name) / 'saves'
        self.root.mkdir()
        self.src = self.root / 'one.save.json'
        state_schema.save_state(state_schema.new_game(), str(self.src))
        self.env = patch.dict(os.environ, {'WORLD_GAMES_SAVES': str(self.root),
                                           'WORLD_GAMES_STATE_ROOT': str(self.root)})
        self.env.start()
        self.active = server._active['path']
        server._active['path'] = str(self.src)

    def tearDown(self):
        server._active['path'] = self.active
        self.env.stop()
        self.temp.cleanup()

    def pending(self, path):
        Path(str(path) + '.archive-pending').write_bytes(b'pending evidence')
        Path(str(path) + '.log.jsonl').write_bytes(b'archive evidence')

    def test_archive_rejects_pending_source_and_target(self):
        for pending_target in (False, True):
            with self.subTest(target=pending_target):
                dst = self.root / '.trash' / self.src.name
                dst.parent.mkdir(exist_ok=True)
                pending = dst if pending_target else self.src
                self.pending(pending)
                before = self.src.read_bytes()
                with self.assertRaises((RuntimeError, ValueError)):
                    sessions.archive(str(self.root), str(self.src))
                self.assertEqual(self.src.read_bytes(), before)
                self.assertEqual(Path(str(pending) + '.log.jsonl').read_bytes(), b'archive evidence')
                Path(str(pending) + '.archive-pending').unlink()
                Path(str(pending) + '.log.jsonl').unlink()

    def test_manage_archive_preserves_active(self):
        self.pending(self.src)
        with self.assertRaises((RuntimeError, ValueError)):
            server.session_manage('archive', 'one')
        self.assertEqual(server._active['path'], str(self.src))
        self.assertTrue(self.src.exists())

    def test_restore_and_purge_reject_pending(self):
        result = sessions.archive(str(self.root), str(self.src))
        trash = Path(result['archived'])
        self.pending(trash)
        for operation in (lambda: sessions.restore_from_trash(str(self.root), 'one'),
                          lambda: sessions.purge_trash(str(self.root), 'one')):
            with self.assertRaises((RuntimeError, ValueError)):
                operation()
            self.assertTrue(trash.exists())
            self.assertEqual(Path(str(trash) + '.log.jsonl').read_bytes(), b'archive evidence')

    def test_restore_rejects_pending_destination(self):
        sessions.archive(str(self.root), str(self.src))
        self.pending(self.src)
        with self.assertRaises((RuntimeError, ValueError)):
            sessions.restore_from_trash(str(self.root), 'one')
        self.assertTrue((self.root / '.trash' / self.src.name).exists())

    def test_import_respects_fixture_root(self):
        outside = Path(self.temp.name) / 'outside.save.json'
        state_schema.save_state(state_schema.new_game(), str(outside))
        with self.assertRaisesRegex(RuntimeError, '路径不在允许根目录内'):
            server.session_import(str(outside), 'outside')
        result = server.session_import(str(self.src), 'two')
        self.assertEqual(Path(result['state_path']), self.root / 'two.save.json')
        self.assertTrue((self.root / 'two.save.json').is_file())

    def test_import_rejects_pending_source(self):
        self.pending(self.src)
        with self.assertRaisesRegex(RuntimeError, '存在未处理的归档记录'):
            server.session_import(str(self.src), 'two')
        self.assertFalse((self.root / 'two.save.json').exists())
        self.assertEqual(Path(str(self.src) + '.log.jsonl').read_bytes(), b'archive evidence')

    def test_import_rejects_pending_destination(self):
        dst = self.root / 'two.save.json'
        self.pending(dst)
        with self.assertRaises((RuntimeError, ValueError)):
            server.session_import(str(self.src), 'two', overwrite=True)
        self.assertFalse(dst.exists())
        self.assertEqual(Path(str(dst) + '.archive-pending').read_bytes(), b'pending evidence')

    def test_archive_waits_for_source_lock_before_check(self):
        entered = threading.Event()
        done = threading.Event()
        errors = []
        def worker():
            entered.set()
            try:
                sessions.archive(str(self.root), str(self.src))
            except Exception as exc:
                errors.append(exc)
            finally:
                done.set()
        with state_schema.state_lock(str(self.src)):
            thread = threading.Thread(target=worker)
            thread.start()
            self.assertTrue(entered.wait(2))
            self.assertFalse(done.wait(0.15))
            self.pending(self.src)
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertTrue(self.src.exists())

    def test_import_waits_for_source_lock_before_read(self):
        entered = threading.Event()
        done = threading.Event()
        errors = []
        locked_states = server.session_store.locked_states
        @contextlib.contextmanager
        def observed_lock(*paths):
            entered.set()
            with locked_states(*paths):
                yield
        def worker():
            try:
                server.session_import(str(self.src), 'two')
            except Exception as exc:
                errors.append(exc)
            finally:
                done.set()
        with patch.object(server.session_store, 'locked_states', observed_lock):
            thread = threading.Thread(target=worker)
            try:
                with state_schema.state_lock(str(self.src)):
                    thread.start()
                    self.assertTrue(entered.wait(2), f'import never reached locks; errors={errors!r}')
                    self.assertFalse(done.wait(0.15), f'import finished before source lock released; errors={errors!r}')
                    self.pending(self.src)
            finally:
                if thread.ident is not None:
                    thread.join(3)
        self.assertFalse(thread.is_alive(), f'import thread did not finish; errors={errors!r}')
        self.assertEqual(len(errors), 1, f'import errors={errors!r}')
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertIn('存在未处理的归档记录', str(errors[0]))
        self.assertFalse((self.root / 'two.save.json').exists())

    def test_archive_existing_trash_uses_non_overwriting_suffix(self):
        trash = self.root / '.trash'
        trash.mkdir()
        (trash / self.src.name).write_bytes(b'existing save')
        result = sessions.archive(str(self.root), str(self.src))
        self.assertEqual((trash / self.src.name).read_bytes(), b'existing save')
        self.assertTrue(Path(result['archived']).is_file())

    def test_snapshots_reject_pending_source_destination_and_rotation(self):
        dst = self.root / 'one.000000.snap.json'
        old = self.root / 'one.000001.snap.json'
        for which in ('source', 'destination', 'rotation'):
            with self.subTest(which=which):
                path = {'source': self.src, 'destination': dst, 'rotation': old}[which]
                if which == 'rotation':
                    old.write_bytes(b'old snapshot')
                self.pending(path)
                with patch.object(sessions, 'KEEP_SNAPSHOTS', 1 if which == 'rotation' else 20):
                    with self.assertRaises((RuntimeError, ValueError)):
                        sessions.snapshot(str(self.src))
                self.assertFalse(dst.exists())
                if which == 'rotation':
                    self.assertEqual(old.read_bytes(), b'old snapshot')
                    old.unlink()
                Path(str(path) + '.archive-pending').unlink()
                Path(str(path) + '.log.jsonl').unlink()

    def test_mcp_snapshot_rejects_pending_destination(self):
        dst = Path(str(self.src) + '.snap.tag')
        self.pending(dst)
        with self.assertRaises((RuntimeError, ValueError)):
            server.snapshot('tag')
        self.assertFalse(dst.exists())

    def test_long_running_save_archive_restore_and_purge_sidecars(self):
        state = state_schema.load_state(str(self.src))
        state['tick'] = 4
        state_schema.save_state(state, str(self.src))
        suffixes = ('.log.jsonl', '.log.2.jsonl', '.viz.jsonl')
        for suffix in suffixes:
            Path(str(self.src) + suffix).write_bytes(suffix.encode())
        source = {suffix: Path(str(self.src) + suffix).read_bytes()
                  for suffix in ('.bak',) + suffixes}
        dst = Path(sessions.archive(str(self.root), str(self.src))['archived'])
        for suffix, contents in source.items():
            self.assertFalse(Path(str(self.src) + suffix).exists())
            self.assertEqual(Path(str(dst) + suffix).read_bytes(), contents)
        sessions.restore_from_trash(str(self.root), 'one')
        for suffix, contents in source.items():
            self.assertEqual(Path(str(self.src) + suffix).read_bytes(), contents)
        dst = Path(sessions.archive(str(self.root), str(self.src))['archived'])
        sessions.purge_trash(str(self.root), 'one')
        self.assertFalse(dst.exists())
        for suffix in source:
            self.assertFalse(Path(str(dst) + suffix).exists())

    def test_interrupted_archive_preserves_main_and_sidecar_data(self):
        contents = self.src.read_bytes()
        sidecar = Path(str(self.src) + '.log.jsonl')
        sidecar.write_bytes(b'archive history')
        real_link = sessions.os.link
        calls = []
        def fail_after_first(src, dst, *args, **kwargs):
            if calls:
                raise OSError('injected move failure')
            calls.append((src, dst))
            return real_link(src, dst, *args, **kwargs)
        with patch.object(sessions.os, 'link', side_effect=fail_after_first):
            with self.assertRaises((RuntimeError, OSError)):
                sessions.archive(str(self.root), str(self.src))
        self.assertTrue(calls, 'failure injection must reach the first move')
        paths = list(self.root.rglob('*'))
        self.assertTrue(any(p.is_file() and p.read_bytes() == contents for p in paths))
        self.assertTrue(any(p.is_file() and p.read_bytes() == b'archive history' for p in paths))

    def test_process_exit_after_first_archive_move_preserves_evidence(self):
        original = self.src.read_bytes()
        sidecar = Path(str(self.src) + '.log.jsonl')
        sidecar.write_bytes(b'process exit history')
        code = ("import os, sys; import scripts.verify_audit_fix; from game_engine import sessions; "
                "unlink = sessions.os.unlink; "
                "def_exit = lambda path: (unlink(path), os._exit(91)); "
                "sessions.os.unlink = def_exit; sessions.archive(sys.argv[1], sys.argv[2])")
        proc = subprocess.run([sys.executable, '-B', '-c', code, str(self.root), str(self.src)],
                              cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 91, proc.stderr)
        files = [p for p in self.root.rglob('*') if p.is_file()]
        self.assertTrue(any(p.read_bytes() == original for p in files))
        self.assertTrue(any(p.read_bytes() == b'process exit history' for p in files))
        self.assertTrue(any(p.name.endswith('.archive-pending') for p in files))

    def test_process_exit_during_restore_preserves_evidence(self):
        Path(str(self.src) + '.log.jsonl').write_bytes(b'restore history')
        original = self.src.read_bytes()
        sessions.archive(str(self.root), str(self.src))
        code = ("import os, sys; import scripts.verify_audit_fix; from game_engine import sessions; "
                "unlink = sessions.os.unlink; "
                "def_exit = lambda path: (unlink(path), os._exit(92)); "
                "sessions.os.unlink = def_exit; sessions.restore_from_trash(sys.argv[1], 'one')")
        proc = subprocess.run([sys.executable, '-B', '-c', code, str(self.root)],
                              cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 92, proc.stderr)
        files = [p for p in self.root.rglob('*') if p.is_file()]
        self.assertTrue(any(p.read_bytes() == original for p in files))
        self.assertTrue(any(p.read_bytes() == b'restore history' for p in files))
        self.assertTrue(Path(str(self.src) + '.archive-pending').exists())
        self.assertTrue(Path(str(self.root / '.trash' / self.src.name) + '.archive-pending').exists())

    def test_archive_rejects_sidecar_collision_without_overwriting(self):
        dst = self.root / '.trash' / self.src.name
        dst.parent.mkdir()
        Path(str(self.src) + '.log.jsonl').write_bytes(b'source')
        Path(str(dst) + '.log.jsonl').write_bytes(b'destination')
        with self.assertRaises((RuntimeError, ValueError, OSError)):
            sessions.archive(str(self.root), str(self.src))
        self.assertTrue(self.src.exists())
        self.assertEqual(Path(str(dst) + '.log.jsonl').read_bytes(), b'destination')

    def test_unsupported_link_fails_closed_with_pending(self):
        sidecar = Path(str(self.src) + '.log.jsonl')
        sidecar.write_bytes(b'history')
        original = self.src.read_bytes()
        with patch.object(sessions.os, 'link', side_effect=OSError('unsupported')):
            with self.assertRaises(OSError):
                sessions.archive(str(self.root), str(self.src))
        self.assertEqual(self.src.read_bytes(), original)
        self.assertEqual(sidecar.read_bytes(), b'history')
        self.assertTrue(Path(str(self.src) + '.archive-pending').exists())

    def test_purge_failure_reports_partial_results_and_preserves_pending(self):
        dst = Path(sessions.archive(str(self.root), str(self.src))['archived'])
        sidecar = Path(str(dst) + '.log.jsonl')
        sidecar.write_bytes(b'history')
        real_unlink = sessions.os.unlink
        def fail_main(path):
            if os.path.normcase(str(path)) == os.path.normcase(str(dst)):
                raise OSError('injected')
            return real_unlink(path)
        with patch.object(sessions.os, 'unlink', side_effect=fail_main):
            result = sessions.purge_trash(str(self.root), 'one')
        self.assertEqual(result['count'], 0)
        self.assertTrue(result['irreversible'])
        self.assertEqual([item['removed'] for item in result['files']], [True, False])
        self.assertTrue(dst.exists())
        self.assertTrue(Path(str(dst) + '.archive-pending').exists())

    def test_concurrent_inbox_writer_waits_and_cannot_recreate(self):
        code = ("import sys; import scripts.verify_audit_fix; from game_engine import panel; "
                "print('ready', flush=True); panel.inbox_append(sys.argv[1], 'late')")
        with state_schema.state_lock(str(self.src)):
            proc = subprocess.Popen([sys.executable, '-u', '-B', '-c', code, str(self.src)],
                                    cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(proc.stdout.readline().strip(), 'ready')
            self.assertIsNone(proc.poll())
            sessions.archive(str(self.root), str(self.src))
        stdout, stderr = proc.communicate(timeout=5)
        self.assertNotEqual(proc.returncode, 0, stdout + stderr)
        self.assertIn('FileNotFoundError', stderr)
        self.assertFalse(Path(str(self.src) + '.inbox.jsonl').exists())

    def test_archived_sidecar_writers_cannot_recreate(self):
        from game_engine import panel, viz_series
        state = state_schema.load_state(str(self.src))
        sessions.archive(str(self.root), str(self.src))
        with self.assertRaises(FileNotFoundError):
            panel.inbox_append(str(self.src), 'late action')
        viz_series.record_sample(str(self.src), state)
        self.assertFalse(Path(str(self.src) + '.inbox.jsonl').exists())
        self.assertFalse(Path(str(self.src) + '.viz.jsonl').exists())

    def test_sidecars_and_snapshots_roundtrip(self):
        snap = self.root / 'one.000000.snap.json'
        snap.write_bytes(b'snapshot')
        snap_log = Path(str(snap) + '.log.2.jsonl')
        snap_log.write_bytes(b'snapshot history')
        for suffix in ('.inbox.jsonl', '.viz.jsonl', '.snap.label', '.snap.测试'):
            Path(str(self.src) + suffix).write_bytes(suffix.encode())
        dst = Path(sessions.archive(str(self.root), str(self.src))['archived'])
        self.assertEqual((dst.parent / snap.name).read_bytes(), b'snapshot')
        sessions.restore_from_trash(str(self.root), 'one')
        self.assertEqual(snap.read_bytes(), b'snapshot')
        self.assertEqual(snap_log.read_bytes(), b'snapshot history')
        for suffix in ('.inbox.jsonl', '.viz.jsonl', '.snap.label', '.snap.测试'):
            self.assertEqual(Path(str(self.src) + suffix).read_bytes(), suffix.encode())

    def test_archived_active_transaction_in_another_process_cannot_recreate(self):
        sessions.archive(str(self.root), str(self.src))
        code = "import sys, state_schema as s; s.transact_state(lambda state: state.update(tick=99), sys.argv[1])"
        result = subprocess.run([sys.executable, '-c', code, str(self.src)], cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.src.exists())

    def test_concurrent_process_waits_for_archive_and_cannot_recreate(self):
        code = ("import sys, state_schema as s; "
                "print('ready', flush=True); "
                "s.transact_state(lambda state: state.update(tick=99), sys.argv[1])")
        with state_schema.state_lock(str(self.src)):
            proc = subprocess.Popen([sys.executable, '-u', '-c', code, str(self.src)],
                                    cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(proc.stdout.readline().strip(), 'ready')
            self.assertIsNone(proc.poll())
            sessions.archive(str(self.root), str(self.src))
        stdout, stderr = proc.communicate(timeout=5)
        self.assertNotEqual(proc.returncode, 0, stdout + stderr)
        self.assertIn('FileNotFoundError', stderr)
        self.assertFalse(self.src.exists())

    def test_missing_transaction_requires_explicit_creation(self):
        self.src.unlink()
        with self.assertRaises((FileNotFoundError, ValueError)):
            state_schema.transact_state(lambda state: None, str(self.src))
        self.assertFalse(self.src.exists())
        state_schema.transact_state(lambda state: None, str(self.src), allow_create=True)
        self.assertTrue(self.src.exists())

    def test_windows_case_alias_reentrant_lock(self):
        if os.name != 'nt':
            self.skipTest('requires Windows case-insensitive filesystem')
        with state_schema.state_lock(str(self.src), timeout=0.2):
            with state_schema.state_lock(str(self.src).upper(), timeout=0.2):
                self.assertTrue(self.src.exists())

    def test_long_collision_name_purge_only_selected_archive(self):
        name = 'x' * 48
        src = self.root / (name + '.save.json')
        state_schema.save_state(state_schema.new_game(), str(src))
        trash = self.root / '.trash'
        trash.mkdir()
        old = trash / src.name
        old.write_bytes(b'old archive')
        archived = Path(sessions.archive(str(self.root), str(src))['archived'])
        selected = archived.name[:-len('.save.json')]
        sessions.purge_trash(str(self.root), selected)
        self.assertEqual(old.read_bytes(), b'old archive')
        self.assertFalse(archived.exists())

    def test_legacy_long_trash_identifier_is_exact(self):
        name = 'z' * 48
        trash = self.root / '.trash'
        trash.mkdir()
        old = trash / (name + '.save.json')
        legacy = trash / (name + '-123456789.save.json')
        old.write_bytes(b'old')
        legacy.write_bytes(b'legacy')
        sessions.purge_trash(str(self.root), name + '-123456789')
        self.assertEqual(old.read_bytes(), b'old')
        self.assertFalse(legacy.exists())

    def test_crash_during_first_pending_blocks_both_endpoints(self):
        dst = self.root / '.trash' / self.src.name
        code = ("import os,sys; import scripts.verify_audit_fix; from game_engine import sessions; "
                "sync=os.fsync; os.fsync=lambda fd:(sync(fd),os._exit(93)); "
                "sessions.archive(sys.argv[1],sys.argv[2])")
        proc = subprocess.run([sys.executable, '-B', '-c', code, str(self.root), str(self.src)],
                              cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 93, proc.stderr)
        for path in (self.src, dst):
            with self.subTest(path=path):
                with self.assertRaises(RuntimeError):
                    state_schema.save_state(state_schema.new_game(), str(path))
        self.assertFalse(dst.exists())

    def test_restore_rejects_pending_snapshot(self):
        snap = Path(server.snapshot('source')['snapshot'])
        self.pending(snap)
        before = self.src.read_bytes()
        with self.assertRaises(RuntimeError):
            server.restore(str(snap))
        self.assertEqual(self.src.read_bytes(), before)

    def test_restore_waits_for_snapshot_lock(self):
        snap = Path(server.snapshot('source')['snapshot'])
        started, done = threading.Event(), threading.Event()
        errors = []
        def worker():
            started.set()
            try:
                server.restore(str(snap))
            except Exception as exc:
                errors.append(exc)
            finally:
                done.set()
        with state_schema.state_lock(str(snap)):
            thread = threading.Thread(target=worker)
            thread.start()
            self.assertTrue(started.wait(2))
            self.assertFalse(done.wait(0.2))
            self.pending(snap)
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)

    def test_pending_history_readers_fail_closed_after_process_exit(self):
        code = ("import os,sys; import state_schema as s; "
                "append=s._append_archive; "
                "s._append_archive=lambda path, entries:(append(path,entries),os._exit(44)); "
                "s.transact_state(lambda state: None,sys.argv[1],archive_entries=[{'desc':'uncommitted-secret'}])")
        proc = subprocess.run([sys.executable, '-B', '-c', code, str(self.src)],
                              cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 44, proc.stderr)
        with self.assertRaises(RuntimeError):
            server.recall('uncommitted-secret')
        with self.assertRaises(RuntimeError):
            state_schema.load_state(str(self.src))
        from game_engine import panel, viz_series, input_policy
        with self.assertRaises(RuntimeError):
            input_policy.load_state(str(self.src), root=str(self.root))
        with self.assertRaises(RuntimeError):
            panel.load_state_retry(str(self.src))
        with self.assertRaises(RuntimeError):
            panel.inbox_read_all(str(self.src))
        with self.assertRaises(RuntimeError):
            viz_series.load_series(str(self.src))
        handler = object.__new__(panel.Handler)
        handler._state = lambda: str(self.src)
        handler.path = '/history'
        with self.assertRaises(RuntimeError):
            handler._history_payload()
        row = next(r for r in sessions.list_saves(str(self.root)) if r['name'] == 'one')
        self.assertTrue(row.get('pending_review'))

    def test_shared_pending_blocks_state_read_and_marks_list(self):
        (self.root / '.ww-session-transaction-pending').write_text('{}', encoding='utf-8')
        with self.assertRaises(RuntimeError):
            state_schema.load_state(str(self.src))
        row = next(r for r in sessions.list_saves(str(self.root)) if r['name'] == 'one')
        self.assertTrue(row.get('pending_review'))

    def test_cross_process_guard_waits_for_other_transaction(self):
        other = self.root / 'other.save.json'
        state_schema.save_state(state_schema.new_game(), str(other))
        edit = ("import sys, state_schema as s\n"
                "def update(state):\n print('editing',flush=True); sys.stdin.readline(); state['tick']=7\n"
                "s.transact_state(update,sys.argv[1])\n")
        arch = ("import sys; import scripts.verify_audit_fix; from game_engine import sessions\n"
                "sessions.os.link=lambda *a,**k: (_ for _ in ()).throw(OSError('injected'))\n"
                "print('starting',flush=True)\n"
                "sessions.archive(sys.argv[1],sys.argv[2])\n")
        b = subprocess.Popen([sys.executable, '-u', '-B', '-c', edit, str(other)], cwd=ROOT,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        a = None
        try:
            self.assertEqual(b.stdout.readline().strip(), 'editing')
            a = subprocess.Popen([sys.executable, '-u', '-B', '-c', arch, str(self.root), str(self.src)],
                                 cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(a.stdout.readline().strip(), 'starting')
            try:
                a.wait(timeout=0.7)
            except subprocess.TimeoutExpired:
                pass
            self.assertIsNone(a.poll(), 'archive must wait for the in-flight transaction')
            self.assertFalse((self.root / '.ww-session-transaction-pending').exists())
        finally:
            b.stdin.write('\n')
            b.stdin.flush()
            b.communicate(timeout=15)
            if a is not None:
                a.communicate(timeout=15)
        self.assertEqual(b.returncode, 0)
        self.assertNotEqual(a.returncode, 0)
        self.assertTrue((self.root / '.ww-session-transaction-pending').exists())

    def test_cross_process_writer_waits_for_failed_guard_publication(self):
        other = self.root / 'other.save.json'
        state_schema.save_state(state_schema.new_game(), str(other))
        before = other.read_bytes()
        arch = ("import sys,os; import scripts.verify_audit_fix; from game_engine import sessions\n"
                "sync=os.fsync\n"
                "def stop(fd):\n sync(fd); print('guard',flush=True); sys.stdin.readline(); os._exit(94)\n"
                "os.fsync=stop\n"
                "sessions.archive(sys.argv[1],sys.argv[2])\n")
        edit = ("import sys,state_schema as s; print('starting',flush=True); "
                "s.transact_state(lambda state:state.update(tick=7),sys.argv[1])")
        a = subprocess.Popen([sys.executable, '-u', '-B', '-c', arch, str(self.root), str(self.src)],
                             cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        b = None
        try:
            self.assertEqual(a.stdout.readline().strip(), 'guard')
            b = subprocess.Popen([sys.executable, '-u', '-B', '-c', edit, str(other)], cwd=ROOT,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(b.stdout.readline().strip(), 'starting')
            try:
                b.wait(timeout=0.7)
            except subprocess.TimeoutExpired:
                pass
            self.assertIsNone(b.poll(), 'writer must wait for guard publisher')
        finally:
            a.stdin.write('\n')
            a.stdin.flush()
            a.communicate(timeout=15)
            if b is not None:
                stdout, stderr = b.communicate(timeout=15)
        self.assertEqual(a.returncode, 94)
        self.assertNotEqual(b.returncode, 0, stdout + stderr)
        self.assertIn('RuntimeError', stderr)
        self.assertEqual(other.read_bytes(), before)

    def test_process_snapshot_rotation_rejects_sidecar_pending(self):
        old = self.root / 'one.000000.snap.json'
        old.write_bytes(b'original snapshot')
        sidecar = Path(str(old) + '.log.jsonl')
        sidecar.write_bytes(b'snapshot history')
        pending = Path(str(sidecar) + '.archive-pending')
        pending.write_bytes(b'pending')
        state = state_schema.load_state(str(self.src))
        state['tick'] = 1
        state_schema.save_state(state, str(self.src))
        code = ("import sys; import scripts.verify_audit_fix; from game_engine import sessions; "
                "sessions.KEEP_SNAPSHOTS=1; sessions.snapshot(sys.argv[1])")
        proc = subprocess.run([sys.executable, '-B', '-c', code, str(self.src)], cwd=ROOT,
                              capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('RuntimeError', proc.stderr)
        self.assertEqual(old.read_bytes(), b'original snapshot')
        self.assertEqual(sidecar.read_bytes(), b'snapshot history')
        self.assertEqual(pending.read_bytes(), b'pending')
        self.assertFalse((self.root / 'one.000001.snap.json').exists())

    def test_mcp_snapshot_rejects_related_sidecar_pending(self):
        dst = Path(str(self.src) + '.snap.tag')
        dst.write_bytes(b'original snapshot')
        pending = Path(str(dst) + '.log.jsonl.archive-pending')
        pending.write_bytes(b'evidence')
        with self.assertRaises(RuntimeError):
            server.snapshot('tag')
        self.assertEqual(dst.read_bytes(), b'original snapshot')
        self.assertEqual(pending.read_bytes(), b'evidence')

    def test_viz_sample_rejects_own_pending(self):
        from game_engine import viz_series
        sidecar = Path(str(self.src) + '.viz.jsonl')
        sidecar.write_bytes(b'{"tick":0,"old":true}\n')
        pending = Path(str(sidecar) + '.archive-pending')
        pending.write_bytes(b'evidence')
        before = sidecar.read_bytes()
        state = state_schema.load_state(str(self.src))
        state['tick'] = 1
        with self.assertRaises(RuntimeError):
            viz_series.record_sample(str(self.src), state)
        with self.assertRaises(RuntimeError):
            viz_series.load_series(str(self.src))
        self.assertEqual(sidecar.read_bytes(), before)
        self.assertEqual(pending.read_bytes(), b'evidence')

    def test_snapshot_copy_failure_preserves_existing_snapshots(self):
        for mcp in (False, True):
            with self.subTest(mcp=mcp):
                dst = (Path(str(self.src) + '.snap.tag') if mcp
                       else self.root / 'one.000000.snap.json')
                dst.write_bytes(b'original snapshot')
                def fail_copy(src, target, *args, **kwargs):
                    Path(target).write_bytes(b'partial')
                    raise OSError('injected copy failure')
                with patch.object(sessions.shutil, 'copyfile', side_effect=fail_copy):
                    with self.assertRaises(Exception):
                        server.snapshot('tag') if mcp else sessions.snapshot(str(self.src))
                self.assertEqual(dst.read_bytes(), b'original snapshot')

    def test_process_exit_during_snapshot_copy_preserves_original(self):
        dst = self.root / 'one.000000.snap.json'
        dst.write_bytes(b'original snapshot')
        code = ("import os,sys; import scripts.verify_audit_fix; from game_engine import sessions\n"
                "def crash(src,dst):\n"
                " f=open(dst,'wb'); f.write(b'partial'); f.flush(); os._exit(95)\n"
                "sessions.shutil.copyfile=crash\n"
                "sessions.snapshot(sys.argv[1])\n")
        proc = subprocess.run([sys.executable, '-B', '-c', code, str(self.src)], cwd=ROOT,
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 95, proc.stderr)
        self.assertEqual(dst.read_bytes(), b'original snapshot')

    def test_snapshot_sync_and_replace_failure_preserve_existing(self):
        for failure in ('fsync', 'replace'):
            for mcp in (False, True):
                with self.subTest(failure=failure, mcp=mcp):
                    dst = (Path(str(self.src) + '.snap.tag') if mcp
                           else self.root / 'one.000000.snap.json')
                    dst.write_bytes(b'original snapshot')
                    with patch.object(sessions.os, failure, side_effect=OSError('injected')):
                        with self.assertRaises(Exception):
                            server.snapshot('tag') if mcp else sessions.snapshot(str(self.src))
                    self.assertEqual(dst.read_bytes(), b'original snapshot')
                    self.assertEqual(list(self.root.glob('.ww_snapshot_*.tmp')), [])

    def test_normal_archive_restore_and_purge(self):
        before = self.src.read_bytes()
        sessions.archive(str(self.root), str(self.src))
        sessions.restore_from_trash(str(self.root), 'one')
        self.assertEqual(self.src.read_bytes(), before)
        sessions.archive(str(self.root), str(self.src))
        self.assertEqual(sessions.purge_trash(str(self.root), 'one')['count'], 1)


if __name__ == '__main__':
    unittest.main()
