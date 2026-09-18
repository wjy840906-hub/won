"""작업 폴더(기획 · 장별 원고 · 진행 상태) 관리.

한 작품 = 한 폴더. 중간에 끊겨도 같은 폴더를 --resume 으로 지정하면 이어서 쓴다.

  out/novel/2026-09-18-제목/
    plan.json        기획
    progress.json    어디까지 썼는지 + 장별 메모
    chapters/01.md   장별 본문
    원고.md / 원고.txt
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ChapterRecord:
    """집필이 끝난 장 하나."""

    number: int
    title: str
    chars: int
    memo: str = ""

    @property
    def filename(self) -> str:
        return f"{self.number:02d}.md"


@dataclass
class NovelState:
    """작업 폴더의 파일들을 읽고 쓴다."""

    directory: Path
    plan: dict = field(default_factory=dict)
    records: list[ChapterRecord] = field(default_factory=list)

    @classmethod
    def load(cls, directory: str | Path) -> "NovelState":
        path = Path(directory)
        state = cls(directory=path)
        if state.plan_path.exists():
            state.plan = json.loads(state.plan_path.read_text(encoding="utf-8"))
        if state.progress_path.exists():
            data = json.loads(state.progress_path.read_text(encoding="utf-8"))
            state.records = [
                ChapterRecord(
                    number=int(item["number"]),
                    title=item.get("title", ""),
                    chars=int(item.get("chars", 0)),
                    memo=item.get("memo", ""),
                )
                for item in data.get("chapters", [])
            ]
        return state

    # -- 경로 ---------------------------------------------------------------

    @property
    def plan_path(self) -> Path:
        return self.directory / "plan.json"

    @property
    def progress_path(self) -> Path:
        return self.directory / "progress.json"

    @property
    def chapters_dir(self) -> Path:
        return self.directory / "chapters"

    # -- 쓰기 ---------------------------------------------------------------

    def save_plan(self, plan: dict) -> None:
        self.plan = plan
        self.directory.mkdir(parents=True, exist_ok=True)
        self.plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def save_chapter(self, chapter: dict, text: str, memo: str = "") -> ChapterRecord:
        record = ChapterRecord(
            number=int(chapter["number"]),
            title=chapter.get("title", ""),
            chars=len(text),
            memo=memo,
        )
        self.chapters_dir.mkdir(parents=True, exist_ok=True)
        (self.chapters_dir / record.filename).write_text(text, encoding="utf-8")
        self.records = [item for item in self.records if item.number != record.number]
        self.records.append(record)
        self.records.sort(key=lambda item: item.number)
        self._save_progress()
        return record

    def _save_progress(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        data = {
            "title": self.plan.get("title", ""),
            "chapters": [
                {
                    "number": item.number,
                    "title": item.title,
                    "chars": item.chars,
                    "memo": item.memo,
                }
                for item in self.records
            ],
        }
        self.progress_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # -- 읽기 ---------------------------------------------------------------

    @property
    def done_numbers(self) -> set[int]:
        return {item.number for item in self.records}

    def text_of(self, number: int) -> str:
        path = self.chapters_dir / f"{number:02d}.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def memos(self, limit: int = 4) -> list[str]:
        """최근 장 메모(기본 4개)와 그 앞 장들의 기획 개요."""
        lines: list[str] = []
        recent = self.records[-limit:] if limit else self.records
        for item in self.records[: max(0, len(self.records) - len(recent))]:
            lines.append(f"- {item.number}장 「{item.title}」: {self._planned_summary(item.number)}")
        for item in recent:
            header = f"[{item.number}장 「{item.title}」]"
            lines.append(f"{header}\n{item.memo}" if item.memo else header)
        return lines

    def _planned_summary(self, number: int) -> str:
        for chapter in self.plan.get("chapters") or []:
            if chapter.get("number") == number:
                return chapter.get("summary", "")
        return ""

    @property
    def total_chars(self) -> int:
        return sum(item.chars for item in self.records)
