import json
import tempfile
import unittest
from pathlib import Path

from xgen_creator.docgen.debug_view import build_debug_view, _source_map

PAYLOAD = {
    "trace_id": "t1", "method": "GET", "path": "/api/x", "status": 200,
    "duration_ms": 12.0, "event_count": 4, "file_count": 1, "truncated": False,
    "files": {"/srv/app.py": [10, 11, 12]},
    "flow": [
        ["line", "/srv/app.py", 10, "handler", 1],
        ["call", "/srv/app.py", 20, "helper", 2],   # call 이벤트는 리플레이에서 제외
        ["line", "/srv/app.py", 11, "handler", 1],
        ["line", "/srv/app.py", 12, "handler", 1],
    ],
    "slices": [{
        "file": "/srv/app.py", "executed_count": 3, "total_lines": 15,
        "excerpts": [{"start": 9, "end": 13, "lines": [
            [9, False, "def handler(req):"],
            [10, True, "    user = auth(req)"],
            [11, True, "    data = load(user)"],
            [12, True, "    return data"],
            [13, False, ""],
        ]}],
    }],
}


class DebugViewTest(unittest.TestCase):
    def test_source_map_from_slices(self):
        src = _source_map(PAYLOAD)
        self.assertEqual(src["/srv/app.py"]["10"], "    user = auth(req)")
        self.assertEqual(src["/srv/app.py"]["12"], "    return data")

    def test_build_self_contained_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = build_debug_view(PAYLOAD, Path(tmp) / "replay.html")
            html = out.read_text(encoding="utf-8")
            self.assertIn("디버거 리플레이", html)
            self.assertIn("GET /api/x", html)
            # 외부 리소스 0 (self-contained)
            self.assertNotIn("http://", html.split("__DATA__")[0] if "__DATA__" in html else html)
            self.assertNotIn("src=\"http", html)
            # flow가 임베드되고 call 이벤트는 빠졌다 (line 3개만)
            start = html.index("const D = ") + len("const D = ")
            data = json.loads(html[start:html.index("\n", start)].rstrip(";"))
            self.assertEqual(len(data["flow"]), 3, "line 이벤트만 리플레이에 들어간다")
            self.assertEqual([f[1] for f in data["flow"]], [10, 11, 12])
            self.assertIn("/srv/app.py", data["src"])

    def test_empty_flow_still_builds(self):
        payload = dict(PAYLOAD, flow=[])
        with tempfile.TemporaryDirectory() as tmp:
            out = build_debug_view(payload, Path(tmp) / "e.html")
            self.assertTrue(out.exists())


class DebugLinkConsistencyTest(unittest.TestCase):
    """결과서의 리플레이 링크는 실제 생성되는 리플레이 파일과 1:1 일치해야 한다."""

    def _report(self, backend):
        from xgen_creator.docgen.forms import render_form
        from xgen_creator.docgen.model import Journey, Step
        journey = Journey(id="j", title="t", steps=[
            Step(idx=1, action="click", selector="b", backend=backend)])
        with tempfile.TemporaryDirectory() as tmp:
            md, html = render_form(journey, "test-report", tmp)
            return md.read_text(encoding="utf-8"), html.read_text(encoding="utf-8")

    def test_backend_with_flow_gets_link(self):
        md, html = self._report(PAYLOAD)
        self.assertIn("debug/step-01.html", md)
        self.assertIn("debug/step-01.html", html)

    def test_backend_without_flow_has_no_link(self):
        md, html = self._report(dict(PAYLOAD, flow=[]))
        self.assertNotIn("debug/step-01.html", md)
        self.assertNotIn("debug/step-01.html", html)


if __name__ == "__main__":
    unittest.main()
