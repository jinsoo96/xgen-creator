"""make 러너 — "산출물 만들어줘" 파이프라인의 단일 구현 (CLI와 웹 콘솔이 공유).

여정 확보(기존 재사용 또는 신규 기록) → LLM 서술(선택) → 전 양식 → PDF(선택).
log 콜백으로 진행 로그를 어느 표면(터미널·웹)으로든 흘린다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable

from .docgen.model import Journey, Step
from .link.element import resolve_element
from .pipeline.build import build
from .pipeline.roles import load_roles
from .rules.loader import load_rules, compose_context

FORMS_ALL = ("journey", "screen-spec", "test-report", "api-spec")


def journey_files(journey_dir: str | Path) -> list[Path]:
    """여정 JSON만 — 계획 파일(*.plan.json) 등 비여정 JSON은 제외."""
    return [p for p in sorted(Path(journey_dir).glob("*.json"))
            if not p.name.endswith(".plan.json")]


def _finalize_steps(config: dict, raws: list[dict]) -> list[Step]:
    steps = []
    for raw in raws:
        if raw.get("element"):
            raw["frontend_sources"] = resolve_element(
                raw["element"], config.get("frontend_roots") or [])
        steps.append(Step(**{k: v for k, v in raw.items()
                             if k in Step.__dataclass_fields__}))
    return steps


def record_goal_journey(config: dict, goal: str, base_url: str | None = None,
                        journey_id: str = "goal", title: str | None = None,
                        headed: bool = False, max_turns: int = 8,
                        reroute: list | None = None, extra_headers: dict | None = None,
                        pre_steps: str | Path | None = None, on_frame=None,
                        log: Callable[[str], None] = print) -> Path:
    """멀티턴 관측 루프 — agent가 화면 변화를 보며 스텝을 스스로 밟는다.

    pre_steps: 루프 전에 결정론으로 수행할 스텝 JSON(로그인 등 — 자격은 LLM에 안 보낸다).
    """
    from .agentloop import run_goal_loop
    from .bridge.driver import BridgeSession
    from .llm import LLMClient

    client = LLMClient.from_env(config)
    if client is None:
        raise RuntimeError("goal 수행에는 LLM 엔드포인트가 필요하다 (llm_base_url)")
    base_url = base_url or config.get("base_url")
    if not base_url:
        raise RuntimeError("base_url 필요")
    roles = load_roles(config)
    rules_context = compose_context(load_rules(config.get("rules_dir", "rules")))
    journey_root = Path(config["journey_dir"]) / journey_id

    log(f"관측 루프 시작: \"{goal}\" (agent: {roles.agent}, 최대 {max_turns}턴)")
    with BridgeSession(base_url, trace_store=config["trace_dir"],
                       shot_dir=journey_root / "shots", headless=not headed,
                       video_dir=journey_root / "video",
                       reroute=reroute, extra_headers=extra_headers,
                       on_frame=on_frame) as session:
        pre_raws: list[dict] = []
        if pre_steps:
            for step_def in json.loads(Path(pre_steps).read_text(encoding="utf-8")):
                mask = step_def.pop("mask", False)
                raw = session.step(**step_def)
                if mask:
                    raw["value"] = "********"  # 자격값은 여정 증거에도 남기지 않는다
                pre_raws.append(raw)
                log(f"  선행 {raw['idx']}: {raw['action']} {raw.get('selector') or ''}")
        loop_raws, reason = run_goal_loop(goal, session, client, roles,
                                          rules_context, max_turns=max_turns,
                                          initial_goto=not pre_raws, log=log)
        raws = pre_raws + loop_raws
    log(f"루프 종료: {reason} · 수행 {len(raws)}스텝 (선행 {len(pre_raws)})")

    journey = Journey(id=journey_id, title=title or goal, base_url=base_url,
                      created=datetime.now(timezone.utc).isoformat(),
                      video=session.video_path,
                      steps=_finalize_steps(config, raws))
    out = journey.save(Path(config["journey_dir"]) / f"{journey_id}.json")
    log(f"여정 저장: {out}")
    return out


def plan_steps_for_goal(config: dict, goal: str, base_url: str | None = None,
                        journey_id: str = "planned",
                        log: Callable[[str], None] = print) -> Path:
    """자연어 목표 → agent 모델(Opus)이 화면을 보고 스텝 계획 → 스텝 JSON 경로.

    "AI가 버튼을 누른다"의 계획 단계. LLM/agent 엔드포인트가 없으면 RuntimeError.
    """
    from .bridge.driver import BridgeSession
    from .llm import LLMClient
    from .plan import plan_steps

    client = LLMClient.from_env(config)
    if client is None:
        raise RuntimeError("계획에는 LLM 엔드포인트가 필요하다 (creator.config.json llm_base_url)")
    base_url = base_url or config.get("base_url")
    if not base_url:
        raise RuntimeError("base_url 필요")
    roles = load_roles(config)
    rules_context = compose_context(load_rules(config.get("rules_dir", "rules")))

    log(f"화면 관찰 중… ({base_url})")
    with BridgeSession(base_url, trace_store=config["trace_dir"],
                       shot_dir=Path(config["journey_dir"]) / journey_id / "plan") as s:
        outline = s.outline(url="/")
    log(f"상호작용 요소 {len(outline)}개 관찰 · agent 모델({roles.agent})이 스텝 계획 중…")
    steps = plan_steps(goal, outline, client, roles, rules_context)
    if not steps:
        raise RuntimeError("agent가 유효한 스텝을 계획하지 못했다 (화면/목표 재확인)")
    if steps[0]["action"] != "goto":  # 실행 세션은 빈 페이지에서 시작 — 진입 스텝을 앞세운다
        steps.insert(0, {"action": "goto", "selector": "/", "note": "화면 진입"})
    log(f"계획 완료: {len(steps)}스텝")
    for i, st in enumerate(steps, 1):
        log(f"  계획 {i}: {st['action']} {st.get('selector') or st.get('value') or ''}")
    plan_path = Path(config["journey_dir"]) / f"{journey_id}.plan.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(steps, ensure_ascii=False, indent=1), encoding="utf-8")
    return plan_path


def record_journey(config: dict, steps_path: str | Path,
                   base_url: str | None = None, journey_id: str | None = None,
                   title: str | None = None, headed: bool = False,
                   video: bool = True, reroute: list | None = None,
                   extra_headers: dict | None = None, on_frame=None,
                   log: Callable[[str], None] = print) -> Path:
    """스텝 정의 JSON을 브리지로 실행해 여정 JSON 경로를 반환. (playwright 필요)"""
    from .bridge.driver import BridgeSession  # optional 의존 — 지연 임포트

    steps_def = json.loads(Path(steps_path).read_text(encoding="utf-8"))
    base_url = base_url or config.get("base_url")
    if not base_url:
        raise RuntimeError("base_url 필요 (creator.config.json 또는 --base-url)")
    journey_id = journey_id or Path(steps_path).stem
    journey_root = Path(config["journey_dir"]) / journey_id

    log(f"여정 기록 시작: {journey_id} → {base_url}")
    steps = []
    with BridgeSession(base_url, trace_store=config["trace_dir"],
                       shot_dir=journey_root / "shots", headless=not headed,
                       video_dir=(journey_root / "video") if video else None,
                       reroute=reroute, extra_headers=extra_headers,
                       on_frame=on_frame) as session:
        for step_def in steps_def:
            raw = session.step(**step_def)
            if raw.get("element"):
                raw["frontend_sources"] = resolve_element(
                    raw["element"], config.get("frontend_roots") or [])
            steps.append(Step(**{k: v for k, v in raw.items()
                                 if k in Step.__dataclass_fields__}))
            log(f"  스텝 {raw['idx']}: {raw['action']} {raw.get('selector') or ''} "
                f"→ 백엔드 트레이스 {'확보' if raw.get('backend') else '없음'}")

    journey = Journey(id=journey_id, title=title or journey_id, base_url=base_url,
                      created=datetime.now(timezone.utc).isoformat(),
                      video=session.video_path, steps=steps)
    out = journey.save(Path(config["journey_dir"]) / f"{journey_id}.json")
    log(f"여정 저장: {out}")
    return out


def run_make(config: dict, steps: str | None = None, base_url: str | None = None,
             journey_id: str | None = None, title: str | None = None,
             headed: bool = False, narrate: bool = True, pdf: bool = False,
             out_dir: str | None = None, reroute: list | None = None,
             goal: str | None = None, pre_steps: str | None = None, on_frame=None,
             log: Callable[[str], None] = print) -> dict:
    """원샷 파이프라인. 반환: {journey_id, outputs, pdfs, video, narrated, steps}

    goal(자연어)이 주어지면 agent 모델이 멀티턴 관측 루프로 직접 브라우저를 몬다
    ("AI가 버튼을 누른다" — 보고→행동→다시 보고). on_frame은 스텝마다 화면 프레임을
    받아 라이브 화면 전환 스트리밍에 쓴다.
    """
    if goal and not steps:
        journey_path = record_goal_journey(
            config, goal, base_url=base_url, journey_id=journey_id or "goal",
            title=title, headed=headed, reroute=reroute,
            pre_steps=pre_steps, on_frame=on_frame, log=log)
        steps = None  # 루프가 여정까지 만들었다 — 아래 최신 여정 탐색을 건너뛰게
        journey = Journey.load(journey_path)
        log(f"여정: {journey.id} (스텝 {len(journey.steps)}개)")
        return _postprocess(config, journey_path, journey, narrate, pdf, out_dir, log)
    if steps:
        journey_path = record_journey(config, steps, base_url=base_url,
                                      journey_id=journey_id, title=title,
                                      headed=headed, reroute=reroute,
                                      on_frame=on_frame, log=log)
    else:
        candidates = sorted(journey_files(config["journey_dir"]),
                            key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            raise RuntimeError("여정이 없다 — 스텝 정의로 기록부터")
        journey_path = candidates[0]
    journey = Journey.load(journey_path)
    log(f"여정: {journey.id} (스텝 {len(journey.steps)}개)")
    return _postprocess(config, journey_path, journey, narrate, pdf, out_dir, log)


def _postprocess(config: dict, journey_path: Path, journey: Journey,
                 narrate: bool, pdf: bool, out_dir: str | None,
                 log: Callable[[str], None]) -> dict:
    narrated = False
    if narrate:
        from .llm import LLMClient
        client = LLMClient.from_env(config)
        if client is None:
            log("서술 생략 — LLM 엔드포인트 미설정")
        else:
            from .docgen.narrate import narrate_journey
            roles = load_roles(config)
            log(f"서술 중… (source 모델: {roles.source})")
            rules_context = compose_context(load_rules(config.get("rules_dir", "rules")))
            narrate_journey(journey, client, roles, rules_context)
            journey.save(journey_path)
            narrated = journey.narrative is not None
            log("서술 완료" if narrated else "서술 실패 — LLM 미응답/오류 (증거 문서는 그대로 생성)")

    outputs: list[str] = []
    resolved_out = out_dir or config["out_dir"]
    for form in FORMS_ALL:
        report = build([journey_path], resolved_out, form=form, force=True)
        outputs += report["outputs"]
        log(f"양식 {form}: {len(report['outputs'])}파일")

    # 디버거 리플레이 — 실행 흐름이 있는 스텝마다 line-by-line 열람 HTML.
    # Step.backend가 곧 트레이스 payload이므로 이를 직접 써서 결과서 링크와 완전히 일치시킨다.
    from .docgen.debug_view import build_debug_view
    debug_dir = Path(resolved_out) / journey.id / "debug"
    debug_views: list[str] = []
    for step in journey.steps:
        payload = step.backend
        if not payload or not payload.get("flow"):
            continue
        view = build_debug_view(payload, debug_dir / f"step-{step.idx:02d}.html",
                                title=f"스텝 {step.idx} — {payload.get('method')} {payload.get('path')}")
        debug_views.append(str(view))
    if debug_views:
        log(f"디버거 리플레이 {len(debug_views)}건")

    pdfs: list[str] = []
    if pdf:
        from .docgen.pdf import html_to_pdf
        for path in outputs:
            if path.endswith(".html"):
                pdfs.append(str(html_to_pdf(path)))
        log(f"PDF {len(pdfs)}종 생성")

    log("완료")
    return {
        "journey_id": journey.id,
        "journey_path": str(journey_path),
        "outputs": outputs,
        "pdfs": pdfs,
        "debug_views": debug_views,
        "video": journey.video,
        "narrated": narrated,
        "steps": [{"idx": s.idx, "action": s.action, "selector": s.selector,
                   "note": s.note, "backend": bool(s.backend),
                   "screenshot": s.screenshot,
                   "url_after": s.url_after} for s in journey.steps],
    }
