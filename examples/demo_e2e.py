"""풀 E2E 자가 데모 — 실브라우저 클릭 → 백엔드 라인 캡처 → 산출물 양식까지 한 번에.

    python examples/demo_app.py --port 8977    # 터미널 1 (데모 백엔드)
    python examples/demo_e2e.py                # 터미널 2 (playwright 필요)

산출: .creator/journeys/live-demo.json + docs_out/live-demo/{test-report,screen-spec}.{md,html}
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from xgen_creator.bridge import BridgeSession
from xgen_creator.docgen import Journey, Step, render_form
from xgen_creator.link import resolve_element

BASE = "http://127.0.0.1:8977"
JOURNEY_ID = "live-demo"


def main() -> int:
    shot_dir = ROOT / ".creator/journeys" / JOURNEY_ID / "shots"
    raws = []
    with BridgeSession(BASE, trace_store=str(ROOT / ".creator/traces"),
                       shot_dir=shot_dir,
                       video_dir=ROOT / ".creator/journeys" / JOURNEY_ID / "video") as session:
        raws.append(session.step("goto", "/"))
        raws.append(session.step("click", "[data-testid=analyze-button]",
                                 note="분석 실행 — 백엔드 /api/analyze가 트레이스된다"))
    video_path = session.video_path

    steps = []
    for raw in raws:
        if raw.get("element"):
            raw["frontend_sources"] = resolve_element(
                raw["element"], [str(ROOT / "examples/demo_frontend")])
        steps.append(Step(**{k: v for k, v in raw.items()
                             if k in Step.__dataclass_fields__}))

    journey = Journey(id=JOURNEY_ID, title="Live Bridge 데모 여정", base_url=BASE,
                      created=datetime.now(timezone.utc).isoformat(),
                      video=video_path, steps=steps)
    jpath = journey.save(ROOT / ".creator/journeys" / f"{JOURNEY_ID}.json")
    print(f"여정 저장: {jpath}")
    print(f"수행 영상: {video_path or '(미녹화)'}")

    out_dir = ROOT / "docs_out" / JOURNEY_ID
    for form in ("test-report", "screen-spec"):
        for p in render_form(journey, form, out_dir):
            print(f"산출물: {p}")

    clicked = steps[-1]
    if clicked.backend:
        b = clicked.backend
        print(f"\n[증명] 클릭 → {b['method']} {b['path']} → {b['status']} · "
              f"실행 파일 {len(b['files'])}개 · 라인이벤트 {b['event_count']}건")
        for _kind, file, line, func, _depth in b["flow"][:12]:
            print(f"  {Path(file).name}:{line:<4} {func}")
        return 0
    print("\n[실패] 백엔드 트레이스 미확보 — 데모 서버가 떠 있는지 확인")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
