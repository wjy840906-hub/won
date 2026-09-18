"""신고 거래량 판정 로직 테스트."""

from __future__ import annotations

import pytest

from volume_peak.config import normalize_date, normalize_market, years_before
from volume_peak.krx_client import DailyBar, Quote
from volume_peak.screener import (
    evaluate,
    filter_candidates,
    screen,
    to_rows,
    window_bars,
)

AS_OF = "2026-09-17"
START = years_before(AS_OF, 10)  # 2016-09-18


def quote(code="005930", name="삼성전자", volume=1_000, value=10**9, **kwargs) -> Quote:
    return Quote(
        code=code,
        name=name,
        market=kwargs.pop("market", "KOSPI"),
        close=kwargs.pop("close", 70_000),
        change_rate=kwargs.pop("change_rate", 5.0),
        volume=volume,
        value=value,
        **kwargs,
    )


def bars(*pairs) -> list[DailyBar]:
    return [DailyBar(date=day, volume=vol, close=1_000, value=vol * 1_000) for day, vol in pairs]


def test_기간_시작일_계산():
    assert years_before("2026-09-17", 10) == "2016-09-18"
    # 윤년 2월 29일: 1년 전이 없으므로 28일 기준으로 잡는다.
    assert years_before("2024-02-29", 1) == "2023-03-01"


def test_기준일이_기간내_최고면_선정된다():
    history = bars(("2017-05-02", 800), ("2020-03-19", 900), (AS_OF, 1_000))
    hit = evaluate(quote(volume=1_000), history, AS_OF, START)

    assert hit is not None
    assert hit.volume == 1_000
    assert hit.prev_peak == 900
    assert hit.prev_peak_date == "2020-03-19"
    assert hit.ratio == pytest.approx(1.11)
    assert hit.history_from == "2017-05-02"


def test_기간_밖의_더_큰_거래량은_보지_않는다():
    # 10년보다 이전(2015년)의 대량 거래는 비교 대상이 아니다.
    history = bars(("2015-01-05", 5_000), ("2020-03-19", 900), (AS_OF, 1_000))
    hit = evaluate(quote(volume=1_000), history, AS_OF, START)

    assert hit is not None
    assert hit.prev_peak == 900


def test_최고치가_아니면_제외():
    history = bars(("2020-03-19", 1_200), (AS_OF, 1_000))
    assert evaluate(quote(volume=1_000), history, AS_OF, START) is None


def test_직전_최고치와_같기만_하면_제외():
    history = bars(("2020-03-19", 1_000), (AS_OF, 1_000))
    assert evaluate(quote(volume=1_000), history, AS_OF, START) is None


def test_같은_최고치가_여러번이면_가장_최근일이_직전_기록일():
    history = bars(("2018-01-05", 900), ("2021-06-10", 900), (AS_OF, 1_000))
    hit = evaluate(quote(volume=1_000), history, AS_OF, START)

    assert hit is not None
    assert hit.prev_peak_date == "2021-06-10"


def test_기준일_이력이_없으면_스냅샷_거래량을_쓴다():
    history = bars(("2020-03-19", 900))
    hit = evaluate(quote(volume=1_500), history, AS_OF, START)

    assert hit is not None
    assert hit.volume == 1_500


def test_비교할_과거가_없으면_제외():
    assert evaluate(quote(volume=1_000), bars((AS_OF, 1_000)), AS_OF, START) is None


def test_이력이_짧으면_기본적으로_제외되고_옵션으로_포함된다():
    history = bars(("2026-08-03", 500), (AS_OF, 1_000))

    assert evaluate(quote(volume=1_000), history, AS_OF, START, min_history_days=250) is None

    hit = evaluate(
        quote(volume=1_000),
        history,
        AS_OF,
        START,
        min_history_days=250,
        include_short_history=True,
    )
    assert hit is not None
    assert "이력 2거래일" in hit.note


def test_거래량_거래대금_하한과_보통주_필터():
    quotes = [
        quote(code="005930", volume=1_000_000, value=10**11),
        quote(code="123450", name="적은거래", volume=1_000, value=10**6),
        quote(code="005935", name="삼성전자우", volume=1_000_000, value=10**11),
    ]
    kept = filter_candidates(quotes, min_volume=100_000, min_value=10**9)
    assert [item.code for item in kept] == ["005930"]

    with_preferred = filter_candidates(
        quotes, min_volume=100_000, min_value=10**9, include_preferred=True
    )
    assert [item.code for item in with_preferred] == ["005930", "005935"]


def test_기간_자르기():
    history = bars(("2015-01-02", 1), ("2020-01-02", 2), ("2026-09-18", 3))
    assert [bar.date for bar in window_bars(history, START, AS_OF)] == ["2020-01-02"]


def test_정렬과_상위_N():
    quotes = [
        quote(code="000100", name="가", volume=300, value=300),
        quote(code="000200", name="나", volume=900, value=100),
        quote(code="000300", name="다", volume=200, value=200),
    ]
    histories = {
        "000100": bars(("2020-01-02", 100), (AS_OF, 300)),   # 3.0배
        "000200": bars(("2020-01-02", 800), (AS_OF, 900)),   # 1.12배
        "000300": bars(("2020-01-02", 10), (AS_OF, 200)),    # 20배
    }

    by_value = screen(quotes, histories, AS_OF, START, sort="value")
    assert [item.code for item in by_value] == ["000100", "000300", "000200"]

    by_ratio = screen(quotes, histories, AS_OF, START, sort="ratio")
    assert [item.code for item in by_ratio] == ["000300", "000100", "000200"]

    by_volume = screen(quotes, histories, AS_OF, START, sort="volume", top=2)
    assert [item.code for item in by_volume] == ["000200", "000100"]


def test_이력이_없는_종목은_건너뛴다():
    assert screen([quote()], {}, AS_OF, START) == []


def test_엑셀용_행_변환():
    history = bars(("2020-03-19", 900), (AS_OF, 1_800))
    rows = to_rows(screen([quote(volume=1_800)], {"005930": history}, AS_OF, START))

    assert rows[0]["no"] == "1"
    assert rows[0]["code"] == "005930"
    assert rows[0]["volume"] == "1,800"
    assert rows[0]["ratio"] == "2.00배"
    assert rows[0]["change_rate"] == "+5.00%"


def test_시장_날짜_표기_변환():
    assert normalize_market("코스닥") == "KSQ"
    assert normalize_market("") == "ALL"
    assert normalize_date("2026.09.17") == "2026-09-17"
    with pytest.raises(ValueError):
        normalize_market("나스닥")
    with pytest.raises(ValueError):
        normalize_date("2026-13-01")
