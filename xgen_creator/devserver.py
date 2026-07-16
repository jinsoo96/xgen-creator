"""초미니 ASGI 서버 — 콘솔/데모/로컬 관측용, 의존성 0. 프로덕션 용도 아님."""
from __future__ import annotations

import asyncio


async def _handle(reader, writer, app):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = await reader.read(65536)
        if not chunk:
            writer.close()
            return
        data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    method, target, _ = lines[0].split(" ", 2)
    headers = []
    for line in lines[1:]:
        key, _, value = line.partition(":")
        headers.append((key.strip().lower().encode("latin-1"),
                        value.strip().encode("latin-1")))
    length = int(dict(headers).get(b"content-length", b"0") or 0)
    while len(body) < length:
        body += await reader.read(65536)
    path, _, query = target.partition("?")
    scope = {"type": "http", "method": method, "path": path,
             "query_string": query.encode("latin-1"), "headers": headers}

    consumed = False

    async def receive():
        nonlocal consumed
        if consumed:
            return {"type": "http.disconnect"}
        consumed = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            writer.write(f"HTTP/1.1 {message['status']} OK\r\n".encode("latin-1"))
            for key, value in message.get("headers") or []:
                writer.write(key + b": " + value + b"\r\n")
            writer.write(b"connection: close\r\n\r\n")
        elif message["type"] == "http.response.body":
            writer.write(message.get("body", b""))
            if not message.get("more_body"):
                await writer.drain()
                writer.close()

    try:
        await app(scope, receive, send)
    except Exception:
        try:
            writer.close()
        except Exception:
            pass


def serve(app, port: int, host: str = "127.0.0.1") -> None:
    async def main():
        server = await asyncio.start_server(
            lambda r, w: _handle(r, w, app), host, port)
        print(f"xgen-creator devserver: http://{host}:{port}", flush=True)
        async with server:
            await server.serve_forever()

    asyncio.run(main())
