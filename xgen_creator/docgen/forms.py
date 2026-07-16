"""산출물 양식(form) — 증거(Journey)를 실무 산출물 문서 양식에 부어 넣는다.

wikidocs류 챕터 나열이 아니라 XGEN CREATOR 고유 양식: 모든 칸이 증거 필드로
소급되고, 증거가 없는 칸은 "증거 없음"으로 남는다(추정으로 채우지 않는다).

양식 레지스트리:
  screen-spec  화면정의서 — 화면 단위(진입경로·구성요소·소스근거·연동API·백엔드 처리)
  test-report  테스트결과서 — 스텝 단위(수행내용·결과·HTTP·판정·증거 + 실행소스 부록)

새 양식 추가 = 이 모듈에 (md, html) 렌더 함수 한 쌍 등록.
"""
from __future__ import annotations

import html as _html
from pathlib import Path

from .model import Journey, Step

_ACTION_KO = {"goto": "화면 이동", "click": "클릭", "fill": "값 입력", "press": "키 입력"}
NO_EVIDENCE = "증거 없음"


# ---------------------------------------------------------------- 공통 헬퍼
def _verdict(step: Step) -> tuple[str, str]:
    """(판정, 근거). 백엔드 증거가 있으면 HTTP로, 없으면 '수행됨'까지만 판정."""
    if step.backend:
        status = step.backend.get("status")
        if isinstance(status, int) and status < 400:
            return "성공", f"HTTP {status}"
        return "실패", f"HTTP {status}"
    return "수행됨", "백엔드 증거 없음"


def _elem_desc(step: Step) -> str:
    el = step.element or {}
    parts = [p for p in [
        f"<{el.get('tag')}>" if el.get("tag") else None,
        f"testid={el.get('testid')}" if el.get("testid") else None,
        f"\"{el.get('text')}\"" if el.get("text") else None,
    ] if p]
    return " ".join(parts) or (step.selector or "-")


def _src_desc(step: Step) -> str:
    if not step.frontend_sources:
        return NO_EVIDENCE
    best = step.frontend_sources[0]
    return f"{best['file']}:{best['line']} ({best['reason']})"


def _api_desc(step: Step) -> str:
    if not step.api:
        return "-"
    return "; ".join(f"{c.get('method')} {c.get('url')}" for c in step.api[:3])


def _backend_desc(step: Step) -> str:
    if not step.backend:
        return NO_EVIDENCE
    b = step.backend
    return (f"{b.get('method')} {b.get('path')} → {b.get('status')} · "
            f"파일 {len(b.get('files', {}))}개 · 라인이벤트 {b.get('event_count')}건")


def _screens(journey: Journey) -> list[tuple[str, list[Step]]]:
    """url_after 기준 화면 그룹(등장 순서 유지)."""
    order: list[str] = []
    groups: dict[str, list[Step]] = {}
    for step in journey.steps:
        url = step.url_after or step.url_before or "(unknown)"
        if url not in groups:
            order.append(url)
            groups[url] = []
        groups[url].append(step)
    return [(u, groups[u]) for u in order]


def _slice_block(backend: dict) -> str:
    rows: list[str] = []
    for sl in backend.get("slices", []):
        rows.append(f"# {sl['file']}  (실행 {sl['executed_count']}줄 / 전체 {sl['total_lines']}줄)")
        for ex in sl.get("excerpts", []):
            rows.append(f"  … {ex['start']}–{ex['end']} …")
            for no, hit, text in ex["lines"]:
                rows.append(f"{'>' if hit else ' '}{no:>6} | {text}")
    return "\n".join(rows)


