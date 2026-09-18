"""예약 결과를 메일로 알린다(기존 SMTP 설정·발송 코드를 그대로 쓴다)."""

from __future__ import annotations

import html
import logging

from kind_managed.config import MailConfig
from kind_managed.mailer import MailError, build_message, send_message

from .runner import BookingResult, Outcome

log = logging.getLogger(__name__)

SENDER_NAME = "예약 매크로"


def build_subject(result: BookingResult) -> str:
    if result.error:
        return f"[예약 중단] {result.scenario_name}"
    if result.reserved is None:
        return f"[예약 실패] {result.scenario_name}"
    mark = "모의" if result.reserved.outcome is Outcome.DRY_RUN else "성공"
    return f"[예약 {mark}] {result.scenario_name} — {result.reserved.target.label}"


def build_body_text(result: BookingResult) -> str:
    lines = [
        f"시나리오: {result.scenario_name}",
        f"시작: {result.started_at:%Y-%m-%d %H:%M:%S}",
    ]
    if result.finished_at:
        lines.append(f"종료: {result.finished_at:%Y-%m-%d %H:%M:%S}")
    if result.dry_run:
        lines.append("※ 모의 실행(--dry-run): 확정 단계는 누르지 않았습니다.")
    lines.append("")
    lines.append(result.summary())
    lines.append("")
    lines.append("시도 내역")
    for attempt in result.attempts:
        lines.append(f"  - {attempt.describe()}")
    if not result.attempts:
        lines.append("  (없음)")
    if result.screenshots:
        lines.append("")
        lines.append("저장된 화면")
        for path in result.screenshots:
            lines.append(f"  - {path}")
    return "\n".join(lines)


def build_body_html(result: BookingResult) -> str:
    rows = "".join(
        f"<tr><td>{attempt.round_no}</td><td>{html.escape(attempt.target.label)}</td>"
        f"<td>{html.escape(attempt.outcome.value)}</td>"
        f"<td>{html.escape(attempt.message)}</td></tr>"
        for attempt in result.attempts
    )
    note = "<p>※ 모의 실행(--dry-run): 확정 단계는 누르지 않았습니다.</p>" if result.dry_run else ""
    return (
        f"<h2>{html.escape(result.scenario_name)}</h2>"
        f"<p><b>{html.escape(result.summary())}</b></p>"
        f"{note}"
        "<table border='1' cellpadding='6' cellspacing='0'>"
        "<tr><th>회차</th><th>후보</th><th>결과</th><th>메모</th></tr>"
        f"{rows or '<tr><td colspan=4>시도 없음</td></tr>'}"
        "</table>"
    )


def notify(mail_config: MailConfig, result: BookingResult, attach_screenshots: bool = True) -> bool:
    """결과 메일을 보낸다. 발송 실패는 로그로 남기고 False 를 돌려준다."""
    attachments = result.screenshots[:3] if attach_screenshots else []
    message = build_message(
        mail_config,
        subject=build_subject(result),
        body_text=build_body_text(result),
        body_html=build_body_html(result),
        attachments=attachments,
        sender_name=SENDER_NAME,
    )
    try:
        send_message(mail_config, message)
    except MailError as exc:
        log.error("결과 메일 발송 실패: %s", exc)
        return False
    return True
