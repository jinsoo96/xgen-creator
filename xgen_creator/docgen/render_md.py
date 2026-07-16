"""산출물 렌더러(markdown) — 여정을 wikidocs식 챕터 문서로.

구성: SUMMARY.md(목차) + 00-overview.md(개요·화면 흐름) + NN-step-*.md(스텝별 증거).
모든 섹션은 증거 유무를 명시한다 — 캡처 못 한 것은 "증거 없음"으로 정직하게.
"""
from __future__ import annotations

from pathlib import Path

from .model import Journey, Step

_ACTION_KO = {"goto": "이동", "click": "클릭", "fill": "입력", "press": "키 입력"}


def _slice_text(slices: list[dict]) -> str:
    lines: list[str] = []
    for sl in slices:
        lines.append(f"# {sl['file']}  (실행 {sl['executed_count']}줄 / 전체 {sl['total_lines']}줄)")
        for ex in sl.get("excerpts", []):
            lines.append(f"  … {ex['start']}–{ex['end']} …")
            for no, hit, text in ex["lines"]:
                lines.append(f"{'>' if hit else ' '}{no:>6} | {text}")
        lines.append("")
    return "\n".join(lines)


def _step_md(step: Step) -> str:
    act = _ACTION_KO.get(step.action, step.action)
    target = step.selector or step.value or ""
    out: list[str] = [f"# 스텝 {step.idx} — {act} {target}".rstrip(), ""]
    if step.note:
        out += [step.note, ""]

    out += ["## 화면", ""]
    if step.screenshot:
        shot = Path(step.screenshot).name
        out += [f"![step-{step.idx}](shots/{shot})", ""]
    if step.url_before != step.url_after:
        out += [f"화면 전환: `{step.url_before}` → `{step.url_after}`", ""]
    else:
        out += [f"URL: `{step.url_after}`", ""]

    out += ["## UI 요소 → 프론트 소스", ""]
    if step.element:
        el = step.element
        desc = " ".join(filter(None, [
            f"`<{el.get('tag')}>`" if el.get("tag") else None,
            f"testid=`{el.get('testid')}`" if el.get("testid") else None,
            f"id=`{el.get('id')}`" if el.get("id") else None,
            f"텍스트 \"{el.get('text')}\"" if el.get("text") else None,
        ]))
        out += [f"- 요소: {desc or '(속성 미캡처)'}"]
    if step.frontend_sources:
        for cand in step.frontend_sources:
            out.append(f"- 소스 후보: `{cand['file']}:{cand['line']}` — {cand['reason']} (score {cand['score']})")
        out.append("")
    else:
        out += ["- 소스 후보: **증거 없음** (리졸버 미실행 또는 매칭 실패)", ""]

    out += ["## API 호출", ""]
    if step.api:
        for call in step.api:
            out.append(f"- `{call.get('method')}` {call.get('url')}")
        out.append("")
    else:
        out += ["- 관측된 fetch/xhr 없음", ""]

    out += ["## 실행된 백엔드 소스 (line-by-line 실측)", ""]
    backend = step.backend
    if backend:
        out += [
            f"- 요청: `{backend.get('method')} {backend.get('path')}` → 상태 {backend.get('status')}"
            f" · {backend.get('duration_ms')}ms"
            + (" · **truncated**" if backend.get("truncated") else ""),
            f"- 실행 파일 {len(backend.get('files', {}))}개, 라인 이벤트 {backend.get('event_count')}건",
            "",
            "```",
            _slice_text(backend.get("slices", [])).rstrip(),
            "```",
            "",
        ]
    else:
        out += ["- **증거 없음** — 이 스텝은 백엔드 트레이스가 캡처되지 않았다"
                " (백엔드 미호출이거나 미들웨어 미장착).", ""]
    return "\n".join(out)


def render_journey_md(journey: Journey, out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    # 00 개요 — 화면 흐름과 증거 신선도
    flow = []
    for s in journey.steps:
        if s.url_before != s.url_after and s.url_after:
            flow.append(f"- 스텝 {s.idx}: `{s.url_before}` → `{s.url_after}`")
    traced = sum(1 for s in journey.steps if s.backend)
    overview = [
        f"# {journey.title}",
        "",
        f"- 여정 ID: `{journey.id}`",
        f"- 대상: `{journey.base_url}`" if journey.base_url else "",
        f"- 증거 수집 시각: {journey.created or '(미기록)'}",
        f"- 스텝 {len(journey.steps)}개 · 백엔드 트레이스 확보 {traced}/{len(journey.steps)}",
        "",
        "> 이 문서는 소스와 실행 증거에서 자동 생성되었다. 모든 서술은 여정 JSON의",
        "> 필드로 소급 가능하며, 증거가 없는 항목은 '증거 없음'으로 표기된다.",
        "",
        "## 화면 흐름",
        "",
    ] + (flow or ["- (화면 전환 없음)"]) + [""]
    p = out / "00-overview.md"
    p.write_text("\n".join(x for x in overview if x is not None), encoding="utf-8")
    written.append(p)

    # NN 스텝 챕터
    for step in journey.steps:
        p = out / f"{step.idx:02d}-step.md"
        p.write_text(_step_md(step), encoding="utf-8")
        written.append(p)

    # SUMMARY (wikidocs/gitbook식 목차)
    summary = [f"# {journey.title}", "", "- [개요](00-overview.md)"]
    for step in journey.steps:
        act = _ACTION_KO.get(step.action, step.action)
        summary.append(f"- [스텝 {step.idx} — {act} {step.selector or step.value or ''}]"
                       f"({step.idx:02d}-step.md)")
    p = out / "SUMMARY.md"
    p.write_text("\n".join(summary) + "\n", encoding="utf-8")
    written.append(p)
    return written
