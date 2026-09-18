"""소재 → 기획(제목·시놉시스·인물·장별 개요)."""

from __future__ import annotations

import logging

from .claude_client import ClaudeError
from .config import Brief, NovelConfig
from .prompts import SYSTEM_PLANNER, plan_prompt

log = logging.getLogger(__name__)

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "logline": {"type": "string"},
        "synopsis": {"type": "string"},
        "genre": {"type": "string"},
        "tone": {"type": "string"},
        "pov": {"type": "string"},
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "profile": {"type": "string"},
                },
                "required": ["name", "role", "profile"],
                "additionalProperties": False,
            },
        },
        "settings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "description"],
                "additionalProperties": False,
            },
        },
        "chapters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "integer"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "beats": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["number", "title", "summary", "beats"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "title",
        "logline",
        "synopsis",
        "genre",
        "tone",
        "pov",
        "characters",
        "settings",
        "chapters",
    ],
    "additionalProperties": False,
}


def normalize_plan(plan: dict, chapters: int) -> dict:
    """장 번호를 1부터 다시 매기고, 요청한 장 수에 맞춘다."""
    raw_chapters = [item for item in (plan.get("chapters") or []) if isinstance(item, dict)]
    if not raw_chapters:
        raise ClaudeError("기획에 장 목록이 없습니다. 다시 실행해 보세요.")

    if len(raw_chapters) != chapters:
        log.warning("기획된 장 수가 %d개입니다(요청 %d개). 그대로 사용합니다.", len(raw_chapters), chapters)

    fixed = []
    for index, chapter in enumerate(raw_chapters, 1):
        beats = [str(beat).strip() for beat in (chapter.get("beats") or []) if str(beat).strip()]
        fixed.append(
            {
                "number": index,
                "title": str(chapter.get("title") or f"{index}장").strip(),
                "summary": str(chapter.get("summary") or "").strip(),
                "beats": beats,
            }
        )
    plan["chapters"] = fixed
    plan["title"] = str(plan.get("title") or "무제").strip()
    return plan


def build_plan(client, brief: Brief, config: NovelConfig) -> dict:
    """Claude 로 기획을 만든다."""
    log.info("기획 생성 중… (%d장 / 장당 %d자)", config.chapters, config.chapter_chars)
    plan = client.json(
        system=SYSTEM_PLANNER,
        prompt=plan_prompt(
            brief.as_lines(), config.chapters, config.chapter_chars, config.language
        ),
        schema=PLAN_SCHEMA,
        what="기획",
    )
    plan = normalize_plan(plan, config.chapters)
    plan["brief"] = {
        "idea": brief.idea,
        "genre": brief.genre,
        "tone": brief.tone,
        "pov": brief.pov,
        "audience": brief.audience,
        "notes": brief.notes,
    }
    log.info("기획 완료: 「%s」 %d장", plan["title"], len(plan["chapters"]))
    return plan


def plan_digest(plan: dict) -> str:
    """집필 프롬프트에 넣을 기획 요약(전체 장 목록은 한 줄씩만)."""
    characters = "\n".join(
        f"- {person.get('name', '')}({person.get('role', '')}): {person.get('profile', '')}"
        for person in plan.get("characters") or []
    )
    settings = "\n".join(
        f"- {place.get('name', '')}: {place.get('description', '')}"
        for place in plan.get("settings") or []
    )
    outline = "\n".join(
        f"- {chapter['number']}장 「{chapter['title']}」: {chapter['summary']}"
        for chapter in plan.get("chapters") or []
    )
    parts = [
        f"제목: {plan.get('title', '')}",
        f"장르: {plan.get('genre', '')} / 분위기·문체: {plan.get('tone', '')} / 시점: {plan.get('pov', '')}",
        f"한 줄 소개: {plan.get('logline', '')}",
        f"줄거리: {plan.get('synopsis', '')}",
    ]
    if characters:
        parts.append(f"인물\n{characters}")
    if settings:
        parts.append(f"배경\n{settings}")
    if outline:
        parts.append(f"전체 장 구성\n{outline}")
    return "\n\n".join(parts)
