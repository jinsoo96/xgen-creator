"""라인 트레이서 — UI 액션이 유발한 Python 실행을 "돌아간 만큼" 라인 단위로 건진다.

백엔드 2종(인터페이스 동일):
- **monitoring** (기본, py3.12+): sys.monitoring(PEP 669). 스코프 밖 코드 위치는
  DISABLE로 영구 배제돼 대형 실앱에서도 오버헤드가 낮다.
- **settrace** (폴백/구버전): sys.settrace. 스코프 밖은 call 시점에 배제.

on_event 콜백으로 라이브 스트리밍(SSE 등)에 연결할 수 있다.
"""
from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class TraceEvent:
    file: str
    line: int
    func: str
    depth: int
    kind: str = "line"  # line | call | return
    vars: dict | None = None  # 라인 실행 후 지역변수 스냅샷 (capture_vars 시)

    def to_tuple(self) -> tuple:
        # 6-튜플 — 마지막이 vars(없으면 None). 소비자는 5개까지 언팩 후 [5]로 vars 접근.
        return (self.kind, self.file, self.line, self.func, self.depth, self.vars)


@dataclass
class TraceResult:
    events: list[TraceEvent] = field(default_factory=list)
    truncated: bool = False

    def executed_lines(self) -> dict[str, list[int]]:
        """파일별 실행 라인(정렬·중복 제거)."""
        out: dict[str, set[int]] = {}
        for ev in self.events:
            if ev.kind == "line":
                out.setdefault(ev.file, set()).add(ev.line)
        return {f: sorted(lines) for f, lines in out.items()}

    def flow(self, limit: int = 5000) -> list[tuple]:
        """실행 순서 그대로의 흐름 (라인 이벤트만)."""
        rows = [ev.to_tuple() for ev in self.events if ev.kind == "line"]
        return rows[:limit]

    def to_dict(self, flow_limit: int = 5000) -> dict:
        return {
            "truncated": self.truncated,
            "event_count": len(self.events),
            "files": self.executed_lines(),
            "flow": self.flow(flow_limit),
        }


