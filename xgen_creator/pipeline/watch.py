"""소스 스냅샷/변경 감지 — "소스가 바뀌면 여정을 다시 뛰고 산출물을 다시 만든다"의 눈.

mtime 스냅샷 비교(경량). 빌드 산출물·의존성 디렉토리는 걷지 않는다.
"""
from __future__ import annotations

import os
from pathlib import Path

SKIP_DIRS = {"node_modules", ".next", ".git", "dist", "build", "out", ".turbo",
             "coverage", "__pycache__", ".creator", "docs_out", ".pytest_cache"}
DEFAULT_EXTS = (".py", ".ts", ".tsx", ".jsx", ".js")


def snapshot(roots: list[str], exts: tuple[str, ...] = DEFAULT_EXTS) -> dict[str, float]:
    """{절대경로: mtime} — 대상 소스 파일 전량."""
    result: dict[str, float] = {}
    for root in roots:
        stack = [Path(root)]
        while stack:
            current = stack.pop()
            try:
                entries = list(os.scandir(current))
            except OSError:
                continue
            for entry in entries:
                name = entry.name
                if entry.is_dir(follow_symlinks=False):
                    if name not in SKIP_DIRS and not name.startswith("."):
                        stack.append(Path(entry.path))
                elif os.path.splitext(name)[1] in exts:
                    try:
                        result[entry.path] = entry.stat().st_mtime
                    except OSError:
                        continue
    return result


def changed_files(previous: dict[str, float], current: dict[str, float]) -> list[str]:
    """추가·수정·삭제된 파일 목록."""
    diffs = [path for path, mtime in current.items()
             if previous.get(path) != mtime]
    diffs += [path for path in previous if path not in current]
    return sorted(diffs)
