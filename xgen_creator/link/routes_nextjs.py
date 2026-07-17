"""Next.js App Router 라우트 맵 — URL 경로 ↔ page 소스 파일.

`**/app/**/page.{tsx,jsx,ts,js}` → 라우트. `(group)` 세그먼트 제거, `[param]` 유지.
"""
from __future__ import annotations

import re
from pathlib import Path

_PAGE_RE = re.compile(r"(?:^|/)app/(.*?)?page\.(tsx|jsx|ts|js)$")
_SKIP_DIRS = {"node_modules", ".next", ".git", "dist", "build", "out", ".turbo"}


def route_from_rel(rel: str) -> str | None:
    match = _PAGE_RE.search(rel.replace("\\", "/"))
    if not match:
        return None
    middle = (match.group(1) or "").strip("/")
    segments = [seg for seg in middle.split("/")
                if seg and not (seg.startswith("(") and seg.endswith(")")) and seg != "."]
    return "/" + "/".join(segments)


def scan_routes(frontend_root: str | Path) -> dict[str, str]:
    """{라우트: page 파일 상대경로}. 모노레포 전체를 걷되 빌드 산출물은 건너뛴다."""
    root = Path(frontend_root)
    routes: dict[str, str] = {}
    stack = [root]
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
            elif entry.name.startswith("page.") and entry.suffix in (".tsx", ".jsx", ".ts", ".js"):
                rel = str(entry.relative_to(root))
                route = route_from_rel(rel)
                if route is not None:
                    routes[route] = rel
    return routes


def match_route(routes: dict[str, str], url_path: str) -> tuple[str, str] | None:
    """실제 URL 경로를 라우트 패턴([param] 포함)에 매칭."""
    url_path = "/" + url_path.strip("/")
    if url_path in routes:
        return url_path, routes[url_path]
    url_segs = [s for s in url_path.split("/") if s]
    for route, rel in routes.items():
        segs = [s for s in route.split("/") if s]
        if len(segs) != len(url_segs):
            continue
        if all(s.startswith("[") or s == u for s, u in zip(segs, url_segs, strict=True)):
            return route, rel
    return None
