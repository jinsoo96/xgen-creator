"""creator CLI — trace / record / doc / routes / rules / roles / doctor."""
from __future__ import annotations

import argparse
import json
import runpy
import sys
from pathlib import Path

from . import __version__
from .config import load_config
from .link.routes_nextjs import scan_routes
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
    from .runner import record_journey
    record_journey(config, args.steps, base_url=args.base_url, journey_id=args.id,
                   title=args.title, headed=args.headed, video=args.video,
                   reroute=[tuple(r.split("=", 1)) for r in (args.reroute or [])])
    return 0


def _cmd_make(args, config) -> int:
    """"산출물 만들어줘" 원샷 — 러너 호출 (웹 콘솔과 동일 구현)."""
    from .runner import run_make
    report = run_make(config, steps=args.steps, base_url=args.base_url,
                      journey_id=args.id, title=args.title, headed=args.headed,
                      narrate=not args.no_narrate, pdf=args.pdf, out_dir=args.out,
                      goal=args.goal, pre_steps=args.pre_steps,
                      reroute=[tuple(r.split("=", 1)) for r in (args.reroute or [])])
    print("\n=== 산출물 ===")
    for path in report["outputs"] + report["pdfs"]:
        print(f"  {path}")
    traced = sum(1 for s in report["steps"] if s["backend"])
    print(f"영상: {report['video'] or '없음'} · 서술: {'포함' if report['narrated'] else '없음'} · "
          f"백엔드 증거 {traced}/{len(report['steps'])}")
    return 0


def _cmd_watch(args, config) -> int:
    """자동 재생성 파이프라인. 여정 변경 → 재렌더. --sources면 소스 변경 → 여정
    재수집(make)까지. Ctrl+C로 종료."""
    import time
    from .pipeline.watch import snapshot, changed_files
    journey_dir = Path(config["journey_dir"])
    seen: dict[str, float] = {}
    source_roots = ((config.get("backend_roots") or [])
                    + (config.get("frontend_roots") or [])) if args.sources else []
    src_snapshot = snapshot(source_roots) if source_roots else {}
    print(f"watch: 여정={journey_dir}"
          + (f" · 소스 {len(src_snapshot)}파일 감시" if source_roots else "")
          + f" (interval {args.interval}s, Ctrl+C 종료)", flush=True)
    try:
        while True:
            if source_roots:
                current = snapshot(source_roots)
                diffs = changed_files(src_snapshot, current)
                if diffs:
                    src_snapshot = current
                    print(f"소스 변경 {len(diffs)}건 감지 (예: {Path(diffs[0]).name}) "
                          f"→ 여정 재수집", flush=True)
                    from .runner import run_make
                    try:
                        run_make(config, steps=args.steps, goal=args.goal,
                                 narrate=False, pdf=args.pdf)
                    except Exception as exc:
                        print(f"  재수집 실패: {exc}")
            from .runner import journey_files
            changed = []
            for jp in journey_files(journey_dir):
                mtime = jp.stat().st_mtime
                if seen.get(str(jp)) != mtime:
                    seen[str(jp)] = mtime
                    changed.append(jp)
            for jp in changed:
                try:
                    for form in ("journey", "screen-spec", "test-report", "api-spec"):
                        report = build([jp], args.out or config["out_dir"], form=form)
                        if report["built"]:
                            print(f"  재생성 {jp.stem} [{form}]: "
                                  f"{len(report['outputs'])}파일", flush=True)
                except Exception as exc:  # 파일 하나가 감시 전체를 죽이면 안 된다
                    print(f"  재생성 실패 {jp.name}: {exc}")
            if changed:
                from .docgen.index_page import build_index
                build_index(args.out or config["out_dir"])
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nwatch 종료")
    return 0


def _cmd_debug(args, config) -> int:
    """트레이스 ID → 디버거 리플레이 HTML (line-by-line 열람). --open이면 브라우저로."""
    from .trace.store import TraceStore
    from .docgen.debug_view import build_debug_view
    store = TraceStore(config["trace_dir"])
    trace_id = args.trace_id
    if trace_id is None:  # 없으면 가장 최근 트레이스
        ids = store.list_ids()
        if not ids:
            print("트레이스가 없다 — 먼저 make/record/sidecar로 수집", file=sys.stderr)
            return 2
        newest = max(ids, key=lambda t: (store.root / f"{t}.json").stat().st_mtime)
        trace_id = newest
        print(f"최근 트레이스: {trace_id}")
    payload = store.load(trace_id)
    if payload is None:
        print(f"트레이스 없음: {trace_id}", file=sys.stderr)
        return 2
    if not payload.get("flow"):
        print(f"실행 흐름 없음(백엔드 미트레이스): {trace_id}", file=sys.stderr)
        return 2
    out = Path(args.out or (Path(config["out_dir"]) / "debug" / f"{trace_id}.html"))
    build_debug_view(payload, out)
    print(f"디버거 리플레이: {out}")
    print(f"  {payload.get('method')} {payload.get('path')} → {payload.get('status')} · "
          f"{payload.get('event_count')} 라인이벤트 · {payload.get('file_count')} 파일")
    if args.open:
        import webbrowser
        webbrowser.open(out.resolve().as_uri())
    return 0


def _cmd_export(args, config) -> int:
    """docs_out 인덱스 생성 — 게이트웨이(모노레포 프론트 등)가 그대로 서빙할 진입점."""
    from .docgen.index_page import build_index
    index = build_index(args.out or config["out_dir"])
    print(f"인덱스 생성: {index}")
    return 0


