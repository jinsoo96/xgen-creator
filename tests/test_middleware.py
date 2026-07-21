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


class ConcurrencyTest(unittest.TestCase):
    def test_second_concurrent_trace_is_nonblocking_and_honest(self):
        """이미 트레이스 진행 중이면 두 번째는 막지 않고(논블로킹) 관측 생략·정직 표기."""
        with tempfile.TemporaryDirectory() as tmp:
            app = CreatorTraceMiddleware(backend_app, roots=[TESTS_DIR], trace_dir=tmp)
            app._lock.acquire()  # 다른 요청이 트레이스 중인 상황을 흉내
            try:
                sent = run_request(app, [(b"x-creator-trace", b"t-concurrent")])
                self.assertEqual(sent[0]["status"], 200, "요청은 막히지 않고 정상 응답")
            finally:
                app._lock.release()
            payload = TraceStore(tmp).load("t-concurrent")
            self.assertIsNotNone(payload)
            self.assertEqual(payload["skipped"], "동시 트레이스 진행 중 — 관측 생략")
            self.assertEqual(payload["event_count"], 0)

    def test_capture_vars_records_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = CreatorTraceMiddleware(backend_app, roots=[TESTS_DIR], trace_dir=tmp,
                                         capture_vars=True)
            run_request(app, [(b"x-creator-trace", b"t-vars")])
            payload = TraceStore(tmp).load("t-vars")
            # flow 6-튜플: [kind, file, line, func, depth, vars] — helper 내부 변수값이 있어야
            var_rows = [r for r in payload["flow"]
                        if len(r) > 5 and r[5] and "total" in r[5]]
            self.assertTrue(var_rows, "라인별 지역변수 값이 flow에 담겨야 한다")


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

    def test_store_concurrent_writes_safe(self):
        """멀티프로세스/멀티워커 — 서로 다른 trace_id 동시 저장이 유실·손상 없이 안전.

        원자 교체(os.replace)라 여러 워커가 각자 트레이스를 같은 dir에 써도 안 깨진다.
        """
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            store = TraceStore(tmp)
            ids = [f"w{w}-{k}" for w in range(4) for k in range(25)]

            def writer(chunk):
                for tid in chunk:
                    store.save(tid, {"trace_id": tid, "flow": [[tid]]})

            chunks = [ids[i::4] for i in range(4)]
            threads = [threading.Thread(target=writer, args=(c,)) for c in chunks]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(len(store.list_ids()), 100, "모든 트레이스가 유실 없이 저장")
            for tid in ids:  # 각 파일이 온전(반쯤 쓰인 것 없음)
                self.assertEqual(store.load(tid)["trace_id"], tid)


if __name__ == "__main__":
    unittest.main()
