"""화면 구조 진단(--probe)의 셀렉터 추천과 보고서."""

from __future__ import annotations

import pytest

from pathlib import Path

from booking_macro.probe import draft_login_steps, format_report, suggest_selector


def 요소(**바꿀_내용):
    기본 = {"tag": "input", "type": "text", "id": "", "name": "", "cls": "",
            "placeholder": "", "label": "", "text": "", "visible": True}
    return {**기본, **바꿀_내용}


@pytest.mark.parametrize(
    "item, 기대",
    [
        (요소(id="userId", name="uid"), "#userId"),                  # id 를 가장 먼저
        (요소(name="uid"), '[name="uid"]'),                          # id 가 없으면 name
        (요소(tag="button", text="로그인"), "text=로그인"),            # 둘 다 없으면 글자
        (요소(tag="div", cls="btn btn-primary extra"), "div.btn.btn-primary"),
        (요소(tag="span"), "span"),
    ],
)
def test_쓸_만한_셀렉터를_추천한다(item, 기대):
    assert suggest_selector(item) == 기대


def test_숫자로_시작하는_id_는_피한다():
    # CSS 에서 #2col 은 그대로 쓸 수 없다.
    assert suggest_selector(요소(id="2col", name="uid")) == '[name="uid"]'


def test_버튼은_글자를_먼저_쓸_수도_있다():
    item = 요소(tag="button", id="btn_1", text="예약하기")

    assert suggest_selector(item) == "#btn_1"
    assert suggest_selector(item, prefer_text=True) == "text=예약하기"


def test_긴_글자는_셀렉터로_쓰지_않는다():
    item = 요소(tag="a", text="회원 약관에 동의하고 계속 진행하시겠습니까")

    assert suggest_selector(item, prefer_text=True) == "a"


로그인화면 = {
    "title": "로그인",
    "url": "https://example.com/member/login.do",
    "inputs": [
        요소(id="mbrId", placeholder="아이디"),
        요소(id="mbrPw", type="password", placeholder="비밀번호"),
    ],
    "selects": [],
    "buttons": [요소(tag="button", type="submit", id="btnLogin", text="로그인")],
    "forms": [{"id": "loginForm", "method": "post", "action": "/login.do", "fields": ["mbrId", "mbrPw"]}],
    "iframes": [],
    "textSample": "로그인",
}


def test_로그인_단계_초안을_만들어_준다():
    초안 = "\n".join(draft_login_steps(로그인화면))

    assert 'fill: "#mbrId"' in 초안
    assert "{{ env.BOOKING_USER }}" in 초안
    assert 'fill: "#mbrPw"' in 초안
    assert "{{ env.BOOKING_PASSWORD }}" in 초안
    assert 'click: "#btnLogin"' in 초안
    assert "url: /member/login.do" in 초안


def test_초안은_그대로_시나리오에_쓸_수_있는_YAML_이다():
    import yaml

    from booking_macro.scenario import Phase

    초안 = yaml.safe_load("\n".join(draft_login_steps(로그인화면)))
    phase = Phase.parse(초안["login"], "login")

    assert [step.action for step in phase.steps] == ["fill", "fill", "click"]
    assert phase.steps[0].value == "{{ env.BOOKING_USER }}"


def test_비밀번호_칸이_없으면_초안을_만들지_않는다():
    화면 = {**로그인화면, "inputs": [요소(id="search", placeholder="검색")]}

    assert draft_login_steps(화면) == []


def test_아이디_칸은_비밀번호_바로_앞에서_찾는다():
    화면 = {
        **로그인화면,
        "inputs": [
            요소(id="searchWord", placeholder="검색어"),
            요소(id="loginId", placeholder="아이디"),
            요소(id="loginPw", type="password"),
        ],
    }

    초안 = "\n".join(draft_login_steps(화면))

    assert 'fill: "#loginId"' in 초안
    assert "searchWord" not in 초안