# ---------------------------------------------------------------- 화면정의서
def _screen_spec_md(journey: Journey) -> str:
    out = [
        f"# 화면정의서 — {journey.title}",
        "",
        "| 문서 항목 | 내용 |",
        "|---|---|",
        f"| 여정 ID | `{journey.id}` |",
        f"| 대상 시스템 | {journey.base_url or NO_EVIDENCE} |",
        f"| 증거 수집 시각 | {journey.created or NO_EVIDENCE} |",
        "| 작성 방식 | XGEN CREATOR 자동 생성 (소스+실행 증거 기반) |",
        "",
    ]
    for i, (url, steps) in enumerate(_screens(journey), 1):
        first = steps[0]
        out += [f"## SCR-{i:02d} — `{url}`", ""]
        entry = (f"스텝 {first.idx}: {_ACTION_KO.get(first.action, first.action)}"
                 + (f" `{first.selector}`" if first.selector else ""))
        if first.url_before and first.url_before != url:
            entry += f" (이전 화면 `{first.url_before}`)"
        out += [f"- 진입 경로: {entry}"]
        shots = [s.screenshot for s in steps if s.screenshot]
        if shots:
            out += [f"- 대표 화면: ![SCR-{i:02d}](shots/{Path(shots[-1]).name})"]
        out += ["", "### 구성 요소 (관측분)", "",
                "| 요소 | 행위 | 프론트 소스 근거 | 연동 API | 백엔드 처리 |",
                "|---|---|---|---|---|"]
        for s in steps:
            out.append(f"| {_elem_desc(s)} | {_ACTION_KO.get(s.action, s.action)} "
                       f"| {_src_desc(s)} | {_api_desc(s)} | {_backend_desc(s)} |")
        out.append("")
    out += ["---", "",
            "> 본 문서는 실측 증거의 렌더이다. 관측되지 않은 요소는 표에 없으며, "
            f"확인 불가 칸은 \"{NO_EVIDENCE}\"으로 남긴다.", ""]
    return "\n".join(out)


# ---------------------------------------------------------------- 테스트결과서
def _test_report_md(journey: Journey) -> str:
    verdicts = [_verdict(s) for s in journey.steps]
    passed = sum(1 for v, _ in verdicts if v in ("성공", "수행됨"))
    failed = sum(1 for v, _ in verdicts if v == "실패")
    traced = sum(1 for s in journey.steps if s.backend)
    out = [
        f"# 테스트결과서 — {journey.title}",
        "",
        "| 문서 항목 | 내용 |",
        "|---|---|",
        f"| 문서 번호 | TR-{journey.id} |",
        f"| 대상 시스템 | {journey.base_url or NO_EVIDENCE} |",
        f"| 수행 시각 | {journey.created or NO_EVIDENCE} |",
        f"| 총 스텝 | {len(journey.steps)} (성공/수행 {passed} · 실패 {failed}) |",
        f"| 백엔드 증거 확보 | {traced}/{len(journey.steps)} 스텝 |",
        "| 수행 방식 | XGEN CREATOR Live Bridge (실브라우저 + 실행 트레이스) |",
    ] + ([f"| 수행 영상 | `{journey.video}` |"] if journey.video else []) + [
        "",
        "## 수행 결과",
        "",
        "| # | 수행 내용 | 대상 요소 | 화면 전환 | 판정 | 판정 근거 | 트레이스 |",
        "|---|---|---|---|---|---|---|",
    ]
    for s, (verdict, basis) in zip(journey.steps, verdicts):
        content = _ACTION_KO.get(s.action, s.action) + (f" `{s.value}`" if s.value and s.action == "fill" else "")
        if s.note:
            content += f" — {s.note}"
        transition = ("`" + (s.url_after or "") + "`") if s.url_before != s.url_after else "유지"
        out.append(f"| {s.idx} | {content} | {_elem_desc(s)} | {transition} "
                   f"| **{verdict}** | {basis} | `{s.trace_id or '-'}` |")
    out += ["", "## 부록 A — 스텝별 실행 소스 (line-by-line 실측)", ""]
    appended = False
    for s in journey.steps:
        if not s.backend:
            continue
        appended = True
        out += [f"### 스텝 {s.idx} — {s.backend.get('method')} {s.backend.get('path')}"
                f" ({s.backend.get('duration_ms')}ms)", "", "```",
                _slice_block(s.backend), "```", ""]
    if not appended:
        out += [f"({NO_EVIDENCE} — 백엔드 트레이스가 캡처된 스텝이 없다)", ""]
    return "\n".join(out)