def _cmd_web(args, config) -> int:
    """산출물 콘솔 — "산출물 만들어줘" 버튼·실행 로그·라이브 소스 스크린·산출물 한 화면."""
    from .devserver import serve
    from .web import ConsoleApp
    if args.open:
        import threading
        import webbrowser
        threading.Timer(1.2, webbrowser.open,
                        [f"http://127.0.0.1:{args.port}/"]).start()
    serve(ConsoleApp(config), args.port)
    return 0


def _cmd_sidecar(args, config) -> int:
    """대상 ASGI 앱을 미들웨어로 감싸 기동 (대상 venv 안에서 실행)."""
    from .sidecar import run_sidecar
    live_hub = None
    if args.live:
        from .live import LiveHub
        live_hub = LiveHub()
    run_sidecar(args.app, args.dir, args.port,
                roots=args.roots or config.get("backend_roots") or [args.dir],
                trace_dir=args.trace_dir or config["trace_dir"],
                max_events=args.max_events, live_hub=live_hub)
    return 0


def _cmd_doc_build(args, config) -> int:
    from .runner import journey_files
    paths = [Path(p) for p in args.journey]
    if not paths:
        paths = journey_files(config["journey_dir"])
    if not paths:
        print("여정 JSON이 없다 — 먼저 `creator record`", file=sys.stderr)
        return 2
    report = build(paths, args.out or config["out_dir"],
                   html=not args.no_html, force=args.force, form=args.form)
    if args.pdf:
        from .docgen.pdf import html_to_pdf
        report["pdf"] = [str(html_to_pdf(p)) for p in report["outputs"]
                         if p.endswith(".html")]
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
    p.add_argument("--video", action="store_true", help="수행 영상(webm) 녹화")
    p.add_argument("--reroute", nargs="*", default=[],
                   help="'url글롭패턴=대상베이스' — 매칭 요청을 사이드카로 션트")

    p = sub.add_parser("make", help="원샷: 여정→서술→전 양식→PDF (산출물 만들어줘)")
    p.add_argument("--goal", default=None,
                   help="자연어 목표 — agent 모델이 멀티턴 관측 루프로 브라우저를 몬다"
                        " (보고→행동→다시 보고)")
    p.add_argument("--pre-steps", default=None,
                   help="goal 루프 전에 결정론으로 수행할 스텝 JSON (로그인 등 — "
                        "\"mask\": true 스텝의 값은 증거에도 남기지 않음)")
    p.add_argument("--steps", default=None, help="스텝 정의 JSON (없으면 최신 여정 재사용)")
    p.add_argument("--base-url", default=None)
    p.add_argument("--id", default=None)
    p.add_argument("--title", default=None)
    p.add_argument("--out", default=None)
    p.add_argument("--headed", action="store_true")
    p.add_argument("--reroute", nargs="*", default=[])
    p.add_argument("--no-narrate", action="store_true", help="LLM 서술 생략")
    p.add_argument("--pdf", action="store_true", help="html 산출물을 PDF로도 출력")

    p = sub.add_parser("web", help="산출물 콘솔 (버튼 하나로 make + 라이브 관측)")
    p.add_argument("--port", type=int, default=8990)
    p.add_argument("--open", action="store_true")

    p = sub.add_parser("watch", help="자동 재생성 (여정 변경→재렌더, --sources면 소스→재수집)")
    p.add_argument("--interval", type=float, default=2.0)
    p.add_argument("--out", default=None)
    p.add_argument("--sources", action="store_true",
                   help="backend/frontend_roots 소스 변경 시 여정 재수집(make)")
    p.add_argument("--steps", default=None, help="재수집에 쓸 스텝 정의")
    p.add_argument("--goal", default=None, help="재수집에 쓸 자연어 목표")
    p.add_argument("--pdf", action="store_true")

    p = sub.add_parser("debug", help="트레이스 → 디버거 리플레이 (line-by-line 열람)")
    p.add_argument("trace_id", nargs="?", default=None, help="트레이스 ID (없으면 최근)")
    p.add_argument("--out", default=None)
    p.add_argument("--open", action="store_true")

    p = sub.add_parser("export", help="docs_out 인덱스 생성 (게이트웨이 진입점)")
    p.add_argument("--out", default=None)

    p = sub.add_parser("sidecar", help="대상 ASGI 앱을 미들웨어로 감싸 기동")
    p.add_argument("app", help="모듈:앱 (예: main:app)")
    p.add_argument("--dir", required=True, help="대상 앱 루트 디렉토리")
    p.add_argument("--port", type=int, default=8201)
    p.add_argument("--roots", nargs="*", default=None)
    p.add_argument("--trace-dir", default=None)
    p.add_argument("--max-events", type=int, default=50_000,
                   help="요청당 라인이벤트 상한 (대형 앱 보호, 기본 50000)")
    p.add_argument("--live", action="store_true", help="라이브 소스스크린 허브 장착")

    p = sub.add_parser("doc", help="산출물")
    doc_sub = p.add_subparsers(dest="doc_command", required=True)
    p_build = doc_sub.add_parser("build", help="여정 → 문서 (변경분만)")
    p_build.add_argument("--journey", nargs="*", default=[])
    p_build.add_argument("--out", default=None)
    p_build.add_argument("--form", default="journey",
                         choices=["journey", "screen-spec", "test-report", "api-spec"],
                         help="산출물 양식 (기본 journey=챕터 문서)")
    p_build.add_argument("--no-html", action="store_true")
    p_build.add_argument("--pdf", action="store_true", help="html을 PDF로도 (Edge headless)")
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
    if args.command == "make":
        return _cmd_make(args, config)
    if args.command == "web":
        return _cmd_web(args, config)
    if args.command == "watch":
        return _cmd_watch(args, config)
    if args.command == "debug":
        return _cmd_debug(args, config)
    if args.command == "export":
        return _cmd_export(args, config)
    if args.command == "sidecar":
        return _cmd_sidecar(args, config)
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
