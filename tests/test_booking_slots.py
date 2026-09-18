"""예약 후보 펼치기와 오픈 시각 대기."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from fake_page import FakeClock

from booking_macro.config import KST
from booking_macro.scenario import ScenarioError
from booking_macro.scheduler import (
    MIN_INTERVAL_SEC,
    deadline_passed,
    resolve_open_at,
    retry_delay,
    wait_until,
)
from booking_macro.slots import resolve_date, resolve_targets

금요일 = date(2026, 9, 18)


@pytest.mark.parametrize(
    "표기, 기대",
    [
        ("2026-10-01", date(2026, 10, 1)),
        ("2026/10/01", date(2026, 10, 1)),
        ("20261001", date(2026, 10, 1)),
        ("today", 금요일),
        ("오늘", 금요일),
        ("내일", date(2026, 9, 19)),
        ("모레", date(2026, 9, 20)),
        ("+7d", date(2026, 9, 25)),
        ("+1w", date(2026, 9, 25)),
        ("-1d", date(2026, 9, 17)),
        ("월", date(2026, 9, 21)),
        ("mon", date(2026, 9, 21)),
        ("월요일", date(2026, 9, 21)),
        ("다음주 월요일", date(2026, 9, 21)),
        ("금", date(2026, 9, 25)),  # 오늘이 금요일이면 다음 금요일
    ],
)
def test_날짜_표기를_실제_날짜로_바꾼다(표기, 기대):
    assert resolve_date(표기, 금요일) == 기대


@pytest.mark.parametrize("표기", ["", "다음달", "2026-13-01", "+7년"])
def test_알_수_없는_날짜는_예를_들어_알려_준다(표기):
    with pytest.raises(ScenarioError):
        resolve_date(표기, 금요일)


def test_목록을_적으면_조합으로_펼쳐지고_순서가_우선순위다():
    targets = resolve_targets(
        (
            {"date": "+7d", "time": ["10:00", "14:00"], "room": "대회의실"},
            {"date": "+7d", "time": "10:00", "room": "소회의실"},
        ),
        금요일,
    )

    assert [target.label for target in targets] == [
        "2026-09-25(금) 10:00 대회의실",
        "2026-09-25(금) 14:00 대회의실",
        "2026-09-25(금) 10:00 소회의실",
    ]
    assert [target.index for target in targets] == [1, 2, 3]


def test_같은_후보가_두_번_나오면_한_번만_시도한다():
    targets = resolve_targets(
        ({"date": "2026-10-01", "time": "10:00"}, {"date": "20261001", "time": "10:00"}),
        금요일,
    )

    assert len(targets) == 1


def test_날짜는_사이트마다_다른_표기로도_쓸_수_있다():
    (target,) = resolve_targets(({"date": "2026-10-01"},), 금요일)

    assert target.fields["date"] == "2026-10-01"
    assert target.fields["date_compact"] == "20261001"
    assert target.fields["date_dot"] == "2026.10.01"
    assert target.fields["year"] == "2026"
    assert target.fields["month"] == "10"
    assert target.fields["day"] == "01"
    assert target.fields["weekday"] == "목"


def test_후보의_빈_목록은_오류다():
    with pytest.raises(ScenarioError, match="비어 있습니다"):
        resolve_targets(({"time": []},), 금요일)


# -- 오픈 시각 ------------------------------------------------------------

아침열시 = datetime(2026, 9, 18, 10, 0, tzinfo=KST)


def test_지난_시각은_다음_날로_잡는다():
    assert resolve_open_at("09:00", 아침열시) == datetime(2026, 9, 19, 9, 0, tzinfo=KST)


def test_아직_안_지난_시각은_오늘로_잡는다():
    assert resolve_open_at("11:30", 아침열시) == datetime(2026, 9, 18, 11, 30, tzinfo=KST)


def test_날짜까지_적으면_그_일시로_잡는다():
    assert resolve_open_at("2026-10-01 09:00", 아침열시) == datetime(2026, 10, 1, 9, 0, tzinfo=KST)


def test_오픈_시각이_없으면_즉시_실행한다():
    assert resolve_open_at("", 아침열시) is None


@pytest.mark.parametrize("표기", ["아침", "25:00", "09시"])
def test_알_수_없는_오픈_시각은_오류다(표기):
    with pytest.raises(ScenarioError):
        resolve_open_at(표기, 아침열시)


def test_오픈_시각까지_나눠_자며_기다린다():
    clock = FakeClock(아침열시)
    열시_반 = datetime(2026, 9, 18, 10, 0, 30, tzinfo=KST)

    waited = wait_until(열시_반, now_fn=clock, sleep=clock.sleep)

    assert waited == pytest.approx(30.0)
    assert clock.now >= 열시_반
    assert max(clock.slept) <= 1.0  # 한 번에 길게 자지 않는다


def test_이미_지난_시각이면_기다리지_않는다():
    clock = FakeClock(아침열시)

    assert wait_until(아침열시, now_fn=clock, sleep=clock.sleep) == 0.0
    assert clock.slept == []


def test_재시도_간격은_최소값_아래로_내려가지_않는다():
    assert retry_delay(0.0) == MIN_INTERVAL_SEC
    assert retry_delay(5.0) == 5.0


def test_흔들림을_더하면_간격이_조금씩_달라진다():
    assert retry_delay(5.0, 2.0, rand=lambda: 0.0) == 5.0
    assert retry_delay(5.0, 2.0, rand=lambda: 1.0) == 7.0


def test_제한_시간을_넘기면_중단_신호를_준다():
    나중 = datetime(2026, 9, 18, 10, 10, tzinfo=KST)

    assert deadline_passed(아침열시, 600, 나중) is True
    assert deadline_passed(아침열시, 1200, 나중) is False
    assert deadline_passed(아침열시, 0, 나중) is False  # 0 = 제한 없음
