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

    def test_wall_clock_budget_stops_tracing(self):
        """벽시계 예산 초과 시 트레이싱이 멈춰 대상이 행되지 않아야 한다.

        Windows monotonic 해상도(~15ms) 대비 넉넉히 큰 작업 + 작은 예산으로 결정적 검증.
        """
        tracer = LineTracer([TESTS_DIR], max_seconds=0.02)
        tracer.start()
        fixture_target.helper(400_000)  # 예산(20ms) 안에 다 못 도는 큰 작업
        result = tracer.stop()
        self.assertTrue(tracer.timed_out, "예산 초과가 감지돼야 한다")
        self.assertTrue(result.truncated)
        self.assertLess(len(result.events), 800_000, "예산으로 전량 캡처 전에 멈춰야 한다")

    def test_no_budget_traces_all(self):
        tracer = LineTracer([TESTS_DIR])  # max_seconds None
        tracer.start()
        fixture_target.helper(50)
        result = tracer.stop()
        self.assertFalse(tracer.timed_out)
        self.assertFalse(result.truncated)
        self.assertGreater(len(result.events), 0)

    def test_capture_vars_records_line_values(self):
        """data flow — 라인마다 지역변수 값이 스냅샷돼야 한다."""
        result = self._trace(fixture_target.helper, 3, capture_vars=True)
        line_evs = [e for e in result.events
                    if e.kind == "line" and e.file.endswith("fixture_target.py")]
        with_vars = [e for e in line_evs if e.vars]
        self.assertTrue(with_vars, "변수 스냅샷이 있어야 한다")
        # total = 0 라인 실행 후엔 n 값이 보여야 하고, 루프 진행에 따라 total이 변한다
        totals = [e.vars.get("total") for e in with_vars if e.vars and "total" in e.vars]
        self.assertIn("0", totals)
        self.assertIn("3", totals)  # 0+1+2 = 3 누적

    def test_no_capture_vars_by_default(self):
        result = self._trace(fixture_target.helper, 2)
        self.assertTrue(all(e.vars is None for e in result.events))

    def test_multithread_capture_and_thread_local_depth(self):
        """monitoring은 전 스레드를 커버 — 여러 스레드 실행이 잡히고 깊이는 스레드별로 독립."""
        import threading
        seen = []

        def worker():
            fixture_target.helper(3)

        tracer = LineTracer([TESTS_DIR])
        tracer.start()
        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        fixture_target.helper(3)  # 메인 스레드도
        result = tracer.stop()
        del seen
        target_evs = [e for e in result.events if e.file.endswith("fixture_target.py")]
        # 4개 실행(스레드 3 + 메인 1) × 9라인 ≈ 36 — 스레드 실행이 유실 없이 잡혀야
        self.assertGreater(len(target_evs), 20,
                           "여러 스레드의 실행이 모두 캡처돼야 한다")

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
