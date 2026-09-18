"""전체 흐름(스냅샷 → 이력 → 선별 → 엑셀 → 메일) 테스트."""

from __future__ import annotations

from dataclasses import replace

import pytest
from openpyxl import load_workbook

from kind_managed.config import MailConfig
from volume_peak import pipeline
from volume_peak.config import ScreenConfig
from volume_peak.krx_client import DailyBar, KrxError, Quote
from volume_peak.pipeline import build_mail_bodies, fetch_histories, run

AS_OF = "2026-09-17"


def quote(code, name, volume, value=10**11, market="KOSPI") -> Quote:
    return Quote(
        code=code,
        name=name,
        market=market,
        close=10_000,
        change_rate=12.5,
        volume=volume,
        value=value,
    )


def series(pairs) -> list[DailyBar]:
    return [DailyBar(date=day, volume=vol, close=10_000, value=vol * 10_000) for day, vol in pairs]


SNAPSHOT = [
    quote("000100", "신고거래량", 5_000_000),
    quote("000200", "평범한종목", 1_000_000),
    quote("000300", "거래없는종목", 10, value=1_000),      # 하한 미달
    quote("000105", "신고거래량우", 5_000_000),            # 우선주
]

HISTORIES = {
    "000100": series(
        [("2017-03-02", 900_000), ("2020-03-19", 2_000_000), (AS_OF, 5_000_000)]
    ),
    "000200": series([("2020-03-19", 9_000_000), (AS_OF, 1_000_000)]),
    "000105": series([("2020-03-19", 100_000), (AS_OF, 5_000_000)]),
}


class FakeClient:
    """네트워크 대신 미리 정한 값을 돌려주는 KRX 클라이언트."""

    def __init__(self, snapshot=None, histories=None, fail: set[str] | None = None):
        self.snapshot = list(SNAPSHOT if snapshot is None else snapshot)
        self.histories = dict(HISTORIES if histories is None else histories)
        self.fail = fail or set()
        self.daily_calls: list[tuple[str, str, str]] = []

    def latest_trading_day(self, on="", market="ALL"):
        return AS_OF, self.snapshot

    def fetch_isin_map(self, market="ALL"):
        return {q.code: f"KR7{q.code}000" for q in self.snapshot}

    def fetch_daily_bars(self, isin, start, end):
        code = isin[3:9]
        self.daily_calls.append((code, start, end))
        if code in self.fail:
            raise KrxError("조회 실패")
        return [bar for bar in self.histories.get(code, []) if start <= bar.date <= end]


def make_config(tmp_path, **kwargs) -> ScreenConfig:
    base = ScreenConfig(
        trade_date=AS_OF,
        years=10,
        min_volume=100_000,
        min_value=10**9,
        min_history_days=0,
        workers=2,
        out_dir=str(tmp_path / "out"),
        cache_dir=str(tmp_path / "cache"),
    )
    return replace(base, **kwargs) if kwargs else base


def run_with(client, config, **kwargs):
    return run(config, client=client, client_factory=lambda: client, **kwargs)


def test_신고_거래량_종목만_고른다(tmp_path):
    client = FakeClient()
    result = run_with(client, make_config(tmp_path))

    assert [item.code for item in result.breakouts] == ["000100"]
    hit = result.breakouts[0]
    assert hit.prev_peak == 2_000_000
    assert hit.prev_peak_date == "2020-03-19"
    assert hit.ratio == pytest.approx(2.5)
    # 우선주와 거래 미달 종목은 이력 조회 자체를 하지 않는다.
    assert sorted(code for code, _, _ in client.daily_calls) == ["000100", "000200"]


def test_우선주_포함_옵션(tmp_path):
    client = FakeClient()
    result = run_with(client, make_config(tmp_path, include_preferred=True))

    assert sorted(item.code for item in result.breakouts) == ["000100", "000105"]


def test_요약과_엑셀_생성(tmp_path):
    client = FakeClient()
    result = run_with(client, make_config(tmp_path))

    assert result.summary.listed == 4
    assert result.summary.candidates == 2
    assert result.summary.breakouts == 1
    assert result.start == "2016-09-18"

    assert result.excel_path is not None and result.excel_path.exists()
    sheet = load_workbook(result.excel_path).active
    assert [cell.value for cell in sheet[4]][:5] == [
        "번호",
        "시장",
        "종목코드",
        "종목명",
        "기준일 거래량",
    ]
    row = [cell.value for cell in sheet[5]]
    assert row[2] == "000100"          # 종목코드는 문자열(앞자리 0 보존)
    assert row[4] == 5_000_000          # 거래량은 숫자로 들어간다
    assert sheet["C5"].number_format == "@"


def test_이력_조회_실패는_전체를_막지_않는다(tmp_path):
    client = FakeClient(fail={"000200"})
    result = run_with(client, make_config(tmp_path))

    assert [item.code for item in result.breakouts] == ["000100"]
    assert len(result.summary.failed) == 1
    assert "평범한종목" in result.summary.failed[0]


