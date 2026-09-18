"""표(코트 × 시간)에서 칸을 고르는 click_cell."""

from __future__ import annotations

import pytest
from fake_page import FakePage

from booking_macro.config import BookingConfig
from booking_macro.runner import Outcome, run_scenario
from booking_macro.scenario import ScenarioError, Step, parse_scenario
from booking_macro.steps import SlotUnavailable, StepContext, StepError, run_step

설정 = BookingConfig(screenshot="never")


def 단계(**바꿀_내용):
    기본 = {"click_cell": "{{ target.court }}", "row": "{{ target.time }}"}
    return Step.parse({**기본, **바꿀_내용}, "reserve.steps[0]")


def 맥락():
    return StepContext(
        config=설정,
        variables={"target": {"court": "실외코트5", "time": "09:00~10:00"}},
    )


# -- 시나리오 문법 ---------------------------------------------------------


def test_짧은_표기는_열_이름으로_읽는다():
    step = Step.parse({"click_cell": "실외코트5", "row": "09:00~10:00"}, "s")

    assert step.action == "click_cell"
    assert step.column == "실외코트5"
    assert step.row == "09:00~10:00"


def test_달력처럼_열_없이_글자만으로도_찾는다():
    step = Step.parse({"click_cell": None, "contains": ["19", "예약가능"]}, "s")

    assert step.contains == ("19", "예약가능")
    assert step.column == ""


def test_조건이_하나도_없으면_오류다():
    with pytest.raises(ScenarioError, match="column · row · contains · exact 중 하나"):
        Step.parse({"click_cell": None}, "reserve.steps[0]")


def test_표_조건은_click_cell_에서만_쓸_수_있다():
    with pytest.raises(ScenarioError, match="click_cell 에서만"):
        Step.parse({"click": "#btn", "row": "09:00"}, "reserve.steps[0]")


def test_무엇을_찾는지_설명에_드러난다():
    assert 단계().describe() == "click_cell {{ target.court }} × {{ target.time }}"


# -- 실행 -----------------------------------------------------------------


def test_찾은_칸을_클릭한다():
    page = FakePage()
    page.evaluate_result = {"found": True, "text": "예약가능", "matched": 1}

    run_step(page, 단계(), 맥락(), "reserve.steps[0]")

    assert page.clicked == ['[data-booking-cell="1"]']


def test_자리표시자를_채워서_찾는다():
    page = FakePage()
    page.evaluate_result = {"found": True, "matched": 1}

    run_step(page, 단계(), 맥락(), "reserve.steps[0]")

    assert page.evaluate_args[0] == {
        "column": "실외코트5",
        "row": "09:00~10:00",
        "contains": [],
        "exact": [],
    }


def test_칸에_담긴_글자로도_찾는다():
    page = FakePage()
    page.evaluate_result = {"found": True, "matched": 1}
    step = Step.parse({"click_cell": None, "contains": ["{{ target.day }}", "예약가능"]}, "s")
    context = StepContext(config=설정, variables={"target": {"day": "19"}})

    run_step(page, step, context, "reserve.steps[0]")

    assert page.evaluate_args[0]["contains"] == ["19", "예약가능"]


def test_칸은_있는데_누를_게_없으면_마감으로_본다():
    page = FakePage()
    page.evaluate_result = {"found": False, "reason": "unavailable", "text": "×", "matched": 1}

    with pytest.raises(SlotUnavailable) as error:
        run_step(page, 단계(), 맥락(), "reserve.steps[0]")

    assert "실외코트5 × 09:00~10:00" in str(error.value)
    assert "이미 찼거나" in str(error.value)
    assert page.clicked == []


def test_그런_열_행이_아예_없으면_실패이고_고칠_곳을_알려_준다():
    page = FakePage()
    page.evaluate_result = {"found": False, "reason": "missing", "matched": 0}

    with pytest.raises(StepError) as error:
        run_step(page, 단계(), 맥락(), "reserve.steps[0]")

    assert not isinstance(error.value, SlotUnavailable)
    assert "해당하는 칸이 없습니다" in str(error.value)
    assert "--probe" in str(error.value)


def test_모의_실행에서는_확정_표시가_붙은_칸을_누르지_않는다():
    page = FakePage()
    page.evaluate_result = {"found": True, "matched": 1}
    context = 맥락()
    context.dry_run = True

    run_step(page, 단계(commit=True), context, "reserve.steps[0]")

    assert page.clicked == []
    assert page.evaluate_args == []


# -- 후보 넘어가기 ---------------------------------------------------------


def 표_시나리오():
    return parse_scenario(
        {
            "name": "테니스장",
            "base_url": "https://example.or.kr",
            "attempts": 1,
            "targets": [{"court": ["실외코트4", "실외코트5"], "time": "09:00~10:00"}],
            "reserve": {
                "url": "/tennis",
                "steps": [
                    {"click_cell": "{{ target.court }}", "row": "{{ target.time }}"},
                    {"click": "#btnApply", "commit": True},
                ],
                "success_when": {"text_contains": "예약이 접수"},
            },
        }
    )


def test_찬_코트는_건너뛰고_다음_코트를_잡는다():
    page = FakePage()
    # 1순위(실외코트4)는 누를 게 없고, 2순위(실외코트5)는 가능하다.
    page.evaluate_result = [
        {"found": False, "reason": "unavailable", "text": "×", "matched": 1},
        {"found": True, "matched": 1},
    ]
    page.on_click = {"#btnApply": lambda p: setattr(p, "text", "예약이 접수되었습니다")}

    result = run_scenario(표_시나리오(), 설정, page, wait_open=False)

    assert [attempt.outcome for attempt in result.attempts] == [Outcome.TAKEN, Outcome.SUCCESS]
    assert result.reserved.target.fields["court"] == "실외코트5"


def test_표에서_칸을_못_찾으면_실패로_기록하고_다음_후보로_간다():
    page = FakePage()
    page.evaluate_result = [
        {"found": False, "reason": "missing", "matched": 0},
        {"found": True, "matched": 1},
    ]
    page.on_click = {"#btnApply": lambda p: setattr(p, "text", "예약이 접수되었습니다")}

    result = run_scenario(표_시나리오(), 설정, page, wait_open=False)

    assert [attempt.outcome for attempt in result.attempts] == [Outcome.FAILED, Outcome.SUCCESS]


def test_날짜는_정확히_같은_값으로_찾는다():
    # '5' 를 찾을 때 '15'·'25' 가 걸리면 엉뚱한 날짜를 예약하게 된다.
    page = FakePage()
    page.evaluate_result = {"found": True, "matched": 1}
    step = Step.parse(
        {"click_cell": None, "exact": "{{ target.day_no }}", "contains": "예약가능"}, "s"
    )
    context = StepContext(config=설정, variables={"target": {"day_no": "5"}})

    run_step(page, step, context, "reserve.steps[0]")

    assert page.evaluate_args[0]["exact"] == ["5"]
    assert page.evaluate_args[0]["contains"] == ["예약가능"]
