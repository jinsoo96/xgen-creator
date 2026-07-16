import json
import os
import unittest
from pathlib import Path

import fixture_target
from xgen_creator.trace import LineTracer, build_slices, render_slices_text

TESTS_DIR = str(Path(__file__).parent)
FIXTURE_FILE = str(Path(fixture_target.__file__))


class TracerTest(unittest.TestCase):
    def _trace(self, fn, *args, **tracer_kw):
        # 스코프를 fixture 파일로 한정 — monitoring 백엔드는 실행 중 프레임(테스트
        # 자신)도 잡으므로 디렉토리 스코프면 테스트 파일 라인이 섞인다
        tracer = LineTracer([FIXTURE_FILE], **tracer_kw)
        tracer.start()
        try:
            fn(*args)
        finally:
            result = tracer.stop()
        return result

    def test_captures_executed_lines_only(self):
        result = self._trace(fixture_target.helper, 3)
        files = result.executed_lines()
        target = [f for f in files if f.endswith("fixture_target.py")]
        self.assertEqual(len(target), 1)
        lines = files[target[0]]
        source = Path(target[0]).read_text(encoding="utf-8").splitlines()
        executed_texts = [source[n - 1].strip() for n in lines]
        self.assertIn("total = 0", executed_texts)
        self.assertIn("total += i", executed_texts)
        # untouched()는 호출 안 됨 — 그 본문 라인은 없어야 한다
        self.assertNotIn('marker = "실행되지 않는 함수"', executed_texts)

    def test_out_of_scope_not_captured(self):
        result = self._trace(lambda: json.dumps({"a": 1}))
        files = result.executed_lines()
        self.assertFalse(any("json" in os.path.basename(f) for f in files))

    def test_empty_roots_captures_nothing(self):
        tracer = LineTracer([])
        tracer.start()
        fixture_target.helper(3)
        result = tracer.stop()
        self.assertEqual(len(result.events), 0)

    def test_truncation_is_honest(self):
        result = self._trace(fixture_target.helper, 1000, max_events=10)
        self.assertTrue(result.truncated)
        self.assertLessEqual(len(result.events), 10)

    def test_flow_preserves_order(self):
        result = self._trace(fixture_target.helper, 2)
        flow = result.flow()
        self.assertGreater(len(flow), 2)
        # 첫 라인 이벤트는 함수 본문 첫 실행문(total = 0)이어야 한다
        first = flow[0]
        source = Path(first[1]).read_text(encoding="utf-8").splitlines()
        self.assertEqual(source[first[2] - 1].strip(), "total = 0")

    def test_live_event_callback(self):
        seen = []
        tracer = LineTracer([TESTS_DIR], on_event=seen.append)
        tracer.start()
        fixture_target.helper(2)
        tracer.stop()
        self.assertEqual(len(seen), len(tracer.result.events))

    def test_monitoring_backend_parity(self):
        import sys
        if not hasattr(sys, "monitoring"):
            self.skipTest("py3.12+ 아님")
        by_backend = {}
        for backend in ("settrace", "monitoring"):
            tracer = LineTracer([TESTS_DIR], backend=backend)
            tracer.start()
            fixture_target.helper(3)
            result = tracer.stop()
            self.assertEqual(tracer.backend, backend)
            files = result.executed_lines()
            target = [f for f in files if f.endswith("fixture_target.py")]
            by_backend[backend] = set(files[target[0]])
        self.assertEqual(by_backend["settrace"], by_backend["monitoring"],
                         "두 백엔드의 실행 라인 집합은 동일해야 한다")

    def test_slices_render(self):
        result = self._trace(fixture_target.helper, 3)
        slices = build_slices(result.executed_lines(), context=1)
        self.assertEqual(len(slices), 1)
        text = render_slices_text(slices)
        self.assertIn("fixture_target.py", text)
        self.assertIn(">", text)
        # 실행된 라인은 '>' 마커
        hit_rows = [r for r in text.splitlines() if r.startswith(">")]
        self.assertTrue(any("total += i" in r for r in hit_rows))


if __name__ == "__main__":
    unittest.main()
