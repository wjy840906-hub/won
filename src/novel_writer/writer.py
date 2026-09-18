"""장별 집필과 다음 장을 위한 메모 작성."""

from __future__ import annotations

import logging
import re

from .claude_client import ClaudeError
from .config import NovelConfig
from .planner import plan_digest
from .prompts import SYSTEM_SUMMARIZER, SYSTEM_WRITER, chapter_prompt, summary_prompt

log = logging.getLogger(__name__)

# 모델이 가끔 붙이는 장 제목 줄("3장 「재회」", "## 3장", "제3장 재회")을 걷어낸다.
_HEADING = re.compile(r"^\s*(#{1,6}\s*)?(제\s*)?\d+\s*장\b.*$")


def strip_heading(text: str) -> str:
    """본문 맨 앞의 장 제목 줄을 없앤다."""
    lines = text.strip().splitlines()
    while lines and (not lines[0].strip() or _HEADING.match(lines[0])):
        lines.pop(0)
    return "\n".join(lines).strip()


def tail(text: str, size: int = 400) -> str:
    """직전 장의 마지막 대목(문체 연결용)."""
    cleaned = text.strip()
    return cleaned[-size:] if len(cleaned) > size else cleaned


def max_tokens_for(chapter_chars: int) -> int:
    """목표 글자수에 여유를 둔 출력 상한. 스트리밍이라 크게 잡아도 된다."""
    return max(8000, min(64000, chapter_chars * 4 + 4000))


def write_chapter(
    client,
    plan: dict,
    chapter: dict,
    config: NovelConfig,
    memos: list[str] | None = None,
    previous_tail: str = "",
) -> str:
    """한 장의 본문을 쓴다."""
    total = len(plan.get("chapters") or [])
    number = chapter.get("number", 0)
    log.info("%d/%d장 「%s」 집필 중…", number, total, chapter.get("title", ""))

    text = client.write(
        system=SYSTEM_WRITER,
        prompt=chapter_prompt(
            plan_digest=plan_digest(plan),
            chapter=chapter,
            story_so_far="\n".join(memos or []),
            previous_tail=previous_tail,
            chapter_chars=config.chapter_chars,
            total_chapters=total,
            language=config.language,
        ),
        what=f"{number}장 본문",
        max_tokens=max_tokens_for(config.chapter_chars),
    )
    text = strip_heading(text)
    log.info("%d장 완료: %d자", number, len(text))
    return text


def summarize_chapter(client, chapter: dict, text: str) -> str:
    """다음 장 집필에 넘길 메모를 만든다(실패해도 집필은 계속한다)."""
    try:
        memo = client.write(
            system=SYSTEM_SUMMARIZER,
            prompt=summary_prompt(chapter, text),
            what=f"{chapter.get('number', 0)}장 요약",
            max_tokens=2000,
            effort="low",
        )
    except ClaudeError as exc:
        log.warning("%d장 요약 실패(기획 개요로 대신합니다): %s", chapter.get("number", 0), exc)
        return f"- {chapter.get('number', 0)}장: {chapter.get('summary', '')}"
    return memo.strip()
