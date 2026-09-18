"""환경변수 기반 설정."""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_EFFORT = "high"
EFFORT_CHOICES = ("low", "medium", "high", "xhigh", "max")


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"환경변수 {name} 값이 정수가 아닙니다: {raw!r}") from exc


def slugify(text: str, fallback: str = "novel") -> str:
    """제목을 폴더 이름으로 쓸 수 있게 다듬는다(한글은 그대로 둔다)."""
    cleaned = unicodedata.normalize("NFC", (text or "").strip())
    cleaned = re.sub(r"[\\/:*?\"<>|\s]+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-.")
    return cleaned[:60] or fallback


@dataclass(frozen=True)
class NovelConfig:
    """집필 설정.

    chapters: 장 수, chapter_chars: 장당 목표 글자수(공백 포함).
    """

    api_key: str = ""
    model: str = DEFAULT_MODEL
    effort: str = DEFAULT_EFFORT
    chapters: int = 10
    chapter_chars: int = 3000
    language: str = "한국어"
    out_dir: str = "out/novel"
    timeout: int = 900
    max_retries: int = 4

    @classmethod
    def from_env(cls) -> "NovelConfig":
        return cls(
            api_key=_env("ANTHROPIC_API_KEY"),
            model=_env("NOVEL_MODEL", DEFAULT_MODEL),
            effort=_env("NOVEL_EFFORT", DEFAULT_EFFORT),
            chapters=_env_int("NOVEL_CHAPTERS", 10),
            chapter_chars=_env_int("NOVEL_CHAPTER_CHARS", 3000),
            language=_env("NOVEL_LANGUAGE", "한국어"),
            out_dir=_env("NOVEL_OUT_DIR", "out/novel"),
            timeout=_env_int("NOVEL_TIMEOUT", 900),
            max_retries=_env_int("NOVEL_MAX_RETRIES", 4),
        )

    def validate(self) -> list[str]:
        """설정 문제를 사람이 읽을 수 있는 메시지로 돌려준다."""
        problems: list[str] = []
        if not self.api_key:
            problems.append(
                "ANTHROPIC_API_KEY 가 비어 있습니다. https://console.anthropic.com 에서 발급하세요."
            )
        if self.effort not in EFFORT_CHOICES:
            problems.append(f"NOVEL_EFFORT 는 {'/'.join(EFFORT_CHOICES)} 중 하나여야 합니다.")
        if not 1 <= self.chapters <= 100:
            problems.append("장 수(--chapters)는 1~100 사이여야 합니다.")
        if not 500 <= self.chapter_chars <= 20000:
            problems.append("장당 글자수(--chars)는 500~20000 사이여야 합니다.")
        return problems


@dataclass(frozen=True)
class Brief:
    """무엇을 쓸지에 대한 사용자 입력."""

    idea: str
    title: str = ""
    genre: str = ""
    tone: str = ""
    pov: str = ""
    audience: str = ""
    notes: str = ""

    def as_lines(self) -> str:
        """프롬프트에 넣을 '항목: 값' 목록. 비어 있는 항목은 뺀다."""
        pairs = [
            ("소재", self.idea),
            ("제목(희망)", self.title),
            ("장르", self.genre),
            ("분위기·문체", self.tone),
            ("시점", self.pov),
            ("독자층", self.audience),
            ("그 밖의 요구", self.notes),
        ]
        return "\n".join(f"- {label}: {value.strip()}" for label, value in pairs if value.strip())
