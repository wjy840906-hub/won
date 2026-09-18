"""예약 오픈 시각 대기와 재시도 간격.

`open_at` 이 있으면 그 시각까지 기다렸다가 시도한다.
"오픈런"을 위한 것이 아니라, 사람이 깨어 있지 않아도 되도록 하는 것이므로
기본 간격은 넉넉하게 두고 서버를 두드리는 횟수를 제한한다.
"""

from __future__ import annotations

import logging
import random
import re
import time
from datetime import datetime, timedelta
from typing import Callable

from .config import now_kst
from .scenario import ScenarioError

log = logging.getLogger(__name__)

# 같은 서버를 이보다 자주 두드리지 않는다.
MIN_INTERVAL_SEC = 1.0

_DATETIME = re.compile(r"^(\d{4})[-./](\d{1,2})[-./](\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?$")
_TIME = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")


def resolve_open_at(spec: str, now: datetime) -> datetime | None:
    """오픈 시각 표기를 실제 일시로 바꾼다.

    '09:00' → 오늘 09:00(이미 지났으면 내일 09:00),
    '2026-10-01 09:00' → 그 일시. 빈 값이면 None(즉시 실행).
    """
    text = (spec or "").strip()
    if not text:
        return None

    match = _DATETIME.match(text)
    if match:
        year, month, day, hour, minute, second = match.groups()
        try:
            return datetime(
                int(year), int(month), int(day), int(hour), int(minute), int(second or 0),
                tzinfo=now.tzinfo,
            )
        except ValueError as exc:
            raise ScenarioError(f"open_at 이 잘못되었습니다: {spec!r} — {exc}") from exc

    match = _TIME.match(text)
    if match:
        hour, minute, second = match.groups()
        if int(hour) > 23 or int(minute) > 59:
            raise ScenarioError(f"open_at 시각이 잘못되었습니다: {spec!r}")
        when = now.replace(
            hour=int(hour), minute=int(minute), second=int(second or 0), microsecond=0
        )
        if when <= now:
            when += timedelta(days=1)
        return when

    raise ScenarioError(f"open_at 표기를 알 수 없습니다: {spec!r} (예: 09:00, 2026-10-01 09:00)")


def wait_until(
    when: datetime,
    *,
    now_fn: Callable[[], datetime] = now_kst,
    sleep: Callable[[float], None] = time.sleep,
    chunk_sec: float = 1.0,
    announce_every_sec: float = 60.0,
) -> float:
    """지정한 시각까지 기다린다. 실제로 기다린 초를 돌려준다.

    한 번에 길게 자지 않고 조금씩 나눠 자므로, 중간에 멈추기 쉽고
    남은 시간을 주기적으로 로그로 남길 수 있다.
    """
    waited = 0.0
    next_announce = 0.0
    while True:
        remaining = (when - now_fn()).total_seconds()
        if remaining <= 0:
            break
        if waited >= next_announce:
            log.info("예약 오픈(%s)까지 %.0f초 대기", when.strftime("%Y-%m-%d %H:%M:%S"), remaining)
            next_announce = waited + announce_every_sec
        nap = min(chunk_sec, remaining)
        sleep(nap)
        waited += nap
    return waited


def retry_delay(
    interval_sec: float,
    jitter_sec: float = 0.0,
    *,
    rand: Callable[[], float] = random.random,
) -> float:
    """다음 시도까지 쉴 시간. 흔들림(jitter)을 더해 요청이 겹치지 않게 한다."""
    base = max(interval_sec, MIN_INTERVAL_SEC)
    if jitter_sec <= 0:
        return base
    return base + rand() * jitter_sec


def deadline_passed(started_at: datetime, deadline_sec: float, now: datetime) -> bool:
    """전체 제한 시간을 넘겼는지. deadline_sec 가 0 이면 제한 없음."""
    if deadline_sec <= 0:
        return False
    return (now - started_at).total_seconds() >= deadline_sec