# ---------------------------------------------------------------- HTML 공통
_FORM_CSS = """
body{font-family:'Segoe UI',system-ui,'Malgun Gothic',sans-serif;max-width:1000px;
     margin:2rem auto;padding:0 1.2rem;line-height:1.65;color:#1a2433;background:#fff}
h1{font-size:1.5rem;border-bottom:3px solid #2b5aa8;padding-bottom:.4rem}
h2{font-size:1.15rem;color:#2b5aa8;margin-top:2rem;border-left:4px solid #2b5aa8;padding-left:.6rem}
h3{font-size:1rem;margin-top:1.4rem}
table{border-collapse:collapse;width:100%;margin:.6rem 0;font-size:.9rem}
th,td{border:1px solid #c9d4e0;padding:.45rem .6rem;text-align:left;vertical-align:top}
th{background:#eef3f9;white-space:nowrap}
code{font-family:Consolas,'D2Coding',monospace;font-size:.85em;background:#f0f3f7;
     padding:.05rem .3rem;border-radius:4px}
pre{background:#0f1720;color:#d8e2ef;padding:1rem;border-radius:8px;overflow-x:auto;
    font-size:.8rem;line-height:1.45}
pre .hit{color:#7ee787;font-weight:600}
img{max-width:100%;border:1px solid #d3dce6;border-radius:8px;margin:.4rem 0}
.badge{display:inline-block;padding:.1rem .55rem;border-radius:999px;font-size:.8rem;font-weight:600}
.pass{background:#e6f4ea;color:#1e7e34}.fail{background:#fdecea;color:#c62828}
.info{background:#e8eef7;color:#2b5aa8}
.footnote{color:#5b6b7f;font-size:.85rem;border-top:1px solid #e0e6ee;margin-top:2rem;padding-top:.8rem}
@media print{body{margin:0;max-width:none}pre{white-space:pre-wrap}}
"""


def _esc(value) -> str:
    return _html.escape(str(value if value is not None else ""))


def _shell(title: str, body: list[str]) -> str:
    return (f"<!doctype html><meta charset='utf-8'><title>{_esc(title)}</title>"
            f"<style>{_FORM_CSS}</style>" + "".join(body))


def _slice_pre(backend: dict) -> str:
    rows: list[str] = []
    for sl in backend.get("slices", []):
        rows.append(_esc(f"# {sl['file']}  (실행 {sl['executed_count']}줄 / 전체 {sl['total_lines']}줄)"))
        for ex in sl.get("excerpts", []):
            for no, hit, text in ex["lines"]:
                row = _esc(f"{no:>6} | {text}")
                rows.append(f'<span class="hit">&gt;{row}</span>' if hit else f" {row}")
    return "<pre>" + "\n".join(rows) + "</pre>"


def _shot_img(steps: list[Step], embed: bool) -> str:
    import base64
    shots = [s.screenshot for s in steps if s.screenshot]
    if not shots:
        return ""
    p = Path(shots[-1])
    if embed and p.exists():
        data = base64.b64encode(p.read_bytes()).decode("ascii")
        return f'<img src="data:image/png;base64,{data}" alt="{_esc(p.name)}">'
    return f'<img src="shots/{_esc(p.name)}" alt="{_esc(p.name)}">'


def _screen_spec_html(journey: Journey, embed_shots: bool = True) -> str:
    body = [f"<h1>화면정의서 — {_esc(journey.title)}</h1>",
            "<table><tr><th>여정 ID</th><td><code>", _esc(journey.id), "</code></td></tr>",
            f"<tr><th>대상 시스템</th><td>{_esc(journey.base_url) or NO_EVIDENCE}</td></tr>",
            f"<tr><th>증거 수집 시각</th><td>{_esc(journey.created) or NO_EVIDENCE}</td></tr>",
            "<tr><th>작성 방식</th><td>XGEN CREATOR 자동 생성 (소스+실행 증거 기반)</td></tr></table>"]
    for i, (url, steps) in enumerate(_screens(journey), 1):
        body.append(f"<h2>SCR-{i:02d} — <code>{_esc(url)}</code></h2>")
        body.append(_shot_img(steps, embed_shots))
        body.append("<table><tr><th>요소</th><th>행위</th><th>프론트 소스 근거</th>"
                    "<th>연동 API</th><th>백엔드 처리</th></tr>")
        for s in steps:
            body.append(f"<tr><td>{_esc(_elem_desc(s))}</td>"
                        f"<td>{_esc(_ACTION_KO.get(s.action, s.action))}</td>"
                        f"<td>{_esc(_src_desc(s))}</td><td>{_esc(_api_desc(s))}</td>"
                        f"<td>{_esc(_backend_desc(s))}</td></tr>")
        body.append("</table>")
    body.append(f'<p class="footnote">본 문서는 실측 증거의 렌더이다. 관측되지 않은 요소는 '
                f'표에 없으며, 확인 불가 칸은 "{NO_EVIDENCE}"으로 남긴다.</p>')
    return _shell(f"화면정의서 — {journey.title}", body)


