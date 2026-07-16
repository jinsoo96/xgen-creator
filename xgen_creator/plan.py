"""여정 계획자 — agent 역할 모델(Opus)이 자연어 목표를 브라우저 스텝으로 바꾼다.

"AI가 버튼을 누른다"의 계획 단계: 화면의 상호작용 요소 목록 + 목표를 주면
Opus가 수행할 스텝(JSON)을 낸다. 실행은 브리지가, 서술은 source 모델(Fable)이 한다.
LLM이 없거나 응답이 깨지면 계획 실패로 정직하게 알리고 진행하지 않는다(추측 실행 금지).
"""
from __future__ import annotations

import json

from .llm import LLMClient
from .pipeline.roles import ModelRoles

ACTIONS = ("goto", "click", "fill", "press")

_SYSTEM = """너는 XGEN CREATOR의 여정 계획자다. 사용자의 목표와 현재 화면의 상호작용 요소
목록을 받아, 브라우저로 수행할 스텝을 JSON 배열로만 출력한다.
- 각 스텝은 {"action","selector","value"(선택),"note"(선택)} 형식이다.
- action 은 goto | click | fill | press 중 하나만 쓴다.
- selector 는 요소 목록의 selector 를 그대로 인용한다(새로 지어내지 않는다).
- 목표에 필요한 최소한의 스텝만 만든다. 확실치 않은 요소는 넣지 않는다.
- 설명·코드펜스 없이 JSON 배열만 출력한다."""


def _extract_json_array(text: str) -> list:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < 0:
        raise ValueError("계획 응답에서 JSON 배열을 찾지 못함")
    return json.loads(text[start:end + 1])


def _validate(raw_steps: list) -> list[dict]:
    steps: list[dict] = []
    for item in raw_steps:
        if not isinstance(item, dict):
            continue
        action = item.get("action")
        if action not in ACTIONS:
            continue
        if action != "goto" and not item.get("selector"):
            continue
        steps.append({k: item[k] for k in ("action", "selector", "value", "note")
                      if item.get(k) is not None})
    return steps


def plan_steps(goal: str, outline: list[dict], client: LLMClient, roles: ModelRoles,
               rules_context: str = "") -> list[dict]:
    """목표 + 화면 요소 목록 → 검증된 스텝 목록. 유효 스텝이 0이면 빈 목록."""
    system = _SYSTEM + (f"\n\n[산출물 규칙]\n{rules_context}" if rules_context else "")
    user = (f"목표: {goal}\n\n현재 화면의 상호작용 요소 (selector 목록):\n"
            f"{json.dumps(outline, ensure_ascii=False, indent=1)}")
    reply = client.chat(roles.agent, [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], max_tokens=1500)
    return _validate(_extract_json_array(reply))
