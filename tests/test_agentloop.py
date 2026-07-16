import json
import tempfile
import unittest
from pathlib import Path

from xgen_creator.agentloop import run_goal_loop, _extract_object
from xgen_creator.pipeline.roles import ModelRoles
from xgen_creator.pipeline.watch import snapshot, changed_files
from xgen_creator.docgen.index_page import build_index


class StubSession:
    """브리지 덕 타입 — outline/step만 흉내."""

    def __init__(self):
        self.performed = []

    def outline(self, url=None, max_elements=45):
        return [{"tag": "button", "selector": "[data-testid=run]", "text": "실행"}]

    def step(self, action, selector=None, value=None, note=""):
        self.performed.append((action, selector))
        return {"idx": len(self.performed), "action": action, "selector": selector,
                "url_after": "http://x/done" if action == "click" else "http://x/",
                "api": [{"m": 1}] if action == "click" else [], "backend": None}


class ScriptedAgent:
    def __init__(self, replies):
        self.replies = list(replies)
        self.models = []

    def chat(self, model, messages, **kw):
        self.models.append(model)
        return self.replies.pop(0)


class AgentLoopTest(unittest.TestCase):
    def test_observe_act_observe_then_done(self):
        agent = ScriptedAgent([
            json.dumps({"action": "click", "selector": "[data-testid=run]"}),
            json.dumps({"done": True, "reason": "결과 확인됨"}),
        ])
        session = StubSession()
        raws, reason = run_goal_loop("실행 버튼을 누른다", session, agent,
                                     ModelRoles(agent="opus-x"), log=lambda m: None)
        self.assertEqual(reason, "결과 확인됨")
        # 진입 goto + 계획된 click = 2회 수행
        self.assertEqual(session.performed, [("goto", "/"), ("click", "[data-testid=run]")])
        self.assertEqual(set(agent.models), {"opus-x"}, "루프 결정은 agent 모델만 쓴다")

    def test_invalid_decision_stops_honestly(self):
        agent = ScriptedAgent([json.dumps({"action": "teleport", "selector": "#x"})])
        raws, reason = run_goal_loop("g", StubSession(), agent, ModelRoles(),
                                     log=lambda m: None)
        self.assertIn("유효하지 않은", reason)
        self.assertEqual(len(raws), 1)  # 진입 goto만

    def test_max_turns_cap(self):
        agent = ScriptedAgent([json.dumps({"action": "click",
                                           "selector": "[data-testid=run]"})] * 3)
        raws, reason = run_goal_loop("g", StubSession(), agent, ModelRoles(),
                                     max_turns=3, log=lambda m: None)
        self.assertIn("최대 턴", reason)
        self.assertEqual(len(raws), 4)  # goto + 3클릭

    def test_extract_object_with_fence(self):
        obj = _extract_object('```json\n{"done": true}\n```')
        self.assertTrue(obj["done"])

    def test_initial_goto_false_resumes_session(self):
        """선행 스텝(로그인 등)이 이미 진입한 세션은 goto 없이 현재 화면부터 관측한다."""
        agent = ScriptedAgent([json.dumps({"done": True, "reason": "이미 목표 화면"})])
        session = StubSession()
        raws, reason = run_goal_loop("g", session, agent, ModelRoles(),
                                     initial_goto=False, log=lambda m: None)
        self.assertEqual(session.performed, [], "initial_goto=False면 진입 goto가 없어야 한다")
        self.assertEqual(raws, [])
        self.assertEqual(reason, "이미 목표 화면")


class SourceWatchTest(unittest.TestCase):
    def test_snapshot_diff_detects_change_and_skips_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("x = 1", encoding="utf-8")
            (root / "node_modules").mkdir()
            (root / "node_modules/dep.js").write_text("noise", encoding="utf-8")
            first = snapshot([tmp])
            self.assertEqual(len(first), 1, "node_modules는 걷지 않는다")
            self.assertEqual(changed_files(first, snapshot([tmp])), [])
            (root / "app.py").write_text("x = 2", encoding="utf-8")
            import os
            os.utime(root / "app.py", (1, 999999999))
            diffs = changed_files(first, snapshot([tmp]))
            self.assertEqual(len(diffs), 1)
            self.assertTrue(diffs[0].endswith("app.py"))


class IndexPageTest(unittest.TestCase):
    def test_build_index_lists_journeys(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "login-flow"
            d.mkdir()
            (d / "test-report.html").write_text("<h1>r</h1>", encoding="utf-8")
            (d / "screen-spec.pdf").write_bytes(b"%PDF")
            index = build_index(tmp)
            text = index.read_text(encoding="utf-8")
            self.assertIn("login-flow", text)
            self.assertIn("테스트결과서.html", text)
            self.assertIn("화면정의서.pdf", text)


if __name__ == "__main__":
    unittest.main()