def test_보고서에_입력칸과_버튼이_담긴다():
    보고서 = format_report(로그인화면)

    assert "제목: 로그인" in 보고서
    assert "#mbrId" in 보고서
    assert "아이디" in 보고서
    assert "'로그인'" in 보고서
    assert "loginForm" in 보고서
    assert "POST /login.do" in 보고서


def test_선택_상자의_보기를_보여_준다():
    화면 = {
        **로그인화면,
        "selects": [요소(tag="select", id="timeSlot", options=["09:00", "10:00", "11:00"], optionCount=3)],
    }

    보고서 = format_report(화면)

    assert "#timeSlot" in 보고서
    assert "09:00 / 10:00 / 11:00" in 보고서


def test_iframe_이_있으면_눈에_띄게_알려_준다():
    화면 = {**로그인화면, "iframes": [{"id": "rsvFrame", "name": "", "src": "/rsv/main.do"}]}

    보고서 = format_report(화면)

    assert "iframe 1개" in 보고서
    assert "/rsv/main.do" in 보고서
    assert "iframe 안의 요소는" in 보고서


def test_입력칸이_하나도_없으면_이유를_짚어_준다():
    보고서 = format_report({**로그인화면, "inputs": [], "buttons": [], "forms": []})

    assert "iframe 안에 있을 수 있습니다" in 보고서


def test_숨겨진_입력칸은_보고서에_넣지_않는다():
    화면 = {**로그인화면, "inputs": [*로그인화면["inputs"], 요소(id="csrf", visible=False)]}

    보고서 = format_report(화면)

    assert "입력칸 2개" in 보고서
    assert "#csrf" not in 보고서


# -- 예약 화면까지 눌러 들어가기(--probe-click) --------------------------------


@pytest.fixture
def 진단페이지(tmp_path):
    from fake_page import FakePage

    from booking_macro.config import BookingConfig

    page = FakePage()
    page.evaluate_result = 로그인화면
    return page, BookingConfig(out_dir=str(tmp_path / "probe"))


def test_클릭_없이_열린_화면을_뜯어본다(진단페이지):
    from booking_macro.probe import probe_url

    page, config = 진단페이지

    보고서 = probe_url(page, "https://yeyak.example.or.kr", config)

    assert page.clicked == []
    assert "#mbrId" in 보고서
    assert "따라간 경로" not in 보고서


def test_적어_준_순서대로_눌러_들어간다(진단페이지):
    from booking_macro.probe import probe_url

    page, config = 진단페이지
    page.on_click = {
        "text=체육시설": lambda p: setattr(p, "url", "/sports"),
        "text=테니스장": lambda p: setattr(p, "url", "/sports/tennis"),
    }

    보고서 = probe_url(
        page, "https://yeyak.example.or.kr", config, ("text=체육시설", "text=테니스장")
    )

    assert page.clicked == ["text=체육시설", "text=테니스장"]
    assert "따라간 경로" in 보고서
    assert "1. text=체육시설 → /sports" in 보고서
    assert "2. text=테니스장 → /sports/tennis" in 보고서


def test_중간에_못_누르면_거기까지_보여_주고_계속_진단한다(진단페이지):
    from booking_macro.probe import probe_url

    page, config = 진단페이지
    page.fail_on = {"text=없는메뉴": "그런 메뉴 없음"}

    보고서 = probe_url(
        page, "https://yeyak.example.or.kr", config, ("text=없는메뉴", "text=테니스장")
    )

    assert "text=없는메뉴 → 누르지 못함" in 보고서
    assert "text=테니스장" not in 보고서  # 끊긴 뒤로는 시도하지 않는다
    assert "#mbrId" in 보고서            # 그래도 현재 화면은 뜯어본다


def test_진단_결과를_파일로_남긴다(진단페이지):
    from booking_macro.probe import probe_url

    page, config = 진단페이지

    보고서 = probe_url(page, "https://yeyak.example.or.kr", config, ("text=체육시설",))

    저장된 = sorted(path.name for path in Path(config.out_dir).iterdir())
    assert 저장된 == ["probe-yeyak_example_or_kr-1단계.html", "probe-yeyak_example_or_kr-1단계.png"]
    assert "HTML 저장" in 보고서
