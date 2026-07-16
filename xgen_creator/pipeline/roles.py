"""모델 역할 라우팅 — 에이전트(오케스트레이션)=Opus, 소스 작업(서술·문서화)=Fable.

우선순위: creator.config.json `models` → 환경변수 → 기본값.
LLM은 서술을 입히는 존재지 사실을 만드는 존재가 아니다 — 결정론 코어는 모델 없이 동작.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_AGENT = "claude-opus-4-8"
DEFAULT_SOURCE = "claude-fable-5"


@dataclass
class ModelRoles:
    agent: str = DEFAULT_AGENT    # 여정 계획·브라우저 조작 판단
    source: str = DEFAULT_SOURCE  # 실행된 소스 해설·산출물 본문 작성


def load_roles(config: dict | None = None) -> ModelRoles:
    models = (config or {}).get("models") or {}
    return ModelRoles(
        agent=models.get("agent")
        or os.environ.get("XGEN_CREATOR_MODEL_AGENT")
        or DEFAULT_AGENT,
        source=models.get("source")
        or os.environ.get("XGEN_CREATOR_MODEL_SOURCE")
        or DEFAULT_SOURCE,
    )
