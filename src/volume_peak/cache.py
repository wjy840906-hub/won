"""일별 시세 캐시.

같은 종목의 과거 시세는 바뀌지 않으므로, 한 번 받아 두고 다음 실행 때는
마지막 저장일 다음 날부터만 이어 받는다(매일 도는 자동화에서 조회량을 줄인다).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .krx_client import DailyBar

log = logging.getLogger(__name__)

SCHEMA = 1


@dataclass
class CachedHistory:
    """캐시에 담긴 한 종목의 이력."""

    bars: list[DailyBar]
    start: str = ""   # 이 캐시가 담고 있는 조회 구간의 시작
    end: str = ""     # 〃 끝


def merge_bars(old: list[DailyBar], new: list[DailyBar]) -> list[DailyBar]:
    """날짜 기준으로 합치고(새 값 우선) 날짜순으로 정렬한다."""
    merged: dict[str, DailyBar] = {bar.date: bar for bar in old}
    for bar in new:
        merged[bar.date] = bar
    return [merged[day] for day in sorted(merged)]


class HistoryCache:
    """종목별 일별 시세를 JSON 파일로 보관한다."""

    def __init__(self, cache_dir: str | Path, namespace: str = "krx_daily") -> None:
        self.root = Path(cache_dir) / namespace

    def path_for(self, code: str) -> Path:
        return self.root / f"{code}.json"

    def load(self, code: str) -> CachedHistory | None:
        path = self.path_for(code)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("schema") != SCHEMA:
                return None
            bars = [
                DailyBar(date=row[0], volume=int(row[1]), close=int(row[2]), value=int(row[3]))
                for row in payload.get("bars", [])
            ]
        except (OSError, ValueError, TypeError, IndexError) as exc:
            log.debug("캐시를 읽지 못해 새로 받습니다(%s): %s", code, exc)
            return None
        return CachedHistory(
            bars=bars, start=payload.get("start", ""), end=payload.get("end", "")
        )

    def save(self, code: str, history: CachedHistory) -> None:
        path = self.path_for(code)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": SCHEMA,
            "code": code,
            "start": history.start,
            "end": history.end,
            "bars": [[bar.date, bar.volume, bar.close, bar.value] for bar in history.bars],
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)


def plan_fetch(cached: CachedHistory | None, start: str, end: str) -> tuple[str, str] | None:
    """캐시를 보고 실제로 조회해야 할 구간을 정한다(None 이면 조회 불필요).

    - 캐시 없음 / 시작이 더 이르다 → 전 구간 다시
    - 끝만 모자람 → 마지막 저장일부터 이어서(경계일은 겹쳐 받아 빠짐을 막는다)
    """
    if cached is None or not cached.bars or not cached.start or cached.start > start:
        return start, end
    if cached.end >= end:
        return None
    return cached.end, end
