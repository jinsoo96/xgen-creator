"""사이드카 — 대상 ASGI 앱을 레포 수정 없이 미들웨어로 감싸 로컬 기동한다.

대상 앱의 venv 안에서 실행한다(그 venv에 xgen-creator를 pip install -e).

    creator sidecar main:app --dir /path/to/backend --port 8201 --roots /path/to/backend

앱 코드는 한 줄도 바꾸지 않는다 — import 후 밖에서 감싸는 것이 전부.
"""
from __future__ import annotations

import importlib
import os
import sys

from .trace.middleware import CreatorTraceMiddleware


def load_app(app_ref: str, app_dir: str):
    module_name, _, attr = app_ref.partition(":")
    attr = attr or "app"
    app_dir = os.path.abspath(app_dir)
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    os.chdir(app_dir)  # 상대경로 설정파일을 읽는 앱 대비
    module = importlib.import_module(module_name)
    return getattr(module, attr)


def run_sidecar(app_ref: str, app_dir: str, port: int, roots: list[str],
                trace_dir: str = ".creator/traces", host: str = "127.0.0.1",
                live_hub=None) -> None:
    app = load_app(app_ref, app_dir)
    wrapped = CreatorTraceMiddleware(app, roots=roots or [app_dir],
                                     trace_dir=trace_dir, live_hub=live_hub)
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("사이드카 실행에는 대상 venv에 uvicorn이 필요하다") from exc
    uvicorn.run(wrapped, host=host, port=port, log_level="warning")
