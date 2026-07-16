"""트레이스 저장소 — 미들웨어(쓰기)와 브리지(읽기)가 파일시스템으로 공유한다.

같은 머신에서 백엔드와 브리지가 돌아가는 로컬 관측 전제(P0). 원격 분리는 P1에서
HTTP 조회 엔드포인트로 확장한다.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]")


def sanitize_id(trace_id: str) -> str:
    return _SAFE_ID.sub("", trace_id)[:80] or "invalid"


class TraceStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, trace_id: str) -> Path:
        return self.root / f"{sanitize_id(trace_id)}.json"

    def save(self, trace_id: str, payload: dict) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(trace_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False,
                                  separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, path)  # 원자적 교체 — 브리지가 반쯤 쓴 파일을 읽지 않도록
        return path

    def load(self, trace_id: str) -> dict | None:
        path = self._path(trace_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def wait(self, trace_id: str, timeout: float = 10.0, poll: float = 0.15) -> dict | None:
        """응답이 브라우저에 먼저 도착하고 저장이 뒤따르는 시차를 흡수한다."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = self.load(trace_id)
            if found is not None:
                return found
            time.sleep(poll)
        return None

    def list_ids(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.stem for p in self.root.glob("*.json"))
