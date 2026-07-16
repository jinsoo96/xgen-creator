"""멀티턴 관측 루프 — agent 역할 모델(Opus)이 보고→행동→다시 보고를 반복한다.

턴마다: 현재 화면 요소 + 지금까지의 수행 이력 → 다음 스텝 하나 또는 완료 선언.
세션은 덕 타이핑(outline()/step())이라 브리지든 스텁이든 동일하게 돈다.
불확실하면 멈추는 것이 원칙 — 유효하지 않은 결정은 그 자리에서 종료하고 사유를 남긴다.
"""
from __future__ import annotations

import json
from typing import Callable

from .llm import LLMClient
from .pipeline.roles import ModelRoles
from .plan import ACTIONS

_SYSTEM = """너는 XGEN CREATOR의 여정 수행 에이전트다. 목표를 향해 브라우저 스텝을 **한 턴에
정확히 하나씩** 결정한다. 매 턴 현재 화면의 상호작용 요소와 지금까지의 수행 이력을 받는다.
출력은 JSON 객체 하나만:
- 다음 행동: {"action":"goto|click|fill|press","selector":"...","value"(선택),"note"(선택)}
- 목표 달성/더 할 것 없음: {"done": true, "reason": "..."}
규칙: selector는 요소 목록에 있는 것만 인용한다. 같은 행동을 의미 없이 반복하지 않는다.
확신이 없으면 done으로 멈추고 reason에 밝힌다. 설명·코드펜스 없이 JSON만."""


def _extract_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("결정 응답에서 JSON 객체를 찾지 못함")
    return json.loads(text[start:end + 1])


def run_goal_loop(goal: str, session, client: LLMClient, roles: ModelRoles,
                  rules_context: str = "", max_turns: int = 8,
                  initial_goto: bool = True,
                  log: Callable[[str], None] = print) -> tuple[list[dict], str]:
    """반환: (수행된 raw 스텝들, 종료 사유).

    initial_goto=False면 이미 진입/로그인된 세션을 이어받아 현재 화면부터 관측한다.
    """
    system = _SYSTEM + (f"\n\n[산출물 규칙]\n{rules_context}" if rules_context else "")
    raws: list[dict] = []
    history: list[dict] = []
    if initial_goto:
        raws.append(session.step("goto", "/", note="화면 진입"))
        history.append({"turn": 0, "action": "goto /", "url": raws[-1].get("url_after")})

    for turn in range(1, max_turns + 1):
        outline = session.outline()
        user = json.dumps({
            "목표": goal,
            "현재_URL": raws[-1].get("url_after") if raws else None,
            "화면_요소": outline,
            "수행_이력": history,
        }, ensure_ascii=False)
        try:
            decision = _extract_object(client.chat(roles.agent, [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ], max_tokens=800))
        except (ValueError, json.JSONDecodeError) as exc:
            reason = f"결정 파싱 실패로 중단: {exc}"
            log(f"턴 {turn}: {reason}")
            return raws, reason
        if decision.get("done"):
            reason = str(decision.get("reason") or "목표 달성")
            log(f"턴 {turn}: 완료 선언 — {reason}")
            return raws, reason
        action = decision.get("action")
        if action not in ACTIONS or (action != "goto" and not decision.get("selector")):
            reason = f"유효하지 않은 결정({decision})으로 중단"
            log(f"턴 {turn}: {reason}")
            return raws, reason
        log(f"턴 {turn}: {action} {decision.get('selector') or decision.get('value') or ''}")
        raw = session.step(action, decision.get("selector"),
                           decision.get("value"), decision.get("note") or "")
        raws.append(raw)
        history.append({"turn": turn, "action": f"{action} {decision.get('selector') or ''}",
                        "url": raw.get("url_after"),
                        "api_호출": len(raw.get("api") or []),
                        "백엔드_트레이스": bool(raw.get("backend"))})
    return raws, f"최대 턴({max_turns}) 도달"
