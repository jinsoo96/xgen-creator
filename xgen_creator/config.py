"""설정 로드 — creator.config.json + .env(환경변수 우선) 오버레이.

실값(도메인·경로·계정)은 전부 gitignore된 로컬 파일에만 있다. 코드에는 기본값과
placeholder뿐 — 설정 없이는 아무것도 안 되는 것이 의도다 (공개 안전).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .dotenv import load_dotenv

DEFAULTS = {
    "base_url": "",
    "backend_url": "",
    "trace_dir": ".creator/traces",
    "journey_dir": ".creator/journeys",
    "out_dir": "docs_out",
    "rules_dir": "rules",
    "backend_roots": [],
    "frontend_roots": [],
    "models": {},
}

_ENV_MAP = {
    "XGEN_CREATOR_BASE_URL": "base_url",
    "XGEN_CREATOR_BACKEND_URL": "backend_url",
    "XGEN_CREATOR_TRACE_DIR": "trace_dir",
}


def load_config(path: str | Path | None = None) -> dict:
    load_dotenv()
    config = dict(DEFAULTS)
    candidate = Path(path) if path else Path("creator.config.json")
    if candidate.is_file():
        config.update(json.loads(candidate.read_text(encoding="utf-8")))
    for env_key, cfg_key in _ENV_MAP.items():
        if os.environ.get(env_key):
            config[cfg_key] = os.environ[env_key]
    return config
