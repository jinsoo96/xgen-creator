"""라이브 소스 스크린 — 트레이서 이벤트를 SSE로 브라우저에 실시간 스트리밍.

"지금 백엔드가 어느 소스 라인을 돌고 있나"를 화면 옆에 흘려보내는 장치.
장착(데모/로컬 관측 전용):

    hub = LiveHub()
    app = CreatorTraceMiddleware(app, roots=[...], live_hub=hub)
    # ASGI 라우팅에서: if path == "/creator/events": await sse_endpoint(hub, ...)

트레이서 콜백은 이벤트루프 스레드에서 동기 호출되므로 put_nowait로만 적재하고,
느린 구독자는 이벤트를 버린다(dropped 카운트) — 관측이 대상 실행을 늦추면 안 된다.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .trace.tracer import TraceEvent

VIEWER_PATH = "/creator/live"
EVENTS_PATH = "/creator/events"


class LiveHub:
    def __init__(self, queue_size: int = 2000) -> None:
        self.queue_size = queue_size
        self._subscribers: set[asyncio.Queue] = set()
        self._source_cache: dict[str, list[str]] = {}
        self.dropped = 0

    def _line_text(self, file: str, line: int) -> str:
        lines = self._source_cache.get(file)
        if lines is None:
            try:
                lines = Path(file).read_text(encoding="utf-8",
                                             errors="replace").splitlines()
            except OSError:
                lines = []
            self._source_cache[file] = lines
        return lines[line - 1] if 0 < line <= len(lines) else ""

    def publish(self, ev: TraceEvent) -> None:
        """LineTracer on_event 콜백."""
        if not self._subscribers:
            return
        message = {"file": ev.file, "line": ev.line, "func": ev.func,
                   "kind": ev.kind, "text": self._line_text(ev.file, ev.line)}
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                self.dropped += 1

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self.queue_size)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)


async def sse_endpoint(hub: LiveHub, scope, receive, send,
                       heartbeat: float = 15.0) -> None:
    """ASGI SSE 핸들러 — 이벤트를 `data: {json}` 프레임으로 흘린다."""
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"text/event-stream"),
                            (b"cache-control", b"no-cache")]})
    queue = hub.subscribe()
    try:
        await send({"type": "http.response.body",
                    "body": b"event: hello\ndata: {}\n\n", "more_body": True})
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=heartbeat)
                frame = f"data: {json.dumps(message, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                frame = ": keepalive\n\n"
            await send({"type": "http.response.body",
                        "body": frame.encode("utf-8"), "more_body": True})
    except Exception:
        pass  # 구독자 이탈(연결 끊김)은 정상 종료
    finally:
        hub.unsubscribe(queue)


VIEWER_HTML = """<!doctype html><meta charset="utf-8"><title>CREATOR 소스 스크린</title>
<style>
body{font-family:Consolas,'D2Coding',monospace;background:#0f1720;color:#d8e2ef;
     margin:0;display:flex;flex-direction:column;height:100vh}
header{padding:.6rem 1rem;background:#16202e;color:#7ee787;font-weight:600}
header small{color:#5b6b7f;font-weight:400;margin-left:1rem}
#feed{flex:1;overflow-y:auto;padding:.6rem 1rem;font-size:.85rem;line-height:1.5}
.row{white-space:pre}
.file{color:#6cb6ff}
.line{color:#8a97a8}
.hot{color:#7ee787}
</style>
<header>XGEN CREATOR — 라이브 소스 스크린 <small id="status">연결 중…</small></header>
<div id="feed"></div>
<script>
const feed = document.getElementById('feed');
const status = document.getElementById('status');
let lastFile = null;
const es = new EventSource('/creator/events');
es.addEventListener('hello', () => { status.textContent = '연결됨 — 실행 대기'; });
es.onmessage = (e) => {
  const ev = JSON.parse(e.data);
  status.textContent = '실행 중: ' + ev.file.split(/[\\\\/]/).pop() + ':' + ev.line;
  if (ev.file !== lastFile) {
    lastFile = ev.file;
    const h = document.createElement('div');
    h.className = 'row file';
    h.textContent = '# ' + ev.file;
    feed.appendChild(h);
  }
  const row = document.createElement('div');
  row.className = 'row';
  row.innerHTML = '<span class="line">' + String(ev.line).padStart(5) +
                  ' |</span> <span class="hot"></span>';
  row.querySelector('.hot').textContent = ev.text;
  feed.appendChild(row);
  while (feed.childElementCount > 800) feed.removeChild(feed.firstChild);
  feed.scrollTop = feed.scrollHeight;
};
es.onerror = () => { status.textContent = '연결 끊김 — 재시도 중'; };
</script>"""
