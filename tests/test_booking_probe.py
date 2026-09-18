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


# -- 느리거나 닿지 않는 사이트 -------------------------------------------------


def test_끝까지_못_불러와도_그려진_만큼_진단한다(진단페이지):
    from fake_page import FakeTimeout

    from booking_macro.probe import probe_url

    page, config = 진단페이지
    page.fail_on = {"https://느린.example.or.kr": "Timeout 20000ms exceeded"}
    page.text = "로그인" * 60  # 화면은 그려졌다

    보고서 = probe_url(page, "https://느린.example.or.kr", config)

    assert "주의" in 보고서
    assert "끝까지 불러오지는 못했습니다" in 보고서
    assert "BOOKING_PROBE_TIMEOUT_MS" in 보고서
    assert "#mbrId" in 보고서  # 그래도 진단 결과는 나온다


def test_아무것도_못_열면_해외_IP_차단을_먼저_짚어_준다(진단페이지):
    from booking_macro.probe import ProbeError, probe_url

    page, config = 진단페이지
    page.fail_on = {"https://막힌.example.or.kr": "Timeout 20000ms exceeded"}
    page.text = ""  # 아무것도 그려지지 않았다

    with pytest.raises(ProbeError) as error:
        probe_url(page, "https://막힌.example.or.kr", config)

    안내 = str(error.value)
    assert "해외 IP" in 안내
    assert "GitHub Actions 러너는 해외에 있으므로" in 안내
    assert "BOOKING_PROBE_TIMEOUT_MS" in 안내
    assert "BOOKING_WAIT_UNTIL=commit" in 안내


def test_진단은_넉넉한_시간과_domcontentloaded_로_연다(진단페이지):
    from booking_macro.probe import probe_url

    page, config = 진단페이지
    열린_것 = {}
    원래 = page.goto

    def 기록(url, **kwargs):
        열린_것.update(kwargs)
        원래(url, **kwargs)

    page.goto = 기록

    probe_url(page, "https://example.or.kr", config)

    assert 열린_것["timeout"] == 60000
    assert 열린_것["wait_until"] == "domcontentloaded"


def test_화면을_찍기_전에_남은_요청을_끊는다(진단페이지):
    from booking_macro.probe import _save_screenshot

    page, config = 진단페이지
    page.evaluate_result = None

    assert _save_screenshot(page, Path(config.out_dir) / "x.png", config) is True
    끊었나 = [call for call in page.evaluate_args if call is None]
    assert page.actions[0] == ("evaluate", "", "")  # window.stop() 먼저
    assert page.screenshots and page.screenshots[0].exists()


def test_전체화면이_안_되면_보이는_부분만이라도_남긴다(진단페이지, monkeypatch):
    from booking_macro.probe import _save_screenshot

    page, config = 진단페이지
    시도 = []

    def 전체화면만_실패(path, full_page=False, **kwargs):
        시도.append(full_page)
        if full_page:
            raise RuntimeError("Timeout")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"png")

    page.screenshot = 전체화면만_실패

    assert _save_screenshot(page, Path(config.out_dir) / "x.png", config) is True
    assert 시도 == [True, False]


def test_화면을_끝내_못_찍어도_진단은_끝난다(진단페이지):
    from booking_macro.probe import probe_url

    page, config = 진단페이지

    def 항상_실패(*args, **kwargs):
        raise RuntimeError("Timeout")

    page.screenshot = 항상_실패

    보고서 = probe_url(page, "https://example.or.kr", config)

    assert "#mbrId" in 보고서
    assert "화면 저장" not in 보고서
    assert "HTML 저장" in 보고서


# -- 표 구조 · 브라우저 콘솔 스니펫 ---------------------------------------------


표화면 = {
    "title": "다락원체육공원",
    "url": "https://example.or.kr/rent",
    "inputs": [],
    "selects": [],
    "buttons": [],
    "forms": [],
    "iframes": [],
    "textSample": "",
    "tables": [
        {
            "id": "rsvTable",
            "cls": "",
            "rowCount": 18,
            "pressable": 3,
            "header": [
                [{"text": "실내코트1", "span": 2}, {"text": "실외코트5", "span": 2}],
                [{"text": "선택", "span": 1}, {"text": "시간", "span": 1}],
            ],
            "rowSamples": [["×", "09:00~10:00"], ["×", "10:00~11:00"]],
        }
    ],
}


def test_표의_열과_행_이름을_보여_준다():
    보고서 = format_report(표화면)

    assert "표 1개" in 보고서
    assert "rsvTable" in 보고서
    assert "실내코트1×2" in 보고서          # 두 줄 헤더의 colspan 이 드러난다
    assert "09:00~10:00" in 보고서
    assert "click_cell 의 column" in 보고서


def test_한_줄짜리_표는_보고서에_넣지_않는다():
    화면 = {**표화면, "tables": [{**표화면["tables"][0], "rowCount": 1}]}

    assert "click_cell 에 쓸 이름" not in format_report(화면)


def test_콘솔_스니펫이_추출기와_어긋나지_않았다():
    # 스니펫은 probe.EXTRACT_JS 를 그대로 끼워 만든다. 한쪽만 고치면 여기서 잡힌다.
    import subprocess
    import sys

    뿌리 = Path(__file__).resolve().parents[1]
    결과 = subprocess.run(
        [sys.executable, "tools/build_snippet.py", "--check"],
        cwd=뿌리, capture_output=True, text=True,
    )

    assert 결과.returncode == 0, 결과.stderr


def test_콘솔_스니펫은_붙여_넣으면_바로_도는_모양이다():
    스니펫 = (Path(__file__).resolve().parents[1] / "tools" / "probe-snippet.js").read_text(
        encoding="utf-8"
    )

    assert 스니펫.lstrip().startswith("//")       # 쓰는 법이 맨 위에 있다
    assert "(() => {" in 스니펫                   # 즉시 실행식 — 붙여 넣으면 바로 돈다
    assert "copy(글)" in 스니펫                   # 클립보드로 복사
    assert "querySelectorAll" in 스니펫           # 추출기가 실제로 들어 있다
    # 입력칸의 값은 아예 읽지 않는다 — 비밀번호가 결과에 섞일 수 없다.
    assert ".value" not in 스니펫
