import asyncio
import tempfile
import unittest
from pathlib import Path

import fixture_target
from xgen_creator.trace import CreatorTraceMiddleware, TraceStore

TESTS_DIR = str(Path(__file__).parent)


async def backend_app(scope, receive, send):
    fixture_target.helper(4)
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def run_request(app, headers):
    scope = {"type": "http", "method": "GET", "path": "/api/demo", "headers": headers}
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent


class MiddlewareTest(unittest.TestCase):
    def test_traced_request_saves_correlated_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = CreatorTraceMiddleware(backend_app, roots=[TESTS_DIR], trace_dir=tmp)
            sent = run_request(app, [(b"x-creator-trace", b"t-demo-001")])
            self.assertEqual(sent[0]["status"], 200)

            payload = TraceStore(tmp).load("t-demo-001")
            self.assertIsNotNone(payload)
            self.assertEqual(payload["trace_id"], "t-demo-001")
            self.assertEqual(payload["path"], "/api/demo")
            self.assertEqual(payload["status"], 200)
            self.assertFalse(payload["truncated"])
            target = [f for f in payload["files"] if f.endswith("fixture_target.py")]
            self.assertEqual(len(target), 1, "백엔드가 실행한 소스 파일이 상관돼야 한다")
            self.assertTrue(payload["slices"], "실행 슬라이스가 있어야 한다")
            self.assertGreater(payload["event_count"], 0)

    def test_untraced_request_passes_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = CreatorTraceMiddleware(backend_app, roots=[TESTS_DIR], trace_dir=tmp)
            sent = run_request(app, [])
            self.assertEqual(sent[0]["status"], 200)
            self.assertEqual(TraceStore(tmp).list_ids(), [])

    def test_store_wait_and_sanitize(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TraceStore(tmp)
            store.save("../evil/../id", {"x": 1})
            self.assertEqual(store.list_ids(), ["evilid"])
            self.assertIsNone(store.wait("missing", timeout=0.3, poll=0.05))


if __name__ == "__main__":
    unittest.main()
