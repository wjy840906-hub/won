"""시나리오 파싱·검증과 자리표시자 치환."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from booking_macro.config import scenario_env
from booking_macro.scenario import ScenarioError, Step, load_scenario, parse_scenario
from booking_macro.template import TemplateError, render

EXAMPLE = Path(__file__).resolve().parents[1] / "scenarios" / "example-meeting-room.yaml"

MINIMAL = {
    "name": "테스트 예약",
    "base_url": "https://example.com/",
    "targets": [{"date": "2026-10-01", "time": "10:00"}],
    "reserve": {
        "url": "/book?d={{ target.date }}",
        "steps": [{"click": "#go"}],
        "success_when": {"text_contains": "예약이 완료"},
    },
}


def test_예제_시나리오가_그대로_읽힌다():
    scenario = load_scenario(EXAMPLE)

    assert scenario.name == "사내 회의실 예약"
    assert scenario.base_url == "https://booking.example.com"  # 끝 슬래시 제거
    assert scenario.open_at == "09:00"
    assert scenario.attempts == 3
    assert scenario.login is not None
    assert scenario.env_names == ["BOOKING_USER", "BOOKING_PASSWORD"]
    assert scenario.reserve.taken_when.text_contains == ("이미 예약된", "선택하신 시간은 마감")

    commit_steps = [step for step in scenario.reserve.steps if step.commit]
    assert [step.selector for step in commit_steps] == ["#btnReserve"]


def test_JSON_시나리오도_읽는다(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps(MINIMAL, ensure_ascii=False), encoding="utf-8")

    scenario = load_scenario(path)

    assert scenario.name == "테스트 예약"
    assert scenario.reserve.steps[0].action == "click"


def test_짧은_표기와_긴_표기가_같은_결과를_준다():
    short = Step.parse({"fill": "#id", "value": "hong"}, "s")
    long = Step.parse({"action": "fill", "selector": "#id", "value": "hong"}, "s")

    assert short == long


def test_비밀번호는_단계_설명에_찍히지_않는다():
    step = Step.parse({"fill": "#pw", "value": "{{ env.BOOKING_PASSWORD }}"}, "s")

    assert "BOOKING_PASSWORD" not in step.describe()
    assert step.describe() == "fill #pw = ****"


@pytest.mark.parametrize(
    "raw, 포함_문구",
    [
        ({"jump": "#a"}, "액션을 하나만"),
        ({"click": "#a", "fill": "#b"}, "액션을 하나만"),
        ({"fill": "#a"}, "값이 필요합니다"),
        ({"click": ""}, "셀렉터가 필요합니다"),
        ({"wait_ms": "곧"}, "숫자가 아닙니다"),
        ({"click": "#a", "timeout": "느리게"}, "숫자가 아닙니다"),
        ({"click": "#a", "이상한키": 1}, "알 수 없는 항목"),
    ],
)
def test_잘못된_단계는_이유를_알려_준다(raw, 포함_문구):
    with pytest.raises(ScenarioError) as error:
        Step.parse(raw, "reserve.steps[0]")

    assert 포함_문구 in str(error.value)
    assert "reserve.steps[0]" in str(error.value)


@pytest.mark.parametrize(
    "바꿀_내용, 포함_문구",
    [
        ({"targets": []}, "하나 이상"),
        ({"name": ""}, "name"),
        ({"reserve": {"steps": []}}, "url 또는 steps"),
        ({"attempts": 0}, "1 이상"),
        ({"interval_sec": -1}, "0 이상"),
        ({"reserve": {"steps": [{"click": "#a"}], "success_when": {"있음": "x"}}}, "알 수 없는 항목"),
        ({"targets": [{}]}, "비어 있지 않은"),
        ({"이상한키": 1}, "알 수 없는 항목"),
    ],
)
def test_잘못된_시나리오는_이유를_알려_준다(바꿀_내용, 포함_문구):
    data = {**MINIMAL, **바꿀_내용}

    with pytest.raises(ScenarioError) as error:
        parse_scenario(data)

    assert 포함_문구 in str(error.value)


def test_없는_파일은_경로를_알려_준다(tmp_path):
    with pytest.raises(ScenarioError, match="시나리오 파일이 없습니다"):
        load_scenario(tmp_path / "없음.yaml")


def test_자리표시자를_채운다():
    context = {"env": {"BOOKING_USER": "hong"}, "target": {"date": "2026-10-01"}, "today": "2026-09-18"}

    assert render("{{ env.BOOKING_USER }}", context) == "hong"
    assert render("/book?d={{ target.date }}&u={{ env.BOOKING_USER }}", context) == "/book?d=2026-10-01&u=hong"
    assert render("고정 문자열", context) == "고정 문자열"


def test_환경변수가_비면_무엇을_채워야_하는지_알려_준다():
    with pytest.raises(TemplateError) as error:
        render("{{ env.BOOKING_PASSWORD }}", {"env": {}})

    assert "BOOKING_PASSWORD" in str(error.value)


def test_없는_자리표시자는_오류다():
    with pytest.raises(TemplateError, match="target.room"):
        render("{{ target.room }}", {"target": {"date": "2026-10-01"}})


def test_시나리오는_허용된_접두사_환경변수만_읽는다(monkeypatch):
    monkeypatch.setenv("BOOKING_USER", "hong")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "비밀")

    assert scenario_env(["BOOKING_USER"]) == {"BOOKING_USER": "hong"}

    with pytest.raises(ValueError, match="허용되지 않은 이름"):
        scenario_env(["AWS_SECRET_ACCESS_KEY"])


def test_필요한_환경변수가_비면_이름을_알려_준다(monkeypatch):
    monkeypatch.delenv("BOOKING_PASSWORD", raising=False)

    with pytest.raises(ValueError, match="BOOKING_PASSWORD"):
        scenario_env(["BOOKING_PASSWORD"])


def test_저장소에_들어_있는_시나리오는_모두_읽힌다():
    폴더 = Path(__file__).resolve().parents[1] / "scenarios"
    파일들 = sorted(폴더.glob("*.yaml"))

    assert 파일들, "scenarios/ 에 예시가 하나는 있어야 합니다."
    for path in 파일들:
        load_scenario(path)


def test_아직_채우지_않은_단계는_실패할_때_그렇게_알려_준다():
    scenario = load_scenario(
        Path(__file__).resolve().parents[1] / "scenarios" / "dobong-tennis.yaml"
    )

    설명들 = [step.describe() for step in scenario.login.steps]

    assert all("셀렉터를 아직 채우지 않았습니다" in 설명 for 설명 in 설명들)
