import ast
import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import engine
from game_engine.rules import playbook, questline


ROOT = Path(__file__).resolve().parent


class TurnRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.json"
        with (ROOT / "demo_state.json").open(encoding="utf-8") as source:
            self.state = json.load(source)

    def run_tick(self):
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "engine.py"), "tick", "--state", str(self.path)],
            capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        with self.path.open(encoding="utf-8") as saved:
            state = json.load(saved)
        return json.loads(result.stdout), state

    def write_state(self):
        self.path.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")

    def test_cli_advances_and_completes_quest_once(self):
        self.state["questlines"] = [questline.normalize({
            "id": "regression", "reward": {"gold": 7},
            "stages": [{"id": "start", "title": "Start", "exit_if": {"tick_gte": 1}}],
        })]
        self.state["quests"] = {}
        self.state["tick"] = 0
        initial_gold = self.state["entities"]["player"]["gold"]
        self.write_state()
        first, state = self.run_tick()
        self.assertEqual(state["quests"]["regression"]["stage"], "start")
        self.assertEqual(first["_tick"], 1)
        self.assertIn({"quest": "regression", "change": "stage", "stage": "start", "title": "Start"}, first["quest_changes"])
        self.assertTrue(any(e.get("type") == "quest" and e.get("stage") == "start" for e in state["event_log"]))
        second, state = self.run_tick()
        self.assertEqual(state["quests"]["regression"]["status"], "done")
        self.assertEqual(state["entities"]["player"]["gold"], initial_gold + 7)
        self.assertIn({"quest": "regression", "change": "done"}, second["quest_changes"])
        self.assertTrue(any(m.get("kind") == "事业线" and "regression" in m.get("desc", "") for m in state["milestones"]))
        _, state = self.run_tick()
        self.assertEqual(state["entities"]["player"]["gold"], initial_gold + 7)

    def test_cli_matches_mcp_tick_state_and_result(self):
        source = (ROOT / "mcp_server.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        tick = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "tick")
        tick.decorator_list = []
        namespace = {
            "_load": lambda: reference,
            "_seed_rng": engine.seed_rng,
            "tick_market": engine.tick_market,
            "evolve_world": engine.evolve_world,
            "log_event": engine.log_event,
            "quest_rules": questline,
            "playbook_rules": playbook,
            "_finish": lambda state, result: {**result, "_tick": state["tick"]},
        }
        config_node = next(node for node in tree.body if isinstance(node, ast.Assign)
                           and any(isinstance(target, ast.Name) and target.id == "DEFAULT_CONFIG" for target in node.targets))
        milestone_node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_milestone")
        cfg_node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_cfg")
        module = ast.fix_missing_locations(ast.Module(body=[config_node, cfg_node, milestone_node, tick], type_ignores=[]))
        exec(compile(module, str(ROOT / "mcp_server.py"), "exec"), namespace)
        self.state["questlines"] = [questline.normalize({"id": "parity", "reward": {"gold": 7},
            "stages": [{"id": "start", "title": "Start", "exit_if": {"tick_gte": 1}}]})]
        self.state["quests"] = {}
        self.state["tick"] = 0
        reference = copy.deepcopy(self.state)
        self.write_state()
        for _ in range(3):
            expected = namespace["tick"]()
            actual, saved = self.run_tick()
            self.assertEqual(saved, reference)
            self.assertEqual(actual, {"action": "tick", **expected})

    def test_tick_events_include_only_current_quest_events_at_both_entrypoints(self):
        spec = importlib.util.spec_from_file_location("turn_test_helpers", ROOT / "scripts" / "verify_audit_fix.py")
        helpers = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helpers)
        helpers._install_mcp_stubs()
        spec = importlib.util.spec_from_file_location("turn_test_mcp", ROOT / "mcp_server.py")
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        old_path = server._active["path"]
        self.addCleanup(server._active.__setitem__, "path", old_path)
        server._active["path"] = str(self.path)
        for count in (0, 1, 3):
            for entrypoint in ("cli", "mcp"):
                with self.subTest(count=count, entrypoint=entrypoint):
                    self.state["tick"] = 0
                    definitions = [
                        {"id": "stage", "stages": [{"id": "start", "title": "Start"}]},
                        {"id": "done", "stages": [{"id": "start", "title": "Done", "exit_if": {"tick_gte": 1}}]},
                        {"id": "failed", "fail_if": {"tick_gte": 1}, "stages": [{"id": "start"}]},
                    ][:count]
                    self.state["questlines"] = [questline.normalize(item) for item in definitions]
                    self.state["quests"] = {
                        item["id"]: {"status": "active", "stage": "start" if item["id"] == "done" else None,
                                     "done_stages": [], "entered_at": {}, "history": []}
                        for item in definitions
                    }
                    self.state["event_log"] = [{"tick": 0, "type": "quest", "desc": "old quest event"}]
                    self.write_state()
                    if entrypoint == "cli":
                        result, saved = self.run_tick()
                    else:
                        result = server.tick()
                        with self.path.open(encoding="utf-8") as saved_file:
                            saved = json.load(saved_file)
                    expected = []
                    for change in result["quest_changes"]:
                        if change["change"] == "stage":
                            expected.append("事业线「%s」推进到：%s" % (change["quest"], change["title"]))
                        elif change["change"] == "done":
                            expected.append("事业线「%s」完成" % change["quest"])
                        elif change["change"] == "failed":
                            expected.append("事业线「%s」失败（%s）" % (change["quest"], change["reason"]))
                    self.assertEqual(len(expected), count)
                    if count == 3:
                        self.assertTrue({"stage", "done", "failed"}.issubset(
                            {change["change"] for change in result["quest_changes"]}))
                    self.assertEqual([event for event in result["events"] if event.startswith("事业线「")], expected)
                    self.assertNotIn("old quest event", result["events"])
                    self.assertEqual([event["desc"] for event in saved["event_log"] if event.get("type") == "quest"],
                                     ["old quest event", *expected])

    def test_failure_none_never_fails_and_hp_still_fails(self):
        for hp in (0, -1):
            with self.subTest(hp=hp):
                state = {"entities": {"player": {"hp": hp, "hp_max": 10}}}
                none, _ = playbook.normalize({"failure": {"mode": "none"}})
                hp_mode, _ = playbook.normalize({"failure": {"mode": "hp"}})
                self.assertFalse(playbook.summary(state, none)["failure"]["failed"])
                self.assertEqual(playbook.summary(state, none)["failure"]["mode"], "none")
                self.assertTrue(playbook.summary(state, hp_mode)["failure"]["failed"])

    def test_old_save_without_questlines_or_playbook_ticks(self):
        self.state.pop("questlines", None)
        self.state.pop("quests", None)
        self.state.pop("playbook", None)
        tick = self.state["tick"]
        self.write_state()
        result, state = self.run_tick()
        self.assertEqual(state["tick"], tick + 1)
        self.assertEqual(state["quests"], {})
        self.assertEqual(result["quest_changes"], [])
        self.assertEqual(result["playbook"]["failure"]["mode"], "hp")


if __name__ == "__main__":
    unittest.main()
