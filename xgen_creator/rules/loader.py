"""Rule 컨텍스트 — 산출물 규칙(용어 통일·문서 톤·캡처 규격 등)을 LLM 서술 단계에 주입.

rules/*.md 파일 하나 = 규칙 하나. 파일명 사전순으로 로드된다(번호 접두어로 우선순위 제어).
"""
from __future__ import annotations

from pathlib import Path


def load_rules(rules_dir: str | Path) -> list[tuple[str, str]]:
    root = Path(rules_dir)
    if not root.is_dir():
        return []
    rules = []
    for path in sorted(root.glob("*.md")):
        try:
            rules.append((path.stem, path.read_text(encoding="utf-8").strip()))
        except OSError:
            continue
    return rules


def compose_context(rules: list[tuple[str, str]], max_chars: int = 8000) -> str:
    """프롬프트 주입용 블록. 한도 초과분은 뒤쪽 규칙부터 잘리고 그 사실을 명기한다."""
    blocks: list[str] = []
    used = 0
    dropped: list[str] = []
    for name, text in rules:
        block = f"## Rule: {name}\n{text}"
        if used + len(block) > max_chars:
            dropped.append(name)
            continue
        blocks.append(block)
        used += len(block)
    if dropped:
        blocks.append(f"(한도 초과로 미포함된 규칙: {', '.join(dropped)})")
    return "\n\n".join(blocks)
