"""creator CLI — trace / record / doc / routes / rules / roles / doctor."""
from __future__ import annotations

import argparse
import json
import runpy
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .config import load_config
from .link.routes_nextjs import scan_routes
from .link.element import resolve_element
from .pipeline.build import build
from .pipeline.roles import load_roles
from .rules.loader import load_rules, compose_context
from .trace.slice import build_slices, render_slices_text
from .trace.store import TraceStore
from .trace.tracer import LineTracer


def _cmd_trace_run(args, config) -> int:
    """python 스크립트를 트레이서 아래서 실행하고 실행 슬라이스를 출력한다."""
    roots = args.roots or config.get("backend_roots") or [str(Path(args.script).resolve().parent)]
    tracer = LineTracer(roots, max_events=args.max_events)
    tracer.start()
    try:
        runpy.run_path(args.script, run_name="__main__")
    finally:
        result = tracer.stop()
    files = result.executed_lines()
    print(render_slices_text(build_slices(files, context=args.context)))
    print(f"이벤트 {len(result.events)}건, 파일 {len(files)}개"
          + (" (truncated)" if result.truncated else ""))
    return 0


def _cmd_record(args, config) -> int:
    """스텝 정의 JSON을 브리지로 실행해 여정 JSON을 만든다. (playwright 필요)"""
    from .bridge.driver import BridgeSession  # optional 의존 — 지연 임포트
    from .docgen.model import Journey, Step

    steps_def = json.loads(Path(args.steps).read_text(encoding="utf-8"))
    base_url = args.base_url or config.get("base_url")
    if not base_url:
        print("base_url 필요 (--base-url 또는 creator.config.json)", file=sys.stderr)
        return 2
    journey_id = args.id or Path(args.steps).stem
    shot_dir = Path(config["journey_dir"]) / journey_id / "shots"

    steps = []
    with BridgeSession(base_url, trace_store=config["trace_dir"],
                       shot_dir=shot_dir, headless=not args.headed) as session:
        for step_def in steps_def:
            raw = session.step(**step_def)
            if raw.get("element"):
                raw["frontend_sources"] = resolve_element(
                    raw["element"], config.get("frontend_roots") or [])
            steps.append(Step(**{k: v for k, v in raw.items()
                                 if k in Step.__dataclass_fields__}))
            print(f"  스텝 {raw['idx']}: {raw['action']} {raw.get('selector') or ''} "
                  f"→ 백엔드 트레이스 {'확보' if raw.get('backend') else '없음'}")

    journey = Journey(id=journey_id, title=args.title or journey_id, base_url=base_url,
                      created=datetime.now(timezone.utc).isoformat(), steps=steps)
    out = journey.save(Path(config["journey_dir"]) / f"{journey_id}.json")
    print(f"여정 저장: {out}")
    return 0


def _cmd_doc_build(args, config) -> int:
    paths = [Path(p) for p in args.journey]
    if not paths:
        paths = sorted(Path(config["journey_dir"]).glob("*.json"))
    if not paths:
        print("여정 JSON이 없다 — 먼저 `creator record`", file=sys.stderr)
        return 2
    report = build(paths, args.out or config["out_dir"],
                   html=not args.no_html, force=args.force, form=args.form)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


def _cmd_routes(args, config) -> int:
    roots = [args.root] if args.root else config.get("frontend_roots") or []
    for root in roots:
        routes = scan_routes(root)
        for route, rel in sorted(routes.items()):
            print(f"{route}  ←  {rel}")
        print(f"({root}: 라우트 {len(routes)}개)")
    return 0


def _cmd_rules(args, config) -> int:
    rules = load_rules(config.get("rules_dir", "rules"))
    if args.compose:
        print(compose_context(rules))
    else:
        for name, text in rules:
            print(f"- {name} ({len(text)}자)")
    return 0


def _cmd_roles(args, config) -> int:
    roles = load_roles(config)
    print(f"agent  (오케스트레이션): {roles.agent}")
    print(f"source (소스 서술/문서화): {roles.source}")
    return 0


