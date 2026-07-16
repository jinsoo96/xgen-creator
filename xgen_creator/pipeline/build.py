"""빌드 파이프라인 — 여정 JSON을 산출물로, 변경된 것만 다시.

여정 파일 해시를 상태 파일에 기록해 두고, 바뀐 여정만 재렌더한다(md + html).
소스가 바뀌어 여정을 재수집하면 해시가 바뀌므로 자동으로 재생성 대상이 된다.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..docgen.model import Journey
from ..docgen.render_md import render_journey_md
from ..docgen.render_html import render_journey_html


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def build(
    journey_paths: list[str | Path],
    out_dir: str | Path,
    state_file: str | Path = ".creator/build-state.json",
    html: bool = True,
    force: bool = False,
) -> dict:
    """반환: {built: [여정id...], skipped: [...], outputs: [경로...]}"""
    state_path = Path(state_file)
    state: dict = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}

    report = {"built": [], "skipped": [], "outputs": []}
    for jp in journey_paths:
        jp = Path(jp)
        digest = _hash_file(jp)
        journey = Journey.load(jp)
        if not force and state.get(journey.id) == digest:
            report["skipped"].append(journey.id)
            continue
        chapter_dir = Path(out_dir) / journey.id
        written = render_journey_md(journey, chapter_dir)
        if html:
            written.append(render_journey_html(journey, chapter_dir / f"{journey.id}.html"))
        state[journey.id] = digest
        report["built"].append(journey.id)
        report["outputs"] += [str(p) for p in written]

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    return report
