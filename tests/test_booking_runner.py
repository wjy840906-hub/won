"""가짜 페이지로 예약 흐름 전체를 검증한다(브라우저 없음)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest
from fake_page import FakeClock, FakePage

from booking_macro.config import KST, BookingConfig
from booking_macro.notify import build_body_text, build_subject
from booking_macro.runner import Outcome, run_scenario
from booking_macro.scenario import parse_scenario

지금 = datetime(2026, 9, 18, 10, 0, tzinfo=KST)

성공문구 = "예약이 완료되었습니다"
마감문구 = "이미 예약된 시간입니다"


def 시나리오(**바꿀_내용):
    data = {
        "name": "회의실 예약",
        "base_url": "https://example.com",
        "login": {
            "url": "/login",
            "steps": [
                {"fill": "#id", "value": "{{ env.BOOKING_USER }}"},
                {"fill": "#pw", "value": "{{ env.BOOKING_PASSWORD }}"},
                {"click": "#submit"},
            ],
            "success_when": {"visible": ".me"},
        },
        "targets": [
            {"date": "2026-10-01", "time": ["10:00", "14:00"]},
        ],
        "reserve": {
            "url": "/rooms?d={{ target.date }}&t={{ target.time }}",
            "steps": [
                {"accept_dialog": True},
                {"click": "#reserve", "commit": True},
            ],
            "success_when": {"text_contains": 성공문구},
            "taken_when": {"text_contains": 마감문구},
        },
        "attempts": 1,
        "interval_sec": 1,
    }
    data.update(바꿀_내용)
    return parse_scenario(data)


@pytest.fixture(autouse=True)
def 계정(monkeypatch):
    monkeypatch.setenv("BOOKING_USER", "hong")
    monkeypatch.setenv("BOOKING_PASSWORD", "비밀번호")


@pytest.fixture
def 설정(tmp_path):
    return BookingConfig(out_dir=str(tmp_path / "shots"), screenshot="change")


def 실행(scenario, page, 설정, **kwargs):
    clock = FakeClock(지금)
    kwargs.setdefault("now_fn", clock)
    kwargs.setdefault("sleep", clock.sleep)
    return run_scenario(scenario, 설정, page, **kwargs), clock


def test_첫_후보가_되면_거기서_멈춘다(설정):
    page = FakePage(visible={".me"}, on_click={"#reserve": lambda p: setattr(p, "text", 성공문구)})

    result, _ = 실행(시나리오(), page, 설정)

    assert result.succeeded
    assert result.reserved.target.label == "2026-10-01(목) 10:00"
    assert len(result.attempts) == 1  # 2순위는 시도하지 않는다
    이동한_주소 = [url for action, url, _ in page.actions if action == "goto"]
    assert 이동한_주소 == [
        "https://example.com/login",
        "https://example.com/rooms?d=2026-10-01&t=10:00",
    ]


def test_1순위가_마감이면_2순위로_넘어간다(설정):
    page = FakePage(visible={".me"}, text=마감문구)

    def 두_번째부터_성공(p: FakePage) -> None:
        if "t=14:00" in p.url:
            p.text = 성공문구

    page.on_click["#reserve"] = 두_번째부터_성공

    result, _ = 실행(시나리오(), page, 설정)

    assert [attempt.outcome for attempt in result.attempts] == [Outcome.TAKEN, Outcome.SUCCESS]
    assert result.reserved.target.label == "2026-10-01(목) 14:00"


def test_아무_후보도_못_잡으면_실패로_끝난다(설정):
    page = FakePage(visible={".me"}, text=마감문구)

    result, _ = 실행(시나리오(), page, 설정)

    assert not result.succeeded
    assert result.reserved is None
    assert all(attempt.outcome is Outcome.TAKEN for attempt in result.attempts)
    assert "예약하지 못했습니다" in result.summary()


def test_마감이면_간격을_두고_다시_돈다(설정):
    page = FakePage(visible={".me"}, text=마감문구)

    def 두_번째_회차에_열림(p: FakePage) -> None:
        if len([a for a in p.actions if a[0] == "click" and a[1] == "#reserve"]) >= 3:
            p.text = 성공문구

    page.on_click["#reserve"] = 두_번째_회차에_열림

    result, clock = 실행(시나리오(attempts=2, interval_sec=10), page, 설정)

    assert result.succeeded
    assert result.rounds == 2
    assert clock.total_slept == pytest.approx(10.0)  # 회차 사이에 한 번만 쉰다


def test_제한_시간을_넘기면_다음_회차로_가지_않는다(설정):
    page = FakePage(visible={".me"}, text=마감문구)
    clock = FakeClock(지금)

    def 느린_클릭(p: FakePage) -> None:
        clock.sleep(400)

    page.on_click["#reserve"] = 느린_클릭

    result = run_scenario(
        시나리오(attempts=5, interval_sec=1, deadline_sec=600),
        설정,
        page,
        now_fn=clock,
        sleep=clock.sleep,
    )

    assert result.rounds == 1
    assert "제한 시간" in result.error


def test_로그인에_실패하면_예약을_시도하지_않는다(설정):
    page = FakePage(visible=set())  # .me 가 없다 = 로그인 실패

    result, _ = 실행(시나리오(), page, 설정)

    assert result.attempts == []
    assert "로그인" in result.error
    assert "#reserve" not in page.clicked


def test_로그인_단계_자체가_깨져도_이유가_남는다(설정):
    page = FakePage(visible={".me"}, fail_on={"#submit": "버튼이 없습니다"})

    result, _ = 실행(시나리오(), page, 설정)

    assert "로그인 실패" in result.error
    assert "#submit" in result.error


def test_로그인_없는_시나리오도_돈다(설정):
    data = 시나리오()
    scenario = replace(data, login=None)
    page = FakePage(on_click={"#reserve": lambda p: setattr(p, "text", 성공문구)})

    result, _ = 실행(scenario, page, 설정)

    assert result.succeeded


def test_모의_실행은_확정_단계를_누르지_않는다(설정):
    page = FakePage(visible={".me"})

    result, _ = 실행(시나리오(), page, replace(설정, dry_run=True))

    assert result.reserved is not None
    assert result.reserved.outcome is Outcome.DRY_RUN
    assert "#reserve" not in page.clicked
    assert any("모의" in step for step in result.reserved.steps)
    assert "모의 실행 성공" in result.summary()


def test_모의_실행이어도_마감은_마감으로_본다(설정):
    page = FakePage(visible={".me"}, text=마감문구)

    result, _ = 실행(시나리오(), page, replace(설정, dry_run=True))

    assert result.reserved is None
    assert all(attempt.outcome is Outcome.TAKEN for attempt in result.attempts)


def test_확인_대화창을_수락한다(설정):
    page = FakePage(visible={".me"}, on_click={"#reserve": lambda p: setattr(p, "text", 성공문구)})

    실행(시나리오(), page, 설정)

    assert page.fire_dialog().accepted is True


def test_한_후보가_깨져도_다음_후보를_시도한다(설정):
    scenario = 시나리오(
        reserve={
            "url": "/rooms?t={{ target.time }}",
            "steps": [{"wait_for": ".slot"}, {"click": "#reserve", "commit": True}],
            "success_when": {"text_contains": 성공문구},
        }
    )
    page = FakePage(visible={".me"}, fail_on={})

    def 두_번째만_정상(p: FakePage) -> None:
        p.text = 성공문구

    page.on_click["#reserve"] = 두_번째만_정상
    original_wait = page.wait_for_selector

    def 첫_후보에서만_실패(selector: str, **kwargs):
        if selector == ".slot" and "t=10:00" in page.url:
            raise RuntimeError("목록을 못 찾음")
        page.visible.add(selector)
        return original_wait(selector, **kwargs)

    page.wait_for_selector = 첫_후보에서만_실패

    result, _ = 실행(scenario, page, 설정)

    assert [attempt.outcome for attempt in result.attempts] == [Outcome.FAILED, Outcome.SUCCESS]
    assert "목록을 못 찾음" in result.attempts[0].message


def test_optional_단계는_실패해도_넘어간다(설정):
    scenario = 시나리오(
        reserve={
            "url": "/rooms",
            "steps": [
                {"fill": "#purpose", "value": "회의", "optional": True},
                {"click": "#reserve", "commit": True},
            ],
            "success_when": {"text_contains": 성공문구},
        }
    )
    page = FakePage(
        visible={".me"},
        fail_on={"#purpose": "그런 칸 없음"},
        on_click={"#reserve": lambda p: setattr(p, "text", 성공문구)},
    )

    result, _ = 실행(scenario, page, 설정)

    assert result.succeeded
    assert any("건너뜀" in step for step in result.reserved.steps)


def test_성공_문구가_없으면_성공으로_치지_않는다(설정):
    page = FakePage(visible={".me"}, text="다시 시도해 주세요")

    result, _ = 실행(시나리오(), page, 설정)

    assert result.reserved is None
    assert all(attempt.outcome is Outcome.FAILED for attempt in result.attempts)
    assert "성공 확인 실패" in result.attempts[0].message


def test_환경변수가_비면_브라우저를_건드리기_전에_멈춘다(설정, monkeypatch):
    monkeypatch.delenv("BOOKING_PASSWORD", raising=False)
    page = FakePage(visible={".me"})

    with pytest.raises(ValueError, match="BOOKING_PASSWORD"):
        실행(시나리오(), page, 설정)

    assert page.actions == []


def test_오픈_시각까지_기다렸다가_시도한다(설정):
    page = FakePage(visible={".me"}, on_click={"#reserve": lambda p: setattr(p, "text", 성공문구)})
    clock = FakeClock(지금)

    run_scenario(시나리오(open_at="10:05"), 설정, page, now_fn=clock, sleep=clock.sleep)

    assert clock.total_slept == pytest.approx(300.0)


def test_now_옵션이면_오픈_시각을_무시한다(설정):
    page = FakePage(visible={".me"}, on_click={"#reserve": lambda p: setattr(p, "text", 성공문구)})
    clock = FakeClock(지금)

    run_scenario(시나리오(open_at="10:05"), 설정, page, now_fn=clock, sleep=clock.sleep, wait_open=False)

    assert clock.total_slept == 0.0


def test_결과_화면을_파일로_남긴다(설정):
    page = FakePage(visible={".me"}, on_click={"#reserve": lambda p: setattr(p, "text", 성공문구)})

    result, _ = 실행(시나리오(), page, 설정)

    assert result.screenshots
    assert result.screenshots[0].exists()


def test_화면_저장을_끌_수_있다(설정):
    page = FakePage(visible={".me"}, on_click={"#reserve": lambda p: setattr(p, "text", 성공문구)})

    result, _ = 실행(시나리오(), page, replace(설정, screenshot="never"))

    assert result.screenshots == []


def test_결과_메일_제목과_본문에_핵심이_담긴다(설정):
    page = FakePage(visible={".me"}, on_click={"#reserve": lambda p: setattr(p, "text", 성공문구)})

    result, _ = 실행(시나리오(), page, 설정)
    본문 = build_body_text(result)

    assert build_subject(result) == "[예약 성공] 회의실 예약 — 2026-10-01(목) 10:00"
    assert "2026-10-01(목) 10:00" in 본문
    assert "비밀번호" not in 본문  # 자격증명이 메일에 실리지 않는다


def test_실패한_결과의_메일_제목은_실패로_남는다(설정):
    page = FakePage(visible={".me"}, text=마감문구)

    result, _ = 실행(시나리오(), page, 설정)

    assert build_subject(result) == "[예약 실패] 회의실 예약"
    assert "마감" in build_body_text(result)
