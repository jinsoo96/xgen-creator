"""산출물 렌더러(html) — 여정 1건을 self-contained 단일 HTML로.

외부 리소스 없는 단일 파일이라 어디서든(모노레포 프론트 게이트웨이 포함) 그대로 서빙 가능.
스크린샷은 기본 base64 임베드(embed_shots=False면 상대경로 링크).
"""
from __future__ import annotations

import base64
import html
from pathlib import Path

from .model import Journey

_CSS = """
body{font-family:system-ui,'Segoe UI',sans-serif;max-width:960px;margin:2rem auto;
     padding:0 1rem;line-height:1.6;color:#1a2433;background:#fafbfc}
h1{border-bottom:2px solid #2b5aa8;padding-bottom:.3rem}
h2{color:#2b5aa8;margin-top:2.2rem}
code,pre{font-family:Consolas,'D2Coding',monospace;font-size:.85rem}
pre{background:#0f1720;color:#d8e2ef;padding:1rem;border-radius:8px;overflow-x:auto}
pre .hit{color:#7ee787;font-weight:600}
img{max-width:100%;border:1px solid #d3dce6;border-radius:8px}
.meta{color:#5b6b7f;font-size:.9rem}
.step{border:1px solid #e0e6ee;border-radius:10px;padding:1rem 1.4rem;margin:1.2rem 0;background:#fff}
.none{color:#8a97a8;font-style:italic}
"""


def _shot_tag(path: str | None, embed: bool) -> str:
    if not path:
        return '<p class="none">스크린샷 없음</p>'
    p = Path(path)
    if embed and p.exists():
        data = base64.b64encode(p.read_bytes()).decode("ascii")
        return f'<img src="data:image/png;base64,{data}" alt="{html.escape(p.name)}">'
    return f'<img src="shots/{html.escape(p.name)}" alt="{html.escape(p.name)}">'


def _slice_html(slices: list[dict]) -> str:
    rows: list[str] = []
    for sl in slices:
        rows.append(html.escape(f"# {sl['file']} (실행 {sl['executed_count']}줄)"))
        for ex in sl.get("excerpts", []):
            for no, hit, text in ex["lines"]:
                line = html.escape(f"{no:>6} | {text}")
                rows.append(f'<span class="hit">&gt;{line}</span>' if hit else f" {line}")
    return "<pre>" + "\n".join(rows) + "</pre>"


def render_journey_html(journey: Journey, out_path: str | Path,
                        embed_shots: bool = True) -> Path:
    parts: list[str] = [
        f"<style>{_CSS}</style>",
        f"<h1>{html.escape(journey.title)}</h1>",
        f'<p class="meta">여정 <code>{html.escape(journey.id)}</code>'
        f" · 수집 {html.escape(journey.created or '미기록')}"
        f" · 스텝 {len(journey.steps)}개</p>",
    ]
    for s in journey.steps:
        parts.append('<div class="step">')
        parts.append(f"<h2>스텝 {s.idx} — {html.escape(s.action)} "
                     f"<code>{html.escape(s.selector or s.value or '')}</code></h2>")
        if s.note:
            parts.append(f"<p>{html.escape(s.note)}</p>")
        parts.append(_shot_tag(s.screenshot, embed_shots))
        if s.url_before != s.url_after:
            parts.append(f"<p>화면 전환: <code>{html.escape(s.url_before or '')}</code> → "
                         f"<code>{html.escape(s.url_after or '')}</code></p>")
        if s.frontend_sources:
            items = "".join(f"<li><code>{html.escape(c['file'])}:{c['line']}</code> — "
                            f"{html.escape(c['reason'])}</li>" for c in s.frontend_sources)
            parts.append(f"<h3>UI 요소 → 프론트 소스</h3><ul>{items}</ul>")
        if s.api:
            items = "".join(f"<li><code>{html.escape(a.get('method',''))}</code> "
                            f"{html.escape(a.get('url',''))}</li>" for a in s.api)
            parts.append(f"<h3>API 호출</h3><ul>{items}</ul>")
        if s.backend:
            b = s.backend
            parts.append(f"<h3>실행된 백엔드 소스</h3>"
                         f'<p class="meta"><code>{html.escape(str(b.get("method")))} '
                         f'{html.escape(str(b.get("path")))}</code> → {b.get("status")} · '
                         f'{b.get("duration_ms")}ms</p>')
            parts.append(_slice_html(b.get("slices", [])))
        else:
            parts.append('<p class="none">백엔드 트레이스 증거 없음</p>')
        parts.append("</div>")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"<!doctype html><meta charset='utf-8'>"
                   f"<title>{html.escape(journey.title)}</title>" + "".join(parts),
                   encoding="utf-8")
    return out
