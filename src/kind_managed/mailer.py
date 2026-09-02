"""엑셀 파일을 첨부해 메일을 발송한다."""

from __future__ import annotations

import logging
import mimetypes
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

from .config import MailConfig

log = logging.getLogger(__name__)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class MailError(RuntimeError):
    """메일 발송 실패."""


def build_message(
    config: MailConfig,
    subject: str,
    body_text: str,
    body_html: str = "",
    attachments: list[Path] | None = None,
    sender_name: str = "관리종목 알리미",
) -> EmailMessage:
    """첨부파일이 포함된 메일 메시지를 만든다."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((sender_name, config.sender)) if sender_name else config.sender
    message["To"] = ", ".join(config.to)
    if config.cc:
        message["Cc"] = ", ".join(config.cc)
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()

    message.set_content(body_text)
    if body_html:
        message.add_alternative(body_html, subtype="html")

    for path in attachments or []:
        path = Path(path)
        if not path.exists():
            raise MailError(f"첨부할 파일이 없습니다: {path}")
        guessed, _ = mimetypes.guess_type(path.name)
        mime = guessed or (XLSX_MIME if path.suffix.lower() == ".xlsx" else "application/octet-stream")
        maintype, _, subtype = mime.partition("/")
        message.add_attachment(
            path.read_bytes(),
            maintype=maintype,
            subtype=subtype or "octet-stream",
            filename=path.name,
        )
    return message


def send_message(config: MailConfig, message: EmailMessage) -> None:
    """SMTP 로 메일을 발송한다."""
    problems = config.validate()
    if problems:
        raise MailError("메일 설정이 올바르지 않습니다: " + " / ".join(problems))

    try:
        if config.use_ssl:
            server: smtplib.SMTP = smtplib.SMTP_SSL(
                config.host, config.port, timeout=config.timeout
            )
        else:
            server = smtplib.SMTP(config.host, config.port, timeout=config.timeout)
        with server:
            server.ehlo()
            if config.use_starttls and not config.use_ssl:
                server.starttls()
                server.ehlo()
            if config.user and config.password:
                server.login(config.user, config.password)
            server.send_message(message, from_addr=config.sender, to_addrs=config.recipients)
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f"메일 발송 실패: {exc}") from exc

    log.info("메일 발송 완료 → %s", ", ".join(config.recipients))
