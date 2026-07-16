import json
import unittest

from xgen_creator.plan import plan_steps, _validate, _extract_json_array
from xgen_creator.pipeline.roles import ModelRoles


class FakeAgent:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def chat(self, model, messages, **kw):
        self.calls.append((model, messages))
        return self.reply


OUTLINE = [{"tag": "button", "selector": "[data-testid=analyze-button]", "text": "분석 실행"},
           {"tag": "input", "selector": "input[type=email]", "text": None}]


class PlanTest(unittest.TestCase):
    def test_uses_agent_model_and_returns_valid_steps(self):
        reply = json.dumps([
            {"action": "click", "selector": "[data-testid=analyze-button]", "note": "분석"},
        ])
        agent = FakeAgent(reply)
        roles = ModelRoles(agent="agent-opus", source="source-fable")
        steps = plan_steps("분석 버튼을 누른다", OUTLINE, agent, roles)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["action"], "click")
        self.assertEqual(agent.calls[0][0], "agent-opus", "계획은 agent 역할 모델을 쓴다")

    def test_strips_code_fence(self):
        reply = "```json\n[{\"action\":\"goto\",\"value\":\"/\"}]\n```"
        steps = plan_steps("이동", OUTLINE, FakeAgent(reply), ModelRoles())
        self.assertEqual(steps[0]["action"], "goto")

    def test_invalid_actions_and_missing_selector_dropped(self):
        raw = [
            {"action": "click", "selector": "#ok"},
            {"action": "teleport", "selector": "#x"},      # 미지원 action
            {"action": "click"},                            # selector 없음
            {"action": "goto", "value": "/home"},           # goto는 selector 없이 OK
            "쓰레기",
        ]
        steps = _validate(raw)
        self.assertEqual([s["action"] for s in steps], ["click", "goto"])

    def test_extract_array_failure_raises(self):
        with self.assertRaises(ValueError):
            _extract_json_array("계획을 세울 수 없습니다")


if __name__ == "__main__":
    unittest.main()
