"""환경변수 기반 설정."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9), "KST")

DEFAULT_MAIL_TO = "wonjiyun@hanafn.com"


def now_kst() -> datetime:
    return datetime.now(KST)


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


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def normalize_from_date(raw: str) -> str:
    """수집 시작일 표기를 YYYY-MM-DD 로 통일한다.

    허용: '2026-08-01', '20260801', '2026-08', '202608', '8'(올해 8월).
    빈 값이면 제한 없음(전체).
    """
    text = (raw or "").strip()
    if not text:
        return ""

    match = re.fullmatch(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", text)
    if match:
        year, month, day = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"

    match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", text)
    if match:
        year, month, day = match.groups()
        return f"{year}-{month}-{day}"

    match = re.fullmatch(r"(\d{4})[-./](\d{1,2})", text)
    if match:
        year, month = match.groups()
        return f"{year}-{int(month):02d}-01"

    match = re.fullmatch(r"(\d{4})(\d{2})", text)
    if match:
        year, month = match.groups()
        return f"{year}-{month}-01"

    match = re.fullmatch(r"(\d{1,2})", text)
    if match and 1 <= int(match.group(1)) <= 12:
        return f"{now_kst().year}-{int(match.group(1)):02d}-01"

    raise ValueError(f"FROM_DATE 형식을 알 수 없습니다: {raw!r} (예: 2026-08-01, 2026-08, 8)")


def _env_list(name: str, default: str = "") -> list[str]:
    raw = _env(name, default)
    return [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]


@dataclass(frozen=True)
class MailConfig:
    """SMTP 발송 설정."""

    host: str = ""
    port: int = 587
    user: str = ""
    password: str = ""
    sender: str = ""
    to: list[str] = field(default_factory=lambda: [DEFAULT_MAIL_TO])
    cc: list[str] = field(default_factory=list)
    use_ssl: bool = False
    use_starttls: bool = True
    timeout: int = 60

    @classmethod
    def from_env(cls) -> "MailConfig":
        user = _env("SMTP_USER")
        return cls(
            host=_env("SMTP_HOST"),
            port=_env_int("SMTP_PORT", 587),
            user=user,
            password=_env("SMTP_PASSWORD"),
            sender=_env("MAIL_FROM", user),
            to=_env_list("MAIL_TO", DEFAULT_MAIL_TO),
            cc=_env_list("MAIL_CC"),
            use_ssl=_env_bool("SMTP_USE_SSL", False),
            use_starttls=_env_bool("SMTP_USE_STARTTLS", True),
            timeout=_env_int("SMTP_TIMEOUT", 60),
        )

    @property
    def recipients(self) -> list[str]:
        """중복을 제거한 실제 수신자(To + Cc) 목록."""
        seen: dict[str, None] = {}
        for addr in [*self.to, *self.cc]:
            seen.setdefault(addr, None)
        return list(seen)

    def validate(self) -> list[str]:
        """설정 누락 항목을 사람이 읽을 수 있는 메시지로 돌려준다."""
        problems: list[str] = []
        if not self.host:
            problems.append("SMTP_HOST 가 비어 있습니다.")
        if not self.sender:
            problems.append("MAIL_FROM (또는 SMTP_USER) 가 비어 있습니다.")
        if not self.to:
            problems.append("MAIL_TO 가 비어 있습니다.")
        if self.use_ssl and self.use_starttls:
            problems.append("SMTP_USE_SSL 과 SMTP_USE_STARTTLS 를 동시에 켤 수 없습니다.")
        return problems


@dataclass(frozen=True)
class AppConfig:
    """파이프라인 전체 설정."""

    dart_api_key: str = ""
    market: str = ""
    from_date: str = ""
    out_dir: str = "out"
    cache_dir: str = ".cache"
    request_timeout: int = 30
    max_pages: int = 50
    page_size: int = 100

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            dart_api_key=_env("DART_API_KEY"),
            market=_env("KIND_MARKET"),
            from_date=normalize_from_date(_env("FROM_DATE")),
            out_dir=_env("OUT_DIR", "out"),
            cache_dir=_env("CACHE_DIR", ".cache"),
            request_timeout=_env_int("REQUEST_TIMEOUT", 30),
            max_pages=_env_int("KIND_MAX_PAGES", 50),
            page_size=_env_int("KIND_PAGE_SIZE", 100),
        )
