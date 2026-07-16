"""백엔드 로컬 구동 스크립트에 미들웨어를 장착하는 예시 (대상 레포에 커밋하지 않는다).

FastAPI든 Starlette든 순수 ASGI든 동일 — 앱을 1줄로 감싸면 끝.
    uvicorn examples.demo_asgi_wiring:app --port 8000
"""
from xgen_creator.trace import CreatorTraceMiddleware


async def plain_asgi_app(scope, receive, send):
    if scope["type"] != "http":
        return
    body = b'{"ok": true}'
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": body})


# roots = 트레이스할 백엔드 소스 루트(자기 레포 경로로 교체)
app = CreatorTraceMiddleware(plain_asgi_app, roots=["."])
