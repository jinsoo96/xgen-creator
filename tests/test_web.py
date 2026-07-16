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


def fake_make(config, log=print, **params):
    log("여정: fake (스텝 1개)")
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