def _cmd_doctor(args, config) -> int:
    """능력 자가검증 — 선언이 아니라 실동작으로."""
    ok = True

    def check(name: str, passed: bool, detail: str = ""):
        nonlocal ok
        ok = ok and passed
        print(f"  [{'OK' if passed else 'X '}] {name}" + (f" — {detail}" if detail else ""))

    print(f"xgen-creator {__version__} doctor")
    check("Python >= 3.10", sys.version_info >= (3, 10), sys.version.split()[0])

    # 트레이서 실동작: 자기 자신을 트레이스
    probe_lines: list[int] = []

    def _probe():
        x = 1
        return x + 1

    tracer = LineTracer([str(Path(__file__).parent)])
    tracer.start()
    _probe()
    result = tracer.stop()
    check("라인 트레이서 실동작", any(ev.kind == "line" for ev in result.events),
          f"{len(result.events)} 이벤트")

    store = TraceStore(config["trace_dir"])
    try:
        store.save("doctor-probe", {"ok": True})
        check("트레이스 저장소 쓰기", store.load("doctor-probe") is not None, str(store.root))
    except OSError as exc:
        check("트레이스 저장소 쓰기", False, str(exc))

    try:
        import playwright  # noqa: F401
        check("playwright (bridge)", True)
    except ImportError:
        check("playwright (bridge)", False, "optional — pip install xgen-creator[bridge]")

    check("frontend_roots 설정", bool(config.get("frontend_roots")),
          "요소→소스 리졸버에 필요")
    check("backend_roots 설정", bool(config.get("backend_roots")),
          "백엔드 트레이스 스코프에 필요")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows 콘솔(cp949) 대비
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass
    parser = argparse.ArgumentParser(prog="creator",
                                     description="XGEN CREATOR — 소스+실행 증거 기반 산출물 자동화")
    parser.add_argument("--config", default=None, help="creator.config.json 경로")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("trace", help="트레이서")
    trace_sub = p.add_subparsers(dest="trace_command", required=True)
    p_run = trace_sub.add_parser("run", help="스크립트를 트레이스하며 실행")
    p_run.add_argument("script")
    p_run.add_argument("--roots", nargs="*", default=None)
    p_run.add_argument("--context", type=int, default=2)
    p_run.add_argument("--max-events", type=int, default=200_000)

    p = sub.add_parser("record", help="브라우저 여정 기록 (playwright)")
    p.add_argument("--steps", required=True, help="스텝 정의 JSON")
    p.add_argument("--base-url", default=None)
    p.add_argument("--id", default=None)
    p.add_argument("--title", default=None)
    p.add_argument("--headed", action="store_true")

    p = sub.add_parser("doc", help="산출물")
    doc_sub = p.add_subparsers(dest="doc_command", required=True)
    p_build = doc_sub.add_parser("build", help="여정 → 문서 (변경분만)")
    p_build.add_argument("--journey", nargs="*", default=[])
    p_build.add_argument("--out", default=None)
    p_build.add_argument("--form", default="journey",
                         choices=["journey", "screen-spec", "test-report"],
                         help="산출물 양식 (기본 journey=챕터 문서)")
    p_build.add_argument("--no-html", action="store_true")
    p_build.add_argument("--force", action="store_true")

    p = sub.add_parser("routes", help="Next.js 라우트맵")
    p.add_argument("--root", default=None)

    p = sub.add_parser("rules", help="Rule 컨텍스트")
    p.add_argument("--compose", action="store_true")

    sub.add_parser("roles", help="모델 역할 (agent/source)")
    sub.add_parser("doctor", help="자가검증")

    args = parser.parse_args(argv)
    config = load_config(args.config)

    if args.command == "trace":
        return _cmd_trace_run(args, config)
    if args.command == "record":
        return _cmd_record(args, config)
    if args.command == "doc":
        return _cmd_doc_build(args, config)
    if args.command == "routes":
        return _cmd_routes(args, config)
    if args.command == "rules":
        return _cmd_rules(args, config)
    if args.command == "roles":
        return _cmd_roles(args, config)
    if args.command == "doctor":
        return _cmd_doctor(args, config)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
