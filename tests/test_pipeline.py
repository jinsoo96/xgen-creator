import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_docgen import make_journey
from xgen_creator.pipeline import build, load_roles
from xgen_creator.pipeline.roles import DEFAULT_AGENT, DEFAULT_SOURCE
from xgen_creator.rules import load_rules, compose_context


class BuildTest(unittest.TestCase):
    def test_incremental_rebuild(self):
        journey = make_journey()
        with tempfile.TemporaryDirectory() as tmp:
            jpath = journey.save(Path(tmp) / "login-flow.json")
            out = Path(tmp) / "docs_out"
            state = Path(tmp) / "state.json"

            first = build([jpath], out, state_file=state)
            self.assertEqual(first["built"], ["login-flow"])
            self.assertTrue((out / "login-flow" / "SUMMARY.md").exists())
            self.assertTrue((out / "login-flow" / "login-flow.html").exists())

            second = build([jpath], out, state_file=state)
            self.assertEqual(second["built"], [])
            self.assertEqual(second["skipped"], ["login-flow"])

            journey.title = "로그인 여정 v2"
            journey.save(jpath)
            third = build([jpath], out, state_file=state)
            self.assertEqual(third["built"], ["login-flow"], "내용이 바뀌면 재렌더")


class RolesTest(unittest.TestCase):
    def test_defaults_agent_opus_source_fable(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XGEN_CREATOR_MODEL_AGENT", None)
            os.environ.pop("XGEN_CREATOR_MODEL_SOURCE", None)
            roles = load_roles({})
            self.assertEqual(roles.agent, DEFAULT_AGENT)
            self.assertEqual(roles.source, DEFAULT_SOURCE)
            self.assertIn("opus", roles.agent)
            self.assertIn("fable", roles.source)

    def test_config_beats_env(self):
        with mock.patch.dict(os.environ, {"XGEN_CREATOR_MODEL_AGENT": "env-model"}):
            roles = load_roles({"models": {"agent": "config-model"}})
            self.assertEqual(roles.agent, "config-model")
            roles = load_roles({})
            self.assertEqual(roles.agent, "env-model")


class RulesTest(unittest.TestCase):
    def test_load_and_compose(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "01-terms.md").write_text("QA 용어로 통일한다.", encoding="utf-8")
            Path(tmp, "02-tone.md").write_text("매뉴얼체로 쓴다.", encoding="utf-8")
            rules = load_rules(tmp)
            self.assertEqual([name for name, _ in rules], ["01-terms", "02-tone"])
            context = compose_context(rules)
            self.assertIn("## Rule: 01-terms", context)
            self.assertIn("매뉴얼체", context)

    def test_compose_drops_over_budget_honestly(self):
        rules = [("a", "x" * 100), ("b", "y" * 100)]
        context = compose_context(rules, max_chars=120)
        self.assertIn("## Rule: a", context)
        self.assertNotIn("yyy", context)
        self.assertIn("미포함된 규칙: b", context)

    def test_missing_dir_is_empty(self):
        self.assertEqual(load_rules("no-such-dir"), [])


if __name__ == "__main__":
    unittest.main()
