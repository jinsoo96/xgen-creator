import asyncio
import tempfile
import unittest
from pathlib import Path

from test_middleware import backend_app
from xgen_creator.live import LiveHub
from xgen_creator.trace import CreatorTraceMiddleware
from xgen_creator.trace.tracer import TraceEvent

TESTS_DIR = str(Path(__file__).parent)
FIXTURE = str(Path(__file__).parent / "fixture_target.py")


class LiveHubTest(unittest.TestCase):
    def test_publish_includes_source_text(self):
        async def main():
            hub = LiveHub()
            queue = hub.subscribe()
            with tempfile.TemporaryDirectory() as tmp:
                app = CreatorTraceMiddleware(backend_app, roots=[TESTS_DIR],
                                             trace_dir=tmp, live_hub=hub)
                scope = {"type": "http", "method": "GET", "path": "/api",
                         "headers": [(b"x-creator-trace", b"live-1")]}

                async def receive():
                    return {"type": "http.request", "body": b""}

                async def send(message):
                    pass

                await app(scope, receive, send)
            items = []
            while not queue.empty():
                items.append(queue.get_nowait())
            return items

        items = asyncio.run(main())
        self.assertTrue(items, "트레이스 이벤트가 라이브 허브로 흘러야 한다")
        texts = [i["text"].strip() for i in items]
        self.assertIn("total = 0", texts, "이벤트에 소스 라인 텍스트가 실려야 한다")
        self.assertTrue(all({"file", "line", "func", "kind", "text"} <= set(i) for i in items))

    def test_no_subscribers_is_noop(self):
        hub = LiveHub()
        hub.publish(TraceEvent(FIXTURE, 4, "helper", 1))
        self.assertEqual(hub.dropped, 0)

    def test_slow_subscriber_drops_honestly(self):
        async def main():
            hub = LiveHub(queue_size=1)
            hub.subscribe()
            for n in (4, 5, 6):
                hub.publish(TraceEvent(FIXTURE, n, "helper", 1))
            return hub.dropped

        self.assertGreaterEqual(asyncio.run(main()), 2)


if __name__ == "__main__":
    unittest.main()
