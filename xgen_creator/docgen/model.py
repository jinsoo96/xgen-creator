"""증거 모델 — 여정(Journey) = 스텝(Step)의 연쇄. 브리지 출력과 1:1 호환.

산출물의 모든 문장은 이 모델의 필드로 소급 가능해야 한다(소스 기반 원칙).
증거가 없는 필드는 None으로 남긴다 — 채워 넣지 않는 것이 정직성이다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class Step:
    idx: int
    action: str                       # goto | click | fill | press
    selector: str | None = None
    value: str | None = None
    note: str = ""
    trace_id: str | None = None
    url_before: str | None = None
    url_after: str | None = None
    screenshot: str | None = None
    element: dict | None = None       # bridge가 캡처한 DOM 요소 정보
    frontend_sources: list = field(default_factory=list)  # link.resolve_element 결과
    api: list = field(default_factory=list)               # 액션 중 관측된 fetch/xhr
    backend: dict | None = None       # 미들웨어 payload (files/flow/slices/status...)


@dataclass
class Journey:
    id: str
    title: str
    base_url: str = ""
    created: str = ""                 # ISO8601 — 증거 수집 시각 (신선도 표기용)
    steps: list[Step] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Journey":
        steps = [Step(**s) for s in data.get("steps", [])]
        return cls(id=data["id"], title=data.get("title", data["id"]),
                   base_url=data.get("base_url", ""), created=data.get("created", ""),
                   steps=steps)

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1),
                        encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> "Journey":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
