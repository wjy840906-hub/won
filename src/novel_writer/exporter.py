"""장별 원고를 한 편의 원고 파일로 묶는다."""

from __future__ import annotations

from pathlib import Path

from .state import NovelState


def build_markdown(state: NovelState) -> str:
    """제목 · 소개 · 장별 본문을 담은 마크다운 원고."""
    plan = state.plan
    parts = [f"# {plan.get('title', '무제')}", ""]
    if plan.get("logline"):
        parts += [f"> {plan['logline']}", ""]
    meta = " · ".join(
        value for value in (plan.get("genre", ""), plan.get("tone", ""), plan.get("pov", "")) if value
    )
    if meta:
        parts += [f"*{meta}*", ""]

    for record in state.records:
        text = state.text_of(record.number)
        if not text:
            continue
        parts += [f"## {record.number}장 {record.title}".rstrip(), "", text, ""]
    return "\n".join(parts).rstrip() + "\n"


def build_text(state: NovelState) -> str:
    """워드·한글에 붙여 넣기 좋은 순수 텍스트 원고."""
    plan = state.plan
    parts = [plan.get("title", "무제"), ""]
    for record in state.records:
        text = state.text_of(record.number)
        if not text:
            continue
        parts += [f"{record.number}장  {record.title}".rstrip(), "", text, "", ""]
    return "\n".join(parts).rstrip() + "\n"


def export(state: NovelState) -> list[Path]:
    """원고.md · 원고.txt 를 작업 폴더에 저장하고 경로를 돌려준다."""
    state.directory.mkdir(parents=True, exist_ok=True)
    markdown_path = state.directory / "원고.md"
    text_path = state.directory / "원고.txt"
    markdown_path.write_text(build_markdown(state), encoding="utf-8")
    text_path.write_text(build_text(state), encoding="utf-8")
    return [markdown_path, text_path]
