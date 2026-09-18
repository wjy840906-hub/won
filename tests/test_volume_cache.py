"""일별 시세 캐시 테스트."""

from __future__ import annotations

import json

from volume_peak.cache import CachedHistory, HistoryCache, merge_bars, plan_fetch
from volume_peak.krx_client import DailyBar


def bars(*pairs) -> list[DailyBar]:
    return [DailyBar(date=day, volume=vol, close=10, value=vol * 10) for day, vol in pairs]


def test_저장하고_다시_읽는다(tmp_path):
    cache = HistoryCache(tmp_path)
    history = CachedHistory(bars=bars(("2026-09-16", 100), ("2026-09-17", 200)), start="2016-09-18", end="2026-09-17")
    cache.save("005930", history)

    loaded = cache.load("005930")
    assert loaded is not None
    assert loaded.start == "2016-09-18"
    assert loaded.end == "2026-09-17"
    assert [(bar.date, bar.volume) for bar in loaded.bars] == [
        ("2026-09-16", 100),
        ("2026-09-17", 200),
    ]


def test_없는_종목과_깨진_파일은_None(tmp_path):
    cache = HistoryCache(tmp_path)
    assert cache.load("000000") is None

    path = cache.path_for("000001")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{그냥 깨진 파일", encoding="utf-8")
    assert cache.load("000001") is None


def test_스키마가_다르면_무시한다(tmp_path):
    cache = HistoryCache(tmp_path)
    path = cache.path_for("000002")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": 99, "bars": []}), encoding="utf-8")
    assert cache.load("000002") is None


def test_합칠_때_새_값이_이긴다():
    merged = merge_bars(
        bars(("2026-09-16", 100), ("2026-09-17", 200)),
        bars(("2026-09-17", 250), ("2026-09-18", 300)),
    )
    assert [(bar.date, bar.volume) for bar in merged] == [
        ("2026-09-16", 100),
        ("2026-09-17", 250),
        ("2026-09-18", 300),
    ]


def test_조회_구간_계획():
    cached = CachedHistory(bars=bars(("2026-09-17", 1)), start="2016-09-18", end="2026-09-17")

    # 캐시가 없으면 전 구간
    assert plan_fetch(None, "2016-09-18", "2026-09-18") == ("2016-09-18", "2026-09-18")
    # 끝만 모자라면 마지막 저장일부터 이어서(경계일은 겹쳐 받는다)
    assert plan_fetch(cached, "2016-09-18", "2026-09-18") == ("2026-09-17", "2026-09-18")
    # 이미 다 있으면 조회하지 않는다
    assert plan_fetch(cached, "2016-09-18", "2026-09-17") is None
    # 더 이른 시작일을 요구하면 전 구간 다시
    assert plan_fetch(cached, "2010-01-01", "2026-09-17") == ("2010-01-01", "2026-09-17")
    # 비어 있는 캐시도 전 구간
    empty = CachedHistory(bars=[], start="2016-09-18", end="2026-09-17")
    assert plan_fetch(empty, "2016-09-18", "2026-09-17") == ("2016-09-18", "2026-09-17")
