"""기획 → 장별 집필 → 원고 저장(→ 메일) 전체 흐름."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .claude_client import ClaudeClient, ClaudeError
from .config import Brief, NovelConfig, slugify
from .exporter import export
from .planner import build_plan
from .state import NovelState
from .writer import summarize_chapter, tail, write_chapter

log = logging.getLogger(__name__)


@dataclass
class NovelResult:
    """실행 결과."""

    directory: Path
    title: str = ""
    written: int = 0
    total_chapters: int = 0
    total_chars: int = 0
    files: list[Path] = field(default_factory=list)
    usage: str = ""
    mail_sent: bool = False

    @property
    def finished(self) -> bool:
        return self.total_chapters > 0 and self.written >= self.total_chapters


def _work_dir(out_dir: str, title: str) -> Path:
    """out/novel/2026-09-18-제목 — 같은 이름이 있으면 -2, -3 을 붙인다."""
    base = Path(out_dir) / f"{date.today().isoformat()}-{slugify(title)}"
    candidate, index = base, 2
    while candidate.exists():
        candidate = Path(f"{base}-{index}")
        index += 1
    return candidate


def run(
    config: NovelConfig,
    brief: Brief | None = None,
    *,
    client=None,
    resume_dir: str | Path | None = None,
    plan_only: bool = False,
    chapters_limit: int = 0,
    mail_config=None,
) -> NovelResult:
    """소설 한 편을 기획하고 장별로 써서 저장한다.

    resume_dir 을 주면 그 폴더의 기획을 이어받아 남은 장만 쓴다.
    chapters_limit 은 이번 실행에서 쓸 장 수(0이면 끝까지).
    """
    client = client or ClaudeClient(
        api_key=config.api_key,
        model=config.model,
        effort=config.effort,
        timeout=config.timeout,
        max_retries=config.max_retries,
    )

    if resume_dir:
        state = NovelState.load(resume_dir)
        if not state.plan:
            raise ClaudeError(f"이어쓸 기획이 없습니다: {Path(resume_dir) / 'plan.json'}")
        log.info("이어쓰기: %s (%d장까지 완료)", state.directory, len(state.records))
    else:
        if brief is None or not brief.idea.strip():
            raise ClaudeError("무엇을 쓸지(소재)를 알려 주세요.")
        plan = build_plan(client, brief, config)
        state = NovelState(directory=_work_dir(config.out_dir, plan["title"]))
        state.save_plan(plan)
        log.info("작업 폴더: %s", state.directory)

    chapters = state.plan.get("chapters") or []
    result = NovelResult(
        directory=state.directory,
        title=state.plan.get("title", ""),
        total_chapters=len(chapters),
        written=len(state.records),
    )

    if plan_only:
        result.total_chars = state.total_chars
        result.usage = client.usage.summary(config.model)
        return result

    pending = [chapter for chapter in chapters if chapter["number"] not in state.done_numbers]
    if chapters_limit:
        pending = pending[:chapters_limit]

    for chapter in pending:
        number = chapter["number"]
        text = write_chapter(
            client,
            state.plan,
            chapter,
            config,
            memos=state.memos(),
            previous_tail=tail(state.text_of(number - 1)),
        )
        is_last = number == len(chapters)
        memo = "" if is_last else summarize_chapter(client, chapter, text)
        state.save_chapter(chapter, text, memo)
        result.written = len(state.records)

    result.files = export(state)
    result.total_chars = state.total_chars
    result.usage = client.usage.summary(config.model)
    log.info("원고 저장: %s (%d자)", result.files[0], result.total_chars)

    if mail_config is not None:
        result.mail_sent = send_manuscript(mail_config, state, result)
    return result


def build_mail_body(state: NovelState, result: NovelResult) -> str:
    """메일 본문(진행 상황 + 시놉시스 + 장 목록)."""
    plan = state.plan
    lines = [
        f"「{result.title}」 {result.written}/{result.total_chapters}장 · {result.total_chars:,}자",
        "",
        plan.get("logline", ""),
        "",
        plan.get("synopsis", ""),
        "",
        "장 목록",
    ]
    for chapter in plan.get("chapters") or []:
        mark = "✔" if chapter["number"] in state.done_numbers else "·"
        lines.append(f"  {mark} {chapter['number']}장 「{chapter['title']}」 {chapter['summary']}")
    if not result.finished:
        lines += ["", "남은 장은 다음 실행에서 이어 씁니다."]
    return "\n".join(lines)


def send_manuscript(mail_config, state: NovelState, result: NovelResult) -> bool:
    """원고를 첨부해 메일로 보낸다(메일 설정·발송은 kind_managed 의 것을 그대로 쓴다)."""
    from kind_managed.mailer import build_message, send_message

    status = "완성" if result.finished else f"{result.written}/{result.total_chapters}장"
    message = build_message(
        mail_config,
        subject=f"[소설] {result.title} ({status})",
        body_text=build_mail_body(state, result),
        attachments=result.files,
        sender_name="소설 매크로",
    )
    send_message(mail_config, message)
    return True