class LineTracer:
    """스코프 필터링 라인 트레이서. `with LineTracer(roots) as t:` 또는 start()/stop().

    roots가 비어 있으면 아무것도 기록하지 않는다(안전 기본값).
    """

    def __init__(
        self,
        roots: list[str],
        on_event: Callable[[TraceEvent], None] | None = None,
        max_events: int = 200_000,
        record_calls: bool = False,
        backend: str = "auto",  # auto | monitoring | settrace
        max_seconds: float | None = None,
        capture_vars: bool = False,
        max_vars: int = 12,
        var_repr_limit: int = 100,
    ) -> None:
        self.roots = [os.path.normcase(os.path.abspath(r)) for r in roots if r]
        self.on_event = on_event
        self.max_events = max_events
        self.record_calls = record_calls
        # data flow — 라인마다 지역변수 값을 스냅샷(오버헤드 커서 opt-in)
        self.capture_vars = capture_vars
        self.max_vars = max_vars
        self.var_repr_limit = var_repr_limit
        # 벽시계 예산 — 아무리 큰 핸들러라도 이 시간이 지나면 트레이싱을 멈춰
        # 요청이 완료되게 한다(관측이 대상을 행시키지 않도록). None이면 미적용.
        self.max_seconds = max_seconds
        self._deadline: float | None = None
        self.timed_out = False
        monitoring_ok = hasattr(sys, "monitoring")
        if backend == "auto":
            backend = "monitoring" if monitoring_ok else "settrace"
        if backend == "monitoring" and not monitoring_ok:
            backend = "settrace"
        self.backend = backend
        self.result = TraceResult()
        self._scope_cache: dict[str, str | None] = {}
        self._tls = threading.local()   # 호출 깊이를 스레드별로 — 멀티스레드 스택 정확도
        self._record_lock = threading.Lock()  # 여러 스레드가 events에 동시 append 대비
        self._active = False
        self._prev_trace = None
        self._tool_id: int | None = None

    # 호출 깊이 = 스레드-로컬 (monitoring은 전 스레드 콜백을 부르므로 스레드마다 독립)
    @property
    def _depth(self) -> int:
        return getattr(self._tls, "depth", 0)

    @_depth.setter
    def _depth(self, value: int) -> None:
        self._tls.depth = value

    # -- 변수 스냅샷 ---------------------------------------------------------
    def _snapshot(self, frame) -> dict | None:
        """프레임의 지역변수 {이름: repr} — 개수·길이 제한, repr 실패는 건너뛴다."""
        if frame is None:
            return None
        out: dict[str, str] = {}
        try:
            names = frame.f_code.co_varnames[: frame.f_code.co_argcount + 40]
            local = frame.f_locals
        except Exception:
            return None
        for name in names:
            if name.startswith("__") or name not in local:
                continue
            try:
                text = repr(local[name])
            except Exception:
                text = "<repr 실패>"
            if len(text) > self.var_repr_limit:
                text = text[: self.var_repr_limit] + "…"
            out[name] = text
            if len(out) >= self.max_vars:
                break
        return out or None

    def _mon_frame(self, code):
        """monitoring 콜백에서 감시 중인 프레임을 찾는다(콜백 프레임 위)."""
        frame = sys._getframe(2)  # _mon_frame + 콜백(_mon_line) 건너뛰기
        for _ in range(4):
            if frame is None:
                return None
            if frame.f_code is code:
                return frame
            frame = frame.f_back
        return None

    # -- 스코프 판정 ---------------------------------------------------------
    def _scoped(self, filename: str) -> str | None:
        """대상이면 정규화된 절대경로, 아니면 None."""
        cached = self._scope_cache.get(filename, "")
        if cached != "":
            return cached
        resolved: str | None = None
        if filename and not filename.startswith("<"):
            norm = os.path.normcase(os.path.abspath(filename))
            for root in self.roots:
                if norm.startswith(root):
                    resolved = os.path.abspath(filename)
                    break
        self._scope_cache[filename] = resolved
        return resolved

    # -- trace 콜백 ----------------------------------------------------------
    def _record(self, ev: TraceEvent) -> None:
        with self._record_lock:  # 멀티스레드 동시 append 안전
            n = len(self.result.events)
            if n >= self.max_events:
                self.result.truncated = True
                self._active = False
                return
            # 벽시계 예산 초과 시 즉시 중단 (512 이벤트마다 검사 — 시계 오버헤드 최소화)
            if self._deadline is not None and n % 512 == 0 and time.monotonic() > self._deadline:
                self.result.truncated = True
                self.timed_out = True
                self._active = False
                return
            self.result.events.append(ev)
        if self.on_event is not None:
            # 관측 콜백 실패가 대상 실행을 깨면 안 된다
            with contextlib.suppress(Exception):
                self.on_event(ev)

    def _global_trace(self, frame, event, arg):
        if not self._active or event != "call":
            return None
        path = self._scoped(frame.f_code.co_filename)
        if path is None:
            return None
        self._depth += 1
        if self.record_calls:
            self._record(TraceEvent(path, frame.f_lineno, frame.f_code.co_name,
                                    self._depth, "call"))
        return self._local_trace

    def _local_trace(self, frame, event, arg):
        if not self._active:
            return None
        if event == "line":
            path = self._scoped(frame.f_code.co_filename)
            if path is not None:
                snap = self._snapshot(frame) if self.capture_vars else None
                self._record(TraceEvent(path, frame.f_lineno, frame.f_code.co_name,
                                        self._depth, "line", snap))
        elif event == "return":
            if self.record_calls:
                path = self._scoped(frame.f_code.co_filename)
                if path is not None:
                    self._record(TraceEvent(path, frame.f_lineno, frame.f_code.co_name,
                                            self._depth, "return"))
            self._depth = max(0, self._depth - 1)
        return self._local_trace

    # -- sys.monitoring 백엔드 (PEP 669) --------------------------------------
    def _mon_line(self, code, line):
        mon = sys.monitoring
        if not self._active:
            return mon.DISABLE
        path = self._scoped(code.co_filename)
        if path is None:
            return mon.DISABLE  # 스코프 밖 위치는 영구 배제 — 저오버헤드의 핵심
        snap = self._snapshot(self._mon_frame(code)) if self.capture_vars else None
        self._record(TraceEvent(path, line, code.co_name, self._depth, "line", snap))
        return None

    def _mon_start(self, code, offset):
        mon = sys.monitoring
        if not self._active:
            return mon.DISABLE
        path = self._scoped(code.co_filename)
        if path is None:
            return mon.DISABLE
        self._depth += 1
        if self.record_calls:
            self._record(TraceEvent(path, code.co_firstlineno, code.co_name,
                                    self._depth, "call"))
        return None

    def _mon_return(self, code, offset, retval):
        if self._scoped(code.co_filename) is not None:
            if self.record_calls:
                self._record(TraceEvent(code.co_filename, code.co_firstlineno,
                                        code.co_name, self._depth, "return"))
            self._depth = max(0, self._depth - 1)
        return None

    def _mon_unwind(self, code, offset, exc):
        # 예외로 함수가 빠져나갈 때 — PY_RETURN은 안 불리므로 여기서 깊이를 줄여야
        # 예외 이후 콜스택이 부풀지 않는다.
        if self._scoped(code.co_filename) is not None:
            self._depth = max(0, self._depth - 1)
        return None

    def _start_monitoring(self) -> bool:
        mon = sys.monitoring
        for candidate in range(6):
            try:
                mon.use_tool_id(candidate, "xgen-creator")
                self._tool_id = candidate
                break
            except ValueError:
                continue
        if self._tool_id is None:
            return False  # 도구 슬롯 소진 — settrace 폴백
        events = (mon.events.LINE | mon.events.PY_START
                  | mon.events.PY_RETURN | mon.events.PY_UNWIND)
        mon.register_callback(self._tool_id, mon.events.LINE, self._mon_line)
        mon.register_callback(self._tool_id, mon.events.PY_START, self._mon_start)
        mon.register_callback(self._tool_id, mon.events.PY_RETURN, self._mon_return)
        mon.register_callback(self._tool_id, mon.events.PY_UNWIND, self._mon_unwind)
        mon.set_events(self._tool_id, events)
        mon.restart_events()  # 이전 세션의 DISABLE 잔재 해제
        return True

    def _stop_monitoring(self) -> None:
        mon = sys.monitoring
        mon.set_events(self._tool_id, 0)
        for event in (mon.events.LINE, mon.events.PY_START,
                      mon.events.PY_RETURN, mon.events.PY_UNWIND):
            mon.register_callback(self._tool_id, event, None)
        mon.free_tool_id(self._tool_id)
        self._tool_id = None

    # -- 수명 ---------------------------------------------------------------
    def start(self) -> None:
        self._active = True
        if self.max_seconds is not None:
            self._deadline = time.monotonic() + self.max_seconds
        if self.backend == "monitoring" and self._start_monitoring():
            return
        self.backend = "settrace"
        self._prev_trace = sys.gettrace()
        threading.settrace(self._global_trace)
        sys.settrace(self._global_trace)

    def stop(self) -> TraceResult:
        self._active = False
        if self._tool_id is not None:
            self._stop_monitoring()
        else:
            sys.settrace(self._prev_trace)
            threading.settrace(self._prev_trace)  # None이면 해제
        return self.result

    def __enter__(self) -> LineTracer:
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
