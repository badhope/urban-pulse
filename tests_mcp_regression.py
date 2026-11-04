import builtins
import importlib.util
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("audit_test_helpers", ROOT / "scripts" / "verify_audit_fix.py")
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)
helpers._install_mcp_stubs()
spec = importlib.util.spec_from_file_location("mcp_regression_server", ROOT / "mcp_server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
from game_engine import state_schema


class McpRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.path = os.path.join(self.temp.name, "state.json")
        self.state = state_schema.new_game()
        self.state.update({"tick": 1, "config": {"prose_keep": 1, "event_log_keep": 200},
                           "prose": [{"tick": 0, "location": "", "text": "old prose"}],
                           "lore": [{"comment": "lamp", "keys": ["lamp"], "content": "light", "cooldown": 3}]})
        state_schema.save_state(self.state, self.path)
        self.old_path = server._active["path"]
        server._active["path"] = self.path

    def tearDown(self):
        server._active["path"] = self.old_path
        self.temp.cleanup()

    def load(self):
        return state_schema.load_state(self.path)

    def test_lore_preview_does_not_mutate_state_or_consume_cooldown(self):
        before = Path(self.path).read_bytes()
        first = server.lore_lookup("lamp")
        second = server.lore_lookup("lamp")
        self.assertEqual([item["comment"] for item in first["matched"]], ["lamp"])
        self.assertEqual(first, second)
        self.assertEqual(Path(self.path).read_bytes(), before)
        self.assertNotIn("lore_runtime", self.load())
        self.assertFalse(os.path.exists(self.path + ".viz.jsonl"))

    def test_lore_preview_respects_existing_cooldown(self):
        state = self.load()
        server.lore_engine.trigger(state, state["lore"], ["lamp"], tick=1)
        state["tick"] = 2
        state_schema.save_state(state, self.path)
        before = Path(self.path).read_bytes()
        result = server.lore_lookup("lamp")
        self.assertEqual(result["matched"], [])
        self.assertEqual(result["skipped"][0]["why"], "cooldown")
        self.assertEqual(Path(self.path).read_bytes(), before)

    def test_archive_failure_preserves_preexisting_prose(self):
        before = Path(self.path).read_bytes()
        real_open = builtins.open
        real_os_open = os.open

        def failing_open(path, *args, **kwargs):
            if os.fspath(path) == self.path + ".log.jsonl":
                raise OSError("archive failed")
            return real_open(path, *args, **kwargs)

        def failing_os_open(path, *args, **kwargs):
            if os.fspath(path) == self.path + ".log.jsonl":
                raise OSError("archive failed")
            return real_os_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=failing_open), patch.object(os, "open", side_effect=failing_os_open):
            with self.assertRaises(Exception):
                server.publish_prose("new prose")
        self.assertEqual(Path(self.path).read_bytes(), before)
        self.assertEqual(self.load()["prose"][0]["text"], "old prose")

    def assert_pending_blocks_retry(self):
        pending = Path(self.path + ".archive-pending")
        self.assertTrue(pending.is_file())
        before = {p.relative_to(self.temp.name): p.read_bytes()
                  for p in Path(self.temp.name).rglob("*") if p.is_file()}
        with self.assertRaisesRegex(RuntimeError, "人工"):
            server.publish_prose("new prose")
        after = {p.relative_to(self.temp.name): p.read_bytes()
                 for p in Path(self.temp.name).rglob("*") if p.is_file()}
        self.assertEqual(after, before)

    def test_archive_append_failure_preserves_partial_and_complete_writes(self):
        archive = Path(self.path + ".log.jsonl")
        original_append = state_schema._append_archive
        for complete in (False, True):
            with self.subTest(complete=complete), tempfile.TemporaryDirectory(dir=ROOT) as directory:
                old_temp, old_path = self.temp, self.path
                self.temp = types.SimpleNamespace(name=directory)
                self.path = str(Path(directory) / "state.json")
                server._active["path"] = self.path
                try:
                    state_schema.save_state(self.state, self.path)
                    archive = Path(self.path + ".log.jsonl")
                    archive.write_bytes(b'{"type":"existing"}\n')
                    before_archive = archive.read_bytes()
                    before_state = Path(self.path).read_bytes()
                    written = []

                    def failing_append(path, entries):
                        payload = "".join(json.dumps(entry, ensure_ascii=False, allow_nan=False) + "\n"
                                          for entry in entries).replace("\n", os.linesep).encode("utf-8")
                        self.assertGreater(len(payload), 1)
                        if complete:
                            original_append(path, entries)
                            written.append(payload)
                        else:
                            written.append(payload[:len(payload) // 2])
                            with open(path, "ab") as handle:
                                handle.write(written[-1])
                        raise OSError("archive append failed")

                    with patch.object(state_schema, "_append_archive", side_effect=failing_append):
                        with self.assertRaisesRegex(RuntimeError, "archive append failed"):
                            server.publish_prose("new prose")
                    self.assertEqual(len(written), 1)
                    self.assertEqual(archive.read_bytes(), before_archive + written[0])
                    self.assertEqual(Path(self.path).read_bytes(), before_state)
                    self.assert_pending_blocks_retry()
                finally:
                    self.temp, self.path = old_temp, old_path
                    server._active["path"] = self.path

    def test_prose_archived_when_event_archiving_disabled(self):
        state = self.load()
        state["config"]["archive"] = False
        state_schema.save_state(state, self.path)
        server.publish_prose("new prose")
        entries = [json.loads(line) for line in Path(self.path + ".log.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(entries[0]["text"], "old prose")
        self.assertEqual(self.load()["archived_events"], 1)

    def test_generation_archive_and_event_overflow_are_combined(self):
        state = self.load()
        state["archive_generation"] = 2
        state["config"]["event_log_keep"] = 1
        state["event_log"] = [{"type": "prior", "text": "earlier event"}]
        state_schema.save_state(state, self.path)
        result = server.publish_prose("new prose")
        self.assertEqual(result["prose_count"], 1)
        archive = Path(self.path + ".log.2.jsonl")
        entries = [json.loads(line) for line in archive.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([entry["type"] for entry in entries], ["prior", "prose"])
        self.assertEqual(entries[1]["text"], "old prose")
        self.assertEqual(self.load()["archived_events"], 2)
        self.assertFalse(Path(self.path + ".log.jsonl").exists())

    def test_state_replace_failure_preserves_appended_archive(self):
        archive = Path(self.path + ".log.jsonl")
        archive.write_text('{"type":"existing"}\n', encoding="utf-8")
        before_archive = archive.read_bytes()
        before_state = Path(self.path).read_bytes()
        original_replace = state_schema.os.replace
        original_append = state_schema._append_archive
        written = []

        def capture_append(path, entries):
            original_append(path, entries)
            written.append("".join(json.dumps(entry, ensure_ascii=False, allow_nan=False) + "\n"
                                   for entry in entries).replace("\n", os.linesep).encode("utf-8"))

        def fail_state_replace(src, dst):
            if os.path.abspath(dst) == os.path.abspath(self.path):
                raise OSError("replace failed")
            return original_replace(src, dst)

        with patch.object(state_schema, "_append_archive", side_effect=capture_append), \
                patch.object(state_schema.os, "replace", side_effect=fail_state_replace):
            with self.assertRaisesRegex(RuntimeError, "replace failed"):
                server.publish_prose("new prose")
        self.assertEqual(Path(self.path).read_bytes(), before_state)
        self.assertEqual(len(written), 1)
        self.assertTrue(written[0])
        self.assertEqual(archive.read_bytes(), before_archive + written[0])
        self.assert_pending_blocks_retry()


if __name__ == "__main__":
    unittest.main()
