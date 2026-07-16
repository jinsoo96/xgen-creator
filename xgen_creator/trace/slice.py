"""실행 슬라이스 — 트레이스 결과를 사람이 읽는 소스 발췌로 바꾼다.

실행된 라인은 '>' 마커, 앞뒤 context 라인은 공백 마커. 근접한 실행 구간은
하나의 발췌(excerpt)로 병합한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Excerpt:
    start: int
    end: int
    lines: list[tuple[int, bool, str]] = field(default_factory=list)  # (라인번호, 실행여부, 텍스트)


@dataclass
class FileSlice:
    file: str
    executed_count: int
    total_lines: int
    excerpts: list[Excerpt] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "executed_count": self.executed_count,
            "total_lines": self.total_lines,
            "excerpts": [
                {"start": e.start, "end": e.end,
                 "lines": [[no, hit, text] for no, hit, text in e.lines]}
                for e in self.excerpts
            ],
        }


def _merge_runs(lines: list[int], gap: int) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for n in lines:
        if runs and n - runs[-1][1] <= gap:
            runs[-1] = (runs[-1][0], n)
        else:
            runs.append((n, n))
    return runs


def build_slices(files: dict[str, list[int]], context: int = 2) -> list[FileSlice]:
    """files = {절대경로: [실행 라인...]} → 소스 발췌 목록. 읽기 실패 파일은 건너뛴다."""
    slices: list[FileSlice] = []
    for path, executed in sorted(files.items()):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                source = fh.read().splitlines()
        except OSError:
            continue
        hit = set(executed)
        excerpts = []
        for lo, hi in _merge_runs(sorted(hit), gap=context * 2 + 1):
            start = max(1, lo - context)
            end = min(len(source), hi + context)
            rows = [(no, no in hit, source[no - 1]) for no in range(start, end + 1)]
            excerpts.append(Excerpt(start, end, rows))
        slices.append(FileSlice(path, len(hit), len(source), excerpts))
    return slices


def render_slices_text(slices: list[FileSlice], marker: str = ">") -> str:
    """텍스트/마크다운 코드펜스용 렌더."""
    out: list[str] = []
    for sl in slices:
        out.append(f"# {sl.file}  (실행 {sl.executed_count}줄 / 전체 {sl.total_lines}줄)")
        for ex in sl.excerpts:
            out.append(f"  … {ex.start}–{ex.end} …")
            for no, is_hit, text in ex.lines:
                flag = marker if is_hit else " "
                out.append(f"{flag}{no:>6} | {text}")
        out.append("")
    return "\n".join(out)
