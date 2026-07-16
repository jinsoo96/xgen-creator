"""증거 서술 — source 역할 모델이 여정 증거를 읽고 해설을 입힌다.

원칙: LLM은 증거에 있는 것만 서술한다. 프롬프트에 증거 요약과 Rule 컨텍스트를 주입하고,
증거 밖 추정을 금지한다. 서술 실패는 여정을 깨지 않는다(해당 해설만 비움).
"""
from __future__ import annotations

import json

from ..llm import LLMClient
from ..pipeline.roles import ModelRoles
from .model import Journey, Step

_SYSTEM = """너는 XGEN CREATOR의 산출물 서술자다. 아래 실측 증거만 근거로 간결한 한국어 해설을 쓴다.
규칙: (1) 증거에 없는 내용은 절대 추정하지 않는다 (2) 3~5문장, 매뉴얼체 (3) 파일 경로·수치는 증거 그대로 인용한다."""


def _step_evidence(step: Step) -> str:
    evidence = {
        "action": step.action, "selector": step.selector, "note": step.note,
        "url_before": step.url_before, "url_after": step.url_after,
        "element": step.element,
        "frontend_sources": step.frontend_sources[:2],
        "api": step.api[:5],
    }
    if step.backend:
        b = step.backend
        evidence["backend"] = {
            "request": f"{b.get('method')} {b.get('path')} → {b.get('status')}",
            "duration_ms": b.get("duration_ms"),
            "executed_files": {k: len(v) for k, v in (b.get("files") or {}).items()},
            "flow_head": b.get("flow", [])[:15],
        }
    return json.dumps(evidence, ensure_ascii=False)


def narrate_journey(journey: Journey, client: LLMClient, roles: ModelRoles,
                    rules_context: str = "") -> Journey:
    """journey.narrative + 각 step.narrative 채움(제자리 수정 후 반환)."""
    system = _SYSTEM + (f"\n\n[산출물 규칙]\n{rules_context}" if rules_context else "")

    for step in journey.steps:
        try:
            step.narrative = client.chat(roles.source, [
                {"role": "system", "content": system},
                {"role": "user", "content":
                    f"스텝 {step.idx}의 증거다. 이 스텝에서 무엇이 일어났고 어느 소스가 "
                    f"관여했는지 해설하라.\n{_step_evidence(step)}"},
            ]).strip()
        except Exception:
            step.narrative = None  # 서술 실패는 증거를 오염시키지 않는다

    outline = [{"idx": s.idx, "action": s.action, "note": s.note,
                "url_after": s.url_after, "backend": bool(s.backend)}
               for s in journey.steps]
    try:
        journey.narrative = client.chat(roles.source, [
            {"role": "system", "content": system},
            {"role": "user", "content":
                f"여정 '{journey.title}'(대상 {journey.base_url})의 스텝 개요다. "
                f"이 여정이 무엇을 검증/수행했는지 개요 해설을 쓰라.\n"
                f"{json.dumps(outline, ensure_ascii=False)}"},
        ]).strip()
    except Exception:
        journey.narrative = None
    return journey
