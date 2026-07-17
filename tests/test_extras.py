import os
import tempfile
import unittest
from pathlib import Path

from test_docgen import make_journey
from xgen_creator.bridge.driver import reroute_matcher, swap_base
from xgen_creator.docgen.narrate import narrate_journey
from xgen_creator.docgen.pdf import find_edge, html_to_pdf
from xgen_creator.llm import LLMClient
from xgen_creator.pipeline.roles import ModelRoles
from xgen_creator.sidecar import load_app


class FakeClient:
    def __init__(self):
        self.calls = []

    def chat(self, model, messages, **kw):
        self.calls.append((model, messages))
        return "증거 기반 해설이다."


class NarrateTest(unittest.TestCase):
    def test_fills_narratives_with_source_model(self):
        journey = make_journey()
        client = FakeClient()
        roles = ModelRoles(agent="agent-x", source="source-y")
        narrate_journey(journey, client, roles, rules_context="## Rule: tone\n매뉴얼체.")
        self.assertEqual(journey.narrative, "증거 기반 해설이다.")
        self.assertTrue(all(s.narrative for s in journey.steps))
        models = {m for m, _ in client.calls}
        self.assertEqual(models, {"source-y"}, "서술은 source 역할 모델만 사용")
        system = client.calls[0][1][0]["content"]
        self.assertIn("매뉴얼체", system, "Rule 컨텍스트가 프롬프트에 주입돼야 한다")
        self.assertIn("추정하지 않는다", system)

    def test_narrate_failure_does_not_break(self):
        class Boom:
            def chat(self, *a, **k):
                raise RuntimeError("down")

        journey = make_journey()
        narrate_journey(journey, Boom(), ModelRoles())
        self.assertIsNone(journey.narrative)
        self.assertTrue(all(s.narrative is None for s in journey.steps))


class LLMClientTest(unittest.TestCase):
    def test_from_env_none_without_endpoint(self):
        os.environ.pop("XGEN_CREATOR_LLM_BASE_URL", None)
        self.assertIsNone(LLMClient.from_env({}))
        client = LLMClient.from_env({"llm_base_url": "http://localhost:9/v1"})
        self.assertEqual(client.base_url, "http://localhost:9/v1")


class RerouteTest(unittest.TestCase):
    def test_swap_base_preserves_path_and_query(self):
        self.assertEqual(
            swap_base("http://localhost:8080/api/workflow/list?page=2",
                      "http://127.0.0.1:8201/"),
            "http://127.0.0.1:8201/api/workflow/list?page=2")

    def test_matcher_ignores_query_string(self):
        """실 XGEN에서 조용히 샜던 결함 회귀 — 쿼리 붙은 URL도 매칭돼야 한다."""
        m = reroute_matcher("**/api/node/**")
        self.assertTrue(m("http://localhost:3100/api/node/get?include_disabled=true"))
        self.assertTrue(m("http://localhost:3100/api/node/get"))
        self.assertFalse(m("http://localhost:3100/api/workflow/list"))

    def test_matcher_segment_glob(self):
        m = reroute_matcher("**/api/canvas/*")
        self.assertTrue(m("http://x:3100/api/canvas/save?id=1"))
        self.assertFalse(m("http://x:3100/api/other/save"))


class SidecarLoadTest(unittest.TestCase):
    def test_load_app_by_ref(self):
        cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                Path(tmp, "target_app.py").write_text(
                    "async def app(scope, receive, send):\n    pass\n",
                    encoding="utf-8")
                app = load_app("target_app:app", tmp)
                self.assertTrue(callable(app))
                os.chdir(cwd)  # cwd가 임시폴더 안이면 Windows에서 cleanup rmdir 실패
        finally:
            os.chdir(cwd)


class PdfTest(unittest.TestCase):
    def test_html_to_pdf_via_edge(self):
        if find_edge() is None:
            self.skipTest("Edge 미설치 환경")
        with tempfile.TemporaryDirectory() as tmp:
            html = Path(tmp) / "doc.html"
            html.write_text("<h1>PDF 검증</h1><p>본문</p>", encoding="utf-8")
            pdf = html_to_pdf(html)
            self.assertTrue(pdf.exists())
            self.assertGreater(pdf.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
