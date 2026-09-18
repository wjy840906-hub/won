"""거래량 신고점 선별 설정(환경변수 + CLI 기본값)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

# SMTP 설정과 KST 시각은 관리종목 파이프라인과 같은 것을 쓴다.
from kind_managed.config import KST, MailConfig, now_kst  # noqa: F401  (재노출)

MARKET_CHOICES = {
    "": "전체",
    "ALL": "전체",
    "STK": "유가증권",
    "KSQ": "코스닥",
    "KNX": "코넥스",
    "유가증권": "유가증권",
    "코스피": "유가증권",
    "코스닥": "코스닥",
    "코넥스": "코넥스",
}

_MARKET_IDS = {
    "": "ALL",
    "ALL": "ALL",
    "STK": "STK",
    "KSQ": "KSQ",
    "KNX": "KNX",
    "유가증권": "STK",
    "코스피": "STK",
    "코스닥": "KSQ",
    "코넥스": "KNX",
}

SORT_CHOICES = ("value", "ratio", "volume")


def normalize_market(raw: str) -> str:
    """'코스닥' · 'KSQ' · '' 등을 KRX mktId 로 바꾼다."""
    key = (raw or "").strip()
    if key.upper() in _MARKET_IDS:
        return _MARKET_IDS[key.upper()]
    if key in _MARKET_IDS:
        return _MARKET_IDS[key]
    raise ValueError(f"시장 구분을 알 수 없습니다: {raw!r} (ALL/STK/KSQ/KNX, 유가증권/코스닥/코넥스)")


def normalize_date(raw: str) -> str:
    """'2026-09-17' · '20260917' · '2026.09.17' 을 YYYY-MM-DD 로 통일한다(빈 값=최근 영업일)."""
    text = (raw or "").strip()
    if not text:
        return ""
    match = re.fullmatch(r"(\d{4})\D?(\d{1,2})\D?(\d{1,2})", text)
    if not match:
        raise ValueError(f"날짜 형식을 알 수 없습니다: {raw!r} (예: 2026-09-17)")
    year, month, day = match.groups()
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError as exc:
        raise ValueError(f"존재하지 않는 날짜입니다: {raw!r}") from exc


def to_krx_date(value: str) -> str:
    """YYYY-MM-DD → YYYYMMDD (KRX 파라미터 형식)."""
    return (value or "").replace("-", "")


def years_before(as_of: str, years: int) -> str:
    """as_of 로부터 years 년 전 날짜(윈도 시작일)를 돌려준다."""
    anchor = datetime.strptime(as_of, "%Y-%m-%d").date()
    try:
        start = anchor.replace(year=anchor.year - years)
    except ValueError:  # 2월 29일
        start = anchor.replace(year=anchor.year - years, day=28)
    return (start + timedelta(days=1)).isoformat()


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw.replace(",", "").replace("_", ""))
    except ValueError as exc:
        raise ValueError(f"환경변수 {name} 값이 정수가 아닙니다: {raw!r}") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class ScreenConfig:
    """선별 조건."""

    trade_date: str = ""          # 기준일(빈 값이면 최근 영업일)
    years: int = 10               # 비교 기간(년)
    market: str = "ALL"           # ALL/STK/KSQ/KNX
    min_volume: int = 100_000     # 기준일 거래량 하한(주)
    min_value: int = 1_000_000_000  # 기준일 거래대금 하한(원)
    min_history_days: int = 250   # 최소 거래일 수(이보다 짧으면 신규상장으로 보고 제외)
    include_short_history: bool = False  # 이력이 짧아도 후보에 남길지
    include_preferred: bool = False      # 우선주·신주인수권 등 포함 여부
    top: int = 0                  # 0 이면 전부
    sort: str = "value"           # value/ratio/volume
    workers: int = 8              # 개별 종목 시세 동시 조회 수
    out_dir: str = "out"
    cache_dir: str = ".cache"
    request_timeout: int = 30

    @classmethod
    def from_env(cls) -> "ScreenConfig":
        return cls(
            trade_date=normalize_date(_env("TRADE_DATE")),
            years=_env_int("VOLUME_YEARS", 10),
            market=normalize_market(_env("KRX_MARKET")),
            min_volume=_env_int("MIN_VOLUME", 100_000),
            min_value=_env_int("MIN_VALUE", 1_000_000_000),
            min_history_days=_env_int("MIN_HISTORY_DAYS", 250),
            include_short_history=_env_bool("INCLUDE_SHORT_HISTORY", False),
            include_preferred=_env_bool("INCLUDE_PREFERRED", False),
            top=_env_int("TOP_N", 0),
            sort=(_env("SORT_BY", "value") or "value"),
            workers=_env_int("KRX_WORKERS", 8),
            out_dir=_env("OUT_DIR", "out"),
            cache_dir=_env("CACHE_DIR", ".cache"),
            request_timeout=_env_int("REQUEST_TIMEOUT", 30),
        )

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.years < 1:
            problems.append("비교 기간(--years)은 1년 이상이어야 합니다.")
        if self.sort not in SORT_CHOICES:
            problems.append(f"정렬 기준(--sort)은 {'/'.join(SORT_CHOICES)} 중 하나여야 합니다.")
        if self.workers < 1:
            problems.append("동시 조회 수(--workers)는 1 이상이어야 합니다.")
        return problems

    @property
    def market_label(self) -> str:
        return MARKET_CHOICES.get(self.market, self.market)
