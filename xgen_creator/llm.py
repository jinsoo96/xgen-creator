"""OpenAI 호환 챗 클라이언트 — 의존성 0(urllib). 서술(narration) 전용.

LLM은 증거를 서술할 뿐 사실을 만들지 않는다. base_url/key/model은 전부 설정 주도라
Claude API든 vLLM(사내 무료 엔드포인트)이든 동일 코드로 동작한다.
"""
from __future__ import annotations

import json
import os
import urllib.request


class LLMClient:
    def __init__(self, base_url: str, api_key: str = "", timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    @classmethod
    def from_env(cls, config: dict | None = None) -> LLMClient | None:
        """설정/환경에 엔드포인트가 없으면 None — 서술 기능이 조용히 꺼진다."""
        config = config or {}
        base_url = (config.get("llm_base_url")
                    or os.environ.get("XGEN_CREATOR_LLM_BASE_URL") or "")
        if not base_url:
            return None
        api_key = (config.get("llm_api_key")
                   or os.environ.get("XGEN_CREATOR_LLM_API_KEY") or "")
        return cls(base_url, api_key)

    def chat(self, model: str, messages: list[dict], max_tokens: int = 1024,
             temperature: float | None = None) -> str:
        body: dict = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if temperature is not None:  # 일부 모델(Fable 5 등)은 temperature 미지원
            body["temperature"] = temperature
        payload = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=payload,
            headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]