def test_캐시가_있으면_모자란_구간만_받는다(tmp_path):
    config = make_config(tmp_path)
    first = FakeClient()
    run_with(first, config)
    assert first.daily_calls[0][1] == "2016-09-18"

    # 같은 기준일로 다시 돌리면 조회하지 않는다.
    second = FakeClient()
    run_with(second, config)
    assert second.daily_calls == []

    # 기준일이 하루 늘면 마지막 저장일부터만 이어 받는다.
    next_day = "2026-09-18"
    histories = {
        code: bars + series([(next_day, 1_000)]) for code, bars in HISTORIES.items()
    }
    third = FakeClient(histories=histories)
    third.latest_trading_day = lambda on="", market="ALL": (next_day, third.snapshot)  # type: ignore[assignment]
    run(replace(config, trade_date=next_day), client=third, client_factory=lambda: third)

    assert third.daily_calls
    assert all(start == AS_OF for _code, start, _end in third.daily_calls)


def test_캐시를_끄면_매번_전_구간을_받는다(tmp_path):
    config = make_config(tmp_path)
    client = FakeClient()
    run_with(client, config, use_cache=False)
    run_with(client, config, use_cache=False)

    assert len(client.daily_calls) == 4
    assert not (tmp_path / "cache").exists()


def test_이력이_짧은_신규상장은_기본으로_빠진다(tmp_path):
    histories = {"000100": series([("2026-09-01", 100_000), (AS_OF, 5_000_000)])}
    client = FakeClient(snapshot=[SNAPSHOT[0]], histories=histories)

    config = make_config(tmp_path, min_history_days=250)
    assert run_with(client, config).breakouts == []

    result = run_with(
        client,
        replace(config, min_history_days=250, include_short_history=True, cache_dir=str(tmp_path / "c2")),
    )
    assert len(result.breakouts) == 1
    assert "이력 2거래일" in result.breakouts[0].note


def test_표준코드가_없으면_실패로_기록된다(tmp_path):
    client = FakeClient()
    client.fetch_isin_map = lambda market="ALL": {}  # type: ignore[assignment]
    result = run_with(client, make_config(tmp_path))

    assert result.breakouts == []
    assert len(result.summary.failed) == 2
    assert "표준코드" in result.summary.failed[0]


def test_상위_N_과_정렬(tmp_path):
    histories = {
        "000100": series([("2020-03-19", 2_000_000), (AS_OF, 5_000_000)]),   # 2.5배
        "000200": series([("2020-03-19", 100_000), (AS_OF, 1_000_000)]),     # 10배
    }
    snapshot = [SNAPSHOT[0], SNAPSHOT[1]]
    client = FakeClient(snapshot=snapshot, histories=histories)

    by_ratio = run_with(client, make_config(tmp_path, sort="ratio", top=1))
    assert [item.code for item in by_ratio.breakouts] == ["000200"]

    by_value = run_with(client, make_config(tmp_path, sort="value", top=1))
    assert [item.code for item in by_value.breakouts] == ["000100"]


def test_잘못된_설정은_거부한다(tmp_path):
    with pytest.raises(ValueError):
        run_with(FakeClient(), make_config(tmp_path, years=0))
    with pytest.raises(ValueError):
        run_with(FakeClient(), make_config(tmp_path, sort="거래량"))


def test_메일_본문(tmp_path):
    client = FakeClient()
    config = make_config(tmp_path)
    result = run_with(client, config)
    text, html_body = build_mail_bodies(result, config, "신고거래량_20260917.xlsx")

    assert "최근 10년" in text
    assert "신고거래량(000100)" in text
    assert "5,000,000주" in text
    assert "2.50배" in text
    assert "신고거래량_20260917.xlsx" in text
    assert "<table" in html_body and "000100" in html_body


def test_해당_종목이_없으면_빈_목록으로_안내한다(tmp_path):
    client = FakeClient(snapshot=[SNAPSHOT[1]])
    config = make_config(tmp_path)
    result = run_with(client, config)
    text, html_body = build_mail_bodies(result, config, "x.xlsx")

    assert result.breakouts == []
    assert "[해당 종목 없음]" in text
    assert "조건을 만족하는 종목이 없습니다" in html_body


def test_메일_발송(tmp_path, monkeypatch):
    sent: list = []
    monkeypatch.setattr(pipeline, "send_message", lambda config, message: sent.append(message))

    mail_config = MailConfig(host="smtp.example.com", sender="a@example.com", to=["b@example.com"])
    result = run(
        make_config(tmp_path),
        mail_config,
        send_mail=True,
        client=FakeClient(),
        client_factory=FakeClient,
    )

    assert result.mail_sent is True
    assert len(sent) == 1
    message = sent[0]
    assert "[신고거래량] 2026-09-17 기준 최근 10년 최고 거래량 1종목" == message["Subject"]
    assert any(part.get_filename() == "신고거래량_20260917.xlsx" for part in message.iter_attachments())


def test_메일_설정_없이_발송하면_오류(tmp_path):
    with pytest.raises(ValueError):
        run(make_config(tmp_path), None, send_mail=True, client=FakeClient(), client_factory=FakeClient)


def test_이력_조회는_캐시_없이도_동작한다(tmp_path):
    client = FakeClient()
    histories, failures = fetch_histories(
        [SNAPSHOT[0]],
        {"000100": "KR7000100000"},
        start="2016-09-18",
        end=AS_OF,
        client_factory=lambda: client,
        cache=None,
        workers=1,
    )
    assert failures == []
    assert len(histories["000100"]) == 3
