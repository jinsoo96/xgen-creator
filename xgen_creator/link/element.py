"""요소 → 프론트 소스 리졸버 — 클릭한 DOM 요소가 모노레포 어느 소스에서 왔는지 후보를 찾는다.

P0는 정적 텍스트 매칭(랭킹): data-testid 정확일치 > id > 표시 텍스트 > 클래스 토큰.
프로덕션 빌드에서 소스맵이 소실돼도 동작하는 최저선. dev 모드 React fiber 보조는 P1.
"""
from __future__ import annotations

from pathlib import Path

_SKIP_DIRS = {"node_modules", ".next", ".git", "dist", "build", "out", ".turbo", "coverage"}
_EXTS = (".tsx", ".jsx", ".ts", ".js")
_MAX_FILE_BYTES = 512 * 1024


def _iter_source_files(roots: list[str]):
    for root in roots:
        stack = [Path(root)]
        while stack:
            cur = stack.pop()
            try:
                entries = list(cur.iterdir())
            except OSError:
                continue
            for entry in entries:
                if entry.is_dir():
                    if entry.name not in _SKIP_DIRS and not entry.name.startswith("."):
                        stack.append(entry)
                elif entry.suffix in _EXTS:
                    yield entry


def _needles(element: dict) -> list[tuple[str, int, str]]:
    """(찾을 문자열, 점수, 이유) — 신뢰도 순."""
    needles: list[tuple[str, int, str]] = []
    if element.get("testid"):
        needles.append((f'data-testid="{element["testid"]}"', 100, "data-testid 정확일치"))
        needles.append((f"data-testid='{element['testid']}'", 100, "data-testid 정확일치"))
    if element.get("id"):
        needles.append((f'id="{element["id"]}"', 60, "id 일치"))
    text = element.get("text")
    if text and 2 <= len(text) <= 60 and "\n" not in text:
        needles.append((f">{text}<", 45, "표시 텍스트 일치"))
        needles.append((f'"{text}"', 35, "텍스트 리터럴 일치"))
    for cls in (element.get("classes") or [])[:5]:
        if len(cls) >= 6 and not cls.startswith(("css-", "_")):  # 유틸리티/해시 클래스 제외
            needles.append((f'"{cls}', 15, f"클래스 토큰 {cls}"))
    return needles


def resolve_element(element: dict, frontend_roots: list[str], limit: int = 5) -> list[dict]:
    """후보 [{file, line, score, reason}] 점수순. 증거 없으면 빈 목록(정직)."""
    needles = _needles(element)
    if not needles:
        return []
    candidates: dict[tuple[str, int], dict] = {}
    for path in _iter_source_files(frontend_roots):
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for needle, score, reason in needles:
            pos = content.find(needle)
            if pos < 0:
                continue
            line = content.count("\n", 0, pos) + 1
            key = (str(path), line)
            prev = candidates.get(key)
            if prev is None or prev["score"] < score:
                candidates[key] = {"file": str(path), "line": line,
                                   "score": score, "reason": reason}
    ranked = sorted(candidates.values(), key=lambda c: -c["score"])
    return ranked[:limit]
