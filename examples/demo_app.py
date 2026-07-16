"""E2E 데모 — 버튼 클릭이 백엔드 Python을 line-by-line으로 건지는 걸 실브라우저로 증명.

    python examples/demo_app.py --port 8977
브라우저에서 버튼을 누르면 /api/analyze가 실행되고, X-Creator-Trace 헤더 덕에
미들웨어가 아래 비즈니스 로직의 실행 라인을 .creator/traces/<id>.json에 저장한다.
(실사용에선 브리지가 헤더를 주입하지만, 데모 페이지는 자체 JS로 주입한다)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from xgen_creator.trace import CreatorTraceMiddleware
from xgen_creator.live import LiveHub, sse_endpoint, VIEWER_HTML, VIEWER_PATH, EVENTS_PATH
from xgen_creator.devserver import serve


# --- 데모 비즈니스 로직 (트레이스 대상) --------------------------------------
def validate(numbers):
    if not numbers:
        raise ValueError("빈 입력")
    if len(numbers) > 100:
        raise ValueError("너무 많음")
    return [int(n) for n in numbers]


def classify(n):
    if n < 0:
        return "negative"
    if n % 2 == 0:
        return "even"
    return "odd"


def aggregate(labels):
    summary = {}
    for label in labels:
        summary[label] = summary.get(label, 0) + 1
    return summary


def analyze(numbers):
    values = validate(numbers)
    labels = [classify(v) for v in values]
    return {"count": len(values), "summary": aggregate(labels)}


def never_called():
    return "이 함수 본문은 트레이스에 잡히면 안 된다"


# --- 데모 페이지 + API -------------------------------------------------------
_PAGE = """<!doctype html><meta charset="utf-8"><title>CREATOR live demo</title>
<style>body{font-family:system-ui;max-width:640px;margin:3rem auto;line-height:1.6}
button{font-size:1.1rem;padding:.6rem 1.4rem;cursor:pointer}
pre{background:#0f1720;color:#d8e2ef;padding:1rem;border-radius:8px}</style>
<h1>XGEN CREATOR — Live Bridge 데모</h1>
<p>버튼을 누르면 <code>POST /api/analyze</code>가 호출되고, 백엔드 Python이
실제로 돌린 라인이 트레이스 저장소에 남는다.</p>
<button data-testid="analyze-button" onclick="run()">분석 실행</button>
<pre id="out">(대기)</pre>
<script>
async function run(){
  const headers = {'Content-Type':'application/json'};
  // 브리지가 컨텍스트 헤더로 주입하는 게 정상 경로 — 수동 열람시에만 자체 발급
  if (location.search.includes('manual')) headers['X-Creator-Trace'] = 'manual-' + Date.now();
  const res = await fetch('/api/analyze', {method:'POST', headers,
    body: JSON.stringify({numbers:[4,7,-2,10,3]})});
  const data = await res.json();
  document.getElementById('out').textContent = JSON.stringify(data, null, 1);
}
</script>"""


hub = LiveHub()


async def demo_app(scope, receive, send):
    if scope["type"] != "http":
        return
    if scope["path"] == EVENTS_PATH:
        return await sse_endpoint(hub, scope, receive, send)
    if scope["path"] == VIEWER_PATH:
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/html; charset=utf-8")]})
        await send({"type": "http.response.body", "body": VIEWER_HTML.encode()})
        return
    if scope["path"] == "/api/analyze":
        message = await receive()
        payload = json.loads(message.get("body") or b"{}")
        try:
            result = analyze(payload.get("numbers") or [])
            status, body = 200, json.dumps(result).encode()
        except ValueError as exc:
            status, body = 400, json.dumps({"error": str(exc)}).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body})
        return
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"text/html; charset=utf-8")]})
    await send({"type": "http.response.body", "body": _PAGE.encode()})


app = CreatorTraceMiddleware(demo_app, roots=[str(Path(__file__).parent)],
                             trace_dir=".creator/traces", live_hub=hub)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8977)
    serve(app, parser.parse_args().port)
