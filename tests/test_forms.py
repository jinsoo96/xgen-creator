import tempfile
import unittest
from pathlib import Path

from test_docgen import make_journey
from xgen_creator.docgen.forms import render_form, FORMS
from xgen_creator.pipeline import build


class TestReportFormTest(unittest.TestCase):
    def test_md_verdicts_and_appendix(self):
        journey = make_journey()
        with tempfile.TemporaryDirectory() as tmp:
            (path_md, path_html) = render_form(journey, "test-report", tmp)
            md = path_md.read_text(encoding="utf-8")
            self.assertIn("# 테스트결과서", md)
            self.assertIn("| 총 스텝 | 2 (성공/수행 2 · 실패 0) |", md)
            self.assertIn("**성공** | HTTP 200", md)
            self.assertIn("**수행됨** | 백엔드 증거 없음", md)
            self.assertIn("## 부록 A", md)
            self.assertIn(">    10 |     user = find(req.email)", md)

            html = path_html.read_text(encoding="utf-8")
            self.assertIn("badge pass", html)
            self.assertIn("badge info", html)
            self.assertIn('class="hit"', html)

    def test_failed_step_verdict(self):
        journey = make_journey()
        journey.steps[0].backend = dict(journey.steps[0].backend, status=500)
        with tempfile.TemporaryDirectory() as tmp:
            md = render_form(journey, "test-report", tmp, fmt="md")[0] \
                .read_text(encoding="utf-8")
            self.assertIn("**실패** | HTTP 500", md)
            self.assertIn("실패 1", md)


class ScreenSpecFormTest(unittest.TestCase):
    def test_md_groups_screens_and_links_sources(self):
        journey = make_journey()
        with tempfile.TemporaryDirectory() as tmp:
            md = render_form(journey, "screen-spec", tmp, fmt="md")[0] \
                .read_text(encoding="utf-8")
            self.assertIn("# 화면정의서", md)
            self.assertIn("## SCR-01 — `http://localhost:3000/dashboard`", md)
            self.assertIn("## SCR-02 — `http://localhost:3000/settings`", md)
            self.assertIn("features/auth/login.tsx:42 (data-testid 정확일치)", md)
            self.assertIn("증거 없음", md)  # goto 스텝은 소스 근거 없음 — 정직 표기

    def test_unknown_form_raises(self):
        with self.assertRaises(ValueError):
            render_form(make_journey(), "no-such-form", ".")


class PipelineFormTest(unittest.TestCase):
    def test_build_with_form_uses_separate_state(self):
        journey = make_journey()
        with tempfile.TemporaryDirectory() as tmp:
            jpath = journey.save(Path(tmp) / "j.json")
            out, state = Path(tmp) / "out", Path(tmp) / "state.json"

            r1 = build([jpath], out, state_file=state, form="test-report")
            self.assertEqual(r1["built"], ["login-flow"])
            self.assertTrue((out / "login-flow" / "test-report.md").exists())
            self.assertTrue((out / "login-flow" / "test-report.html").exists())

            # 같은 여정이라도 양식이 다르면 별도 상태 — journey 챕터는 새로 빌드돼야 한다
            r2 = build([jpath], out, state_file=state, form="journey")
            self.assertEqual(r2["built"], ["login-flow"])
            # 같은 양식 재빌드는 스킵
            r3 = build([jpath], out, state_file=state, form="test-report")
            self.assertEqual(r3["skipped"], ["login-flow"])

    def test_registry_has_korean_names(self):
        self.assertEqual(FORMS["screen-spec"]["이름"], "화면정의서")
        self.assertEqual(FORMS["test-report"]["이름"], "테스트결과서")


if __name__ == "__main__":
    unittest.main()
