import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path

from xgen_creator.web import ConsoleApp


def call(app, method="GET", path="/", body=b"", query=""):
    scope = {"type": "http", "method": method, "path": path,
             "query_string": query.encode(), "headers": []}
    sent = []

    async def receive():
        return {"type": "http.request", "body": body}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    status = sent[0]["status"]
    payload = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, payload


def fake_make(config, log=print, on_frame=None, **params):
    log("여정: fake (스텝 1개)")
    if on_frame:  # 브리지가 넘기는 라이브 화면 프레임을 흉내
        on_frame({"idx": 1, "action": "click", "url_before": "http://x/a",
                  "url_after": "http://x/b", "shot": None})
    log("완료")
    return {"journey_id": "fake", "journey_path": "x", "outputs": [], "pdfs": [],
            "video": None, "narrated": False,
            "steps": [{"idx": 1, "action": "click", "selector": "#b", "note": "",
                       "backend": True, "screenshot": None, "url_after": "http://x/"}]}


class ConsoleAppTest(unittest.TestCase):
    def _app(self, tmp):
        config = {"base_url": "http://localhost:1", "out_dir": tmp,
                  "journey_dir": tmp, "rules_dir": tmp}
        return ConsoleApp(config, make_fn=fake_make)

    def test_page_has_run_button(self):
        with tempfile.TemporaryDirectory() as tmp:
            status, body = call(self._app(tmp))
            self.assertEqual(status, 200)
            text = body.decode("utf-8")
            self.assertIn("산출물 만들어줘", text)
            self.assertIn("라이브 소스 스크린", text)
            self.assertIn("라이브 화면", text)       # 화면 전환 스트리밍 패널
            self.assertIn("산출물 갤러리", text)      # 게이트웨이 링크

    def test_state_surfaces_live_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self._app(tmp)
            call(app, "POST", "/api/run", b"{}")
            deadline = time.time() + 5
            frame = None
            while time.time() < deadline:
                _, payload = call(app, path="/api/state")
                state = json.loads(payload)
                if state.get("frame"):
                    frame = state["frame"]
                if state["state"] == "done":
                    break
                time.sleep(0.05)
            self.assertIsNotNone(frame, "라이브 화면 프레임이 상태에 노출돼야 한다")
            self.assertEqual(frame["url_after"], "http://x/b")
            self.assertGreaterEqual(frame["seq"], 1)

    def test_gallery_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "login-flow"
            d.mkdir()
            (d / "test-report.html").write_text("<h1>r</h1>", encoding="utf-8")
            status, body = call(self._app(tmp), path="/gallery")
            self.assertEqual(status, 200)
            text = body.decode("utf-8")
            self.assertIn("login-flow", text)
            self.assertIn('href="/files/', text)  # 콘솔 파일 서빙 경로로 링크

    def test_run_then_state_reports_lines_and_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self._app(tmp)
            status, body = call(app, "POST", "/api/run",
                                json.dumps({"narrate": False}).encode())
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(body)["started"])
            deadline = time.time() + 5
            state = None
            while time.time() < deadline:
                _, payload = call(app, path="/api/state")
                state = json.loads(payload)
                if state["state"] == "done":
                    break
                time.sleep(0.05)
            self.assertEqual(state["state"], "done")
            self.assertTrue(any("완료" in line for line in state["lines"]))
            self.assertEqual(state["result"]["steps"][0]["backend"], True)

    def test_run_conflict_while_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            def slow_make(config, log=print, **params):
                time.sleep(0.5)
                return fake_make(config, log=log)

            app = ConsoleApp({"base_url": "", "out_dir": tmp, "journey_dir": tmp},
                             make_fn=slow_make)
            call(app, "POST", "/api/run", b"{}")
            status, _ = call(app, "POST", "/api/run", b"{}")
            self.assertEqual(status, 409)

    def test_file_serving_and_traversal_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "doc.html").write_text("<h1>ok</h1>", encoding="utf-8")
            app = self._app(tmp)
            status, body = call(app, path="/files/doc.html")
            self.assertEqual(status, 200)
            self.assertIn(b"ok", body)
            status, _ = call(app, path="/files/../cli.py")
            self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
