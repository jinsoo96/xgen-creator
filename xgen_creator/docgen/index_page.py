"""산출물 인덱스 — docs_out 전체를 훑어 단일 index.html 목록 페이지를 만든다.

self-contained라 그대로 서빙 가능 — 모노레포 프론트를 게이트웨이로 쓸 때의 진입점.
"""
from __future__ import annotations

import html
from pathlib import Path

_LABELS = {"screen-spec": "화면정의서", "test-report": "테스트결과서",
           "SUMMARY": "챕터 목차"}
_CSS = """
body{font-family:'Segoe UI','Malgun Gothic',sans-serif;background:#0d1420;color:#d8e2ef;
     max-width:1080px;margin:2.5rem auto;padding:0 1.2rem}
h1{font-size:1.6rem;border-bottom:3px solid #2b5aa8;padding-bottom:.4rem}
p.sub{color:#8a97a8}
.card{background:#0a0f16;border:1px solid #223247;border-radius:12px;padding:1.1rem 1.4rem;
      margin:1rem 0}
.card h2{font-size:1.1rem;color:#6cb6ff;margin:0 0 .6rem}
.links a{display:inline-block;background:#111b2a;border:1px solid #2b3d55;border-radius:8px;
         padding:.35rem .8rem;margin:.2rem .3rem .2rem 0;color:#d8e2ef;text-decoration:none;
         font-size:.85rem}
.links a:hover{border-color:#2b5aa8}
.links a.pdf{color:#7ee787}
"""


def build_index(out_dir: str | Path) -> Path:
    out = Path(out_dir)
    cards: list[str] = []
    for folder in sorted(p for p in out.iterdir() if p.is_dir()):
        files = sorted(folder.glob("*.*"))
        if not files:
            continue
        links = []
        for f in files:
            if f.suffix not in (".html", ".pdf", ".md"):
                continue
            label = _LABELS.get(f.stem, f.stem)
            cls = ' class="pdf"' if f.suffix == ".pdf" else ""
            links.append(f'<a href="{folder.name}/{f.name}"{cls}>'
                         f"{html.escape(label)}{f.suffix}</a>")
        cards.append(f'<div class="card"><h2>{html.escape(folder.name)}</h2>'
                     f'<div class="links">{"".join(links)}</div></div>')
    page = (f"<!doctype html><meta charset='utf-8'><title>XGEN CREATOR 산출물</title>"
            f"<style>{_CSS}</style><h1>XGEN CREATOR 산출물</h1>"
            f"<p class='sub'>소스+실행 증거에서 자동 생성 · 여정 {len(cards)}건</p>"
            + "".join(cards))
    index = out / "index.html"
    index.write_text(page, encoding="utf-8")
    return index
