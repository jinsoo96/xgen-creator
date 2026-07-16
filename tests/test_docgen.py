import tempfile
import unittest
from pathlib import Path

from xgen_creator.docgen import Journey, Step, render_journey_md, render_journey_html

BACKEND_PAYLOAD = {
    "trace_id": "t1", "method": "POST", "path": "/api/login", "status": 200,
    "duration_ms": 12.3, "lock_wait_ms": 0.0, "truncated": False, "event_count": 5,
    "files": {"/srv/app/auth.py": [10, 11, 12]},
    "flow": [["line", "/srv/app/auth.py", 10, "login", 1]],
    "slices": [{
        "file": "/srv/app/auth.py", "executed_count": 3, "total_lines": 40,
        "excerpts": [{"start": 9, "end": 13, "lines": [
            [9, False, "def login(req):"],
            [10, True, "    user = find(req.email)"],
            [11, True, "    check(user, req.password)"],
            [12, True, "    return token(user)"],
            [13, False, ""],
        ]}],
    }],
}


def make_journey() -> Journey:
    return Journey(
        id="login-flow", title="로그인 여정", base_url="http://localhost:3000",
        created="2026-07-16T00:00:00+00:00",
        steps=[
            Step(idx=1, action="click", selector="button[type=submit]",
                 url_before="http://localhost:3000/login",
                 url_after="http://localhost:3000/dashboard",
                 element={"tag": "button", "testid": "login-btn", "text": "로그인"},
                 frontend_sources=[{"file": "features/auth/login.tsx", "line": 42,
                                    "score": 100, "reason": "data-testid 정확일치"}],
                 api=[{"method": "POST", "url": "http://localhost:8000/api/login"}],
                 backend=BACKEND_PAYLOAD),
            Step(idx=2, action="goto", selector="/settings",
                 url_before="http://localhost:3000/dashboard",
                 url_after="http://localhost:3000/settings"),
        ],
    )


class RenderMdTest(unittest.TestCase):
    def test_chapters_and_honesty(self):
        journey = make_journey()
        with tempfile.TemporaryDirectory() as tmp:
            written = render_journey_md(journey, tmp)
            names = {p.name for p in written}
            self.assertEqual(names, {"SUMMARY.md", "00-overview.md",
                                     "01-step.md", "02-step.md"})
            overview = (Path(tmp) / "00-overview.md").read_text(encoding="utf-8")
            self.assertIn("백엔드 트레이스 확보 1/2", overview)

            step1 = (Path(tmp) / "01-step.md").read_text(encoding="utf-8")
            self.assertIn("features/auth/login.tsx:42", step1)
            self.assertIn("POST", step1)
            self.assertIn(">    10 |     user = find(req.email)", step1)
            self.assertIn("화면 전환", step1)

            step2 = (Path(tmp) / "02-step.md").read_text(encoding="utf-8")
            self.assertIn("증거 없음", step2)

    def test_roundtrip_json(self):
        journey = make_journey()
        with tempfile.TemporaryDirectory() as tmp:
            path = journey.save(Path(tmp) / "j.json")
            loaded = Journey.load(path)
            self.assertEqual(loaded.id, journey.id)
            self.assertEqual(len(loaded.steps), 2)
            self.assertEqual(loaded.steps[0].backend["status"], 200)


class RenderHtmlTest(unittest.TestCase):
    def test_self_contained_html(self):
        journey = make_journey()
        with tempfile.TemporaryDirectory() as tmp:
            out = render_journey_html(journey, Path(tmp) / "j.html")
            content = out.read_text(encoding="utf-8")
            self.assertIn("<title>로그인 여정</title>", content)
            self.assertIn("실행된 백엔드 소스", content)
            self.assertIn('class="hit"', content)
            self.assertIn("백엔드 트레이스 증거 없음", content)


if __name__ == "__main__":
    unittest.main()
