"""ASGI 미들웨어 — 요청에 X-Creator-Trace 헤더가 있으면 그 요청의 백엔드 실행을 캡처한다.

장착은 로컬 구동 스크립트에서 1줄 (대상 레포에 커밋하지 않는다):

    app = CreatorTraceMiddleware(app, roots=["/path/to/backend/src"])

헤더 없는 요청은 오버헤드 0으로 통과. 트레이스는 전역 락으로 한 번에 하나만
(관측 도구지 프로덕션 프로파일러가 아니다). 락 대기 시간은 결과에 정직하게 기록한다.
"""
from __future__ import annotations

import threading
import time

from .slice import build_slices
from .store import TraceStore
from .tracer import LineTracer

TRACE_HEADER = b"x-creator-trace"


class CreatorTraceMiddleware:
    _lock = threading.Lock()

    def __init__(
        self,
        app,
        roots: list[str],
        trace_dir: str = ".creator/traces",
        max_events: int = 200_000,
        context: int = 2,
        flow_limit: int = 5000,
        live_hub=None,
    ) -> None:
        self.app = app
        self.roots = roots
        self.store = TraceStore(trace_dir)
        self.max_events = max_events
        self.context = context
        self.flow_limit = flow_limit
        self.live_hub = live_hub  # live.LiveHub — 이벤트를 SSE 구독자에 실시간 송출

    @staticmethod
    def _trace_id(scope) -> str | None:
        for name, value in scope.get("headers") or []:
            if name.lower() == TRACE_HEADER:
                return value.decode("latin-1").strip() or None
        return None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        trace_id = self._trace_id(scope)
        if trace_id is None:
            return await self.app(scope, receive, send)

        status_holder = {}

        async def send_wrap(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        on_event = self.live_hub.publish if self.live_hub is not None else None
        tracer = LineTracer(self.roots, max_events=self.max_events, on_event=on_event)
        wait_start = time.perf_counter()
        with self._lock:
            lock_wait_ms = round((time.perf_counter() - wait_start) * 1000, 2)
            run_start = time.perf_counter()
            tracer.start()
            try:
                await self.app(scope, receive, send_wrap)
            finally:
                result = tracer.stop()
                duration_ms = round((time.perf_counter() - run_start) * 1000, 2)

        files = result.executed_lines()
        payload = {
            "trace_id": trace_id,
            "method": scope.get("method"),
            "path": scope.get("path"),
            "status": status_holder.get("status"),
            "duration_ms": duration_ms,
            "lock_wait_ms": lock_wait_ms,
            "truncated": result.truncated,
            "event_count": len(result.events),
            "files": files,
            "flow": result.flow(self.flow_limit),
            "slices": [sl.to_dict() for sl in build_slices(files, context=self.context)],
        }
        self.store.save(trace_id, payload)