def _test_report_html(journey: Journey, embed_shots: bool = True) -> str:
    verdicts = [_verdict(s) for s in journey.steps]
    passed = sum(1 for v, _ in verdicts if v in ("성공", "수행됨"))
    failed = sum(1 for v, _ in verdicts if v == "실패")
    traced = sum(1 for s in journey.steps if s.backend)
    body = [f"<h1>테스트결과서 — {_esc(journey.title)}</h1>",
            f"<table><tr><th>문서 번호</th><td>TR-{_esc(journey.id)}</td></tr>",
            f"<tr><th>대상 시스템</th><td>{_esc(journey.base_url) or NO_EVIDENCE}</td></tr>",
            f"<tr><th>수행 시각</th><td>{_esc(journey.created) or NO_EVIDENCE}</td></tr>",
            f"<tr><th>총 스텝</th><td>{len(journey.steps)} "
            f'(<span class="badge pass">성공/수행 {passed}</span> '
            f'<span class="badge fail">실패 {failed}</span>)</td></tr>',
            f"<tr><th>백엔드 증거 확보</th><td>{traced}/{len(journey.steps)} 스텝</td></tr>"
            + (f"<tr><th>수행 영상</th><td><code>{_esc(journey.video)}</code></td></tr>"
               if journey.video else "")
            + "<tr><th>수행 방식</th><td>XGEN CREATOR Live Bridge (실브라우저 + 실행 트레이스)</td></tr></table>",
            "<h2>수행 결과</h2>",
            "<table><tr><th>#</th><th>수행 내용</th><th>대상 요소</th><th>화면 전환</th>"
            "<th>판정</th><th>판정 근거</th><th>트레이스</th></tr>"]
    for s, (verdict, basis) in zip(journey.steps, verdicts):
        badge = "pass" if verdict in ("성공",) else ("fail" if verdict == "실패" else "info")
        content = _ACTION_KO.get(s.action, s.action)
        if s.note:
            content += f" — {s.note}"
        transition = f"<code>{_esc(s.url_after)}</code>" if s.url_before != s.url_after else "유지"
        body.append(f"<tr><td>{s.idx}</td><td>{_esc(content)}</td>"
                    f"<td>{_esc(_elem_desc(s))}</td><td>{transition}</td>"
                    f'<td><span class="badge {badge}">{verdict}</span></td>'
                    f"<td>{_esc(basis)}</td><td><code>{_esc(s.trace_id or '-')}</code></td></tr>")
    body.append("</table>")
    shots = [s for s in journey.steps if s.screenshot]
    if shots:
        body.append("<h2>화면 증거</h2>")
        for s in shots:
            body.append(f"<h3>스텝 {s.idx}</h3>" + _shot_img([s], embed_shots))
    body.append("<h2>부록 A — 스텝별 실행 소스 (line-by-line 실측)</h2>")
    appended = False
    for s in journey.steps:
        if not s.backend:
            continue
        appended = True
        body.append(f"<h3>스텝 {s.idx} — <code>{_esc(s.backend.get('method'))} "
                    f"{_esc(s.backend.get('path'))}</code> ({s.backend.get('duration_ms')}ms)</h3>")
        body.append(_slice_pre(s.backend))
    if not appended:
        body.append(f'<p class="footnote">{NO_EVIDENCE} — 백엔드 트레이스가 캡처된 스텝이 없다.</p>')
    return _shell(f"테스트결과서 — {journey.title}", body)


# ---------------------------------------------------------------- 레지스트리
FORMS = {
    "screen-spec": {"md": _screen_spec_md, "html": _screen_spec_html, "이름": "화면정의서"},
    "test-report": {"md": _test_report_md, "html": _test_report_html, "이름": "테스트결과서"},
}


def render_form(journey: Journey, form: str, out_dir: str | Path,
                fmt: str = "both") -> list[Path]:
    if form not in FORMS:
        raise ValueError(f"미등록 양식 {form!r} — 사용 가능: {sorted(FORMS)}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    if fmt in ("md", "both"):
        p = out / f"{form}.md"
        p.write_text(FORMS[form]["md"](journey), encoding="utf-8")
        written.append(p)
    if fmt in ("html", "both"):
        p = out / f"{form}.html"
        p.write_text(FORMS[form]["html"](journey), encoding="utf-8")
        written.append(p)
    return written
