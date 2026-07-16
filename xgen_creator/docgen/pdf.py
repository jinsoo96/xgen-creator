"""PDF 출력 — Edge headless print-to-pdf (Windows 기본 자산, 별도 의존성 없음)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

_EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_edge() -> str | None:
    for path in _EDGE_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


def html_to_pdf(html_path: str | Path, pdf_path: str | Path | None = None,
                timeout: float = 90.0) -> Path:
    edge = find_edge()
    if edge is None:
        raise RuntimeError("Edge(msedge.exe) 미발견 — PDF 출력은 Edge headless 필요")
    html_path = Path(html_path).resolve()
    pdf = Path(pdf_path) if pdf_path else html_path.with_suffix(".pdf")
    pdf.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [edge, "--headless", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={pdf.resolve()}", html_path.resolve().as_uri()],
        check=True, timeout=timeout,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not pdf.exists() or pdf.stat().st_size == 0:
        raise RuntimeError(f"PDF 생성 실패: {pdf}")
    return pdf
