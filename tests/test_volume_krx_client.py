"""KRX 시세 클라이언트 파싱/조회 테스트(네트워크 없음)."""

from __future__ import annotations

import json

import pytest
import requests

from volume_peak.krx_client import (
    BLD_DAILY,
    BLD_FINDER,
    BLD_SNAPSHOT,
    KrxClient,
    KrxError,
    business_days_between,
    extract_rows,
    is_common_stock,
    normalize_date,
    split_range,
    to_float,
    to_int,
)


class FakeResponse:
    def __init__(self, payload, status: int = 200, text: str = ""):
        self._payload = payload
        self.status_code = status
        self.text = text or json.dumps(payload, ensure_ascii=False)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        if self._payload is None:
            raise ValueError("Expecting value")
        return self._payload


class FakeSession:
    """post() 호출을 기록하고 미리 준비한 응답을 돌려주는 세션."""

    def __init__(self, responses):
        self.headers: dict[str, str] = {}
        self.responses = list(responses)
        self.calls: list[dict[str, str]] = []

    def post(self, url, data=None, timeout=None):
        self.calls.append(dict(data or {}))
        item = self.responses.pop(0) if self.responses else FakeResponse({"output": []})
        if isinstance(item, Exception):
            raise item
        return item


def make_client(responses, **kwargs) -> tuple[KrxClient, FakeSession]:
    session = FakeSession(responses)
    return KrxClient(session=session, pause=0, **kwargs), session


def test_숫자_문자열_파싱():
    assert to_int("1,234,567") == 1234567
    assert to_int("-") == 0
    assert to_int("") == 0
    assert to_int(4321) == 4321
    assert to_float("-1.23") == pytest.approx(-1.23)
    assert to_float("") == 0.0


def test_날짜_표기_통일():
    assert normalize_date("2026/09/17") == "2026-09-17"
    assert normalize_date("2026-09-17") == "2026-09-17"
    assert normalize_date("20260917") == "2026-09-17"
    assert normalize_date("-") == ""


def test_응답_껍데기가_바뀌어도_행을_찾는다():
    assert extract_rows({"OutBlock_1": [{"a": 1}]}) == [{"a": 1}]
    assert extract_rows({"output": [{"b": 2}]}) == [{"b": 2}]
    assert extract_rows({"block1": [{"c": 3}]}) == [{"c": 3}]
    # 처음 보는 이름이어도 '사전들의 리스트'면 읽는다.
    assert extract_rows({"NewBlockName": [{"d": 4}]}) == [{"d": 4}]
    assert extract_rows({"CURRENT_DATETIME": "2026-09-18"}) == []


def test_보통주_판별():
    assert is_common_stock("005930")
    assert not is_common_stock("005935")  # 삼성전자우
    assert not is_common_stock("00593")


def test_전종목_시세_파싱():
    payload = {
        "OutBlock_1": [
            {
                "ISU_SRT_CD": "005930",
                "ISU_ABBRV": "삼성전자",
                "MKT_NM": "KOSPI",
                "TDD_CLSPRC": "70,000",
                "FLUC_RT": "5.26",
                "ACC_TRDVOL": "30,123,456",
                "ACC_TRDVAL": "2,108,641,920,000",
                "MKTCAP": "417,000,000,000,000",
            },
            {"ISU_SRT_CD": "", "ISU_ABBRV": "빈 행"},
        ]
    }
    client, session = make_client([FakeResponse(payload)])
    quotes = client.fetch_snapshot("2026-09-17", market="STK")

    assert len(quotes) == 1
    quote = quotes[0]
    assert (quote.code, quote.name, quote.market) == ("005930", "삼성전자", "KOSPI")
    assert quote.volume == 30_123_456
    assert quote.value == 2_108_641_920_000
    assert quote.change_rate == pytest.approx(5.26)
    assert session.calls[0]["bld"] == BLD_SNAPSHOT
    assert session.calls[0]["trdDd"] == "20260917"
    assert session.calls[0]["mktId"] == "STK"


def test_최근_영업일은_휴장일과_주말을_건너뛴다():
    # 2026-09-19(토)/20(일)은 요청 자체를 하지 않고, 18(금)은 휴장(빈 응답) 가정.
    responses = [
        FakeResponse({"OutBlock_1": []}),  # 2026-09-18
        FakeResponse({"OutBlock_1": [{"ISU_SRT_CD": "005930", "ACC_TRDVOL": "100"}]}),  # 09-17
    ]
    client, session = make_client(responses)
    as_of, quotes = client.latest_trading_day(on="2026-09-20")

    assert as_of == "2026-09-17"
    assert len(quotes) == 1
    assert [call["trdDd"] for call in session.calls] == ["20260918", "20260917"]


def test_거래일을_못_찾으면_오류():
    client, _ = make_client([FakeResponse({"OutBlock_1": []}) for _ in range(10)])
    with pytest.raises(KrxError):
        client.latest_trading_day(on="2026-09-18", lookback=3)


def test_표준코드_매핑():
    payload = {
        "block1": [
            {"short_code": "005930", "full_code": "KR7005930003", "codeName": "삼성전자"},
            {"short_code": "035720", "full_code": "KR7035720002", "codeName": "카카오"},
        ]
    }
    client, session = make_client([FakeResponse(payload)])
    mapping = client.fetch_isin_map()

    assert mapping == {"005930": "KR7005930003", "035720": "KR7035720002"}
    assert session.calls[0]["bld"] == BLD_FINDER


def test_표준코드가_비면_오류():
    client, _ = make_client([FakeResponse({"block1": []})])
    with pytest.raises(KrxError):
        client.fetch_isin_map()


def test_긴_기간은_나눠서_요청한다():
    assert split_range("2026-01-01", "2026-01-03", 2) == [
        ("2026-01-01", "2026-01-02"),
        ("2026-01-03", "2026-01-03"),
    ]
    # 10년 · 730일 단위 → 6구간, 구간 경계는 겹치지 않고 전체를 덮는다.
    chunks = split_range("2016-09-18", "2026-09-17", 730)
    assert len(chunks) == 6
    assert chunks[0][0] == "2016-09-18" and chunks[-1][1] == "2026-09-17"
    assert split_range("2026-09-18", "2026-09-17", 730) == []


def test_10년치는_여러_번_나눠_받아_합친다():
    # 한 번에 10년을 요청하면 조용히 잘린 응답이 올 수 있어 구간을 나눈다.
    responses = [
        FakeResponse({"output": [{"TRD_DD": "20170103", "ACC_TRDVOL": "10"}]}),
        FakeResponse({"output": [{"TRD_DD": "20190103", "ACC_TRDVOL": "20"}]}),
        FakeResponse({"output": [{"TRD_DD": "20210104", "ACC_TRDVOL": "30"}]}),
        FakeResponse({"output": [{"TRD_DD": "20230102", "ACC_TRDVOL": "40"}]}),
        FakeResponse({"output": [{"TRD_DD": "20250102", "ACC_TRDVOL": "50"}]}),
        FakeResponse({"output": [{"TRD_DD": "20260917", "ACC_TRDVOL": "60"}]}),
    ]
    client, session = make_client(responses)
    bars = client.fetch_daily_bars("KR7005930003", "2016-09-18", "2026-09-17")

    assert len(session.calls) == 6
    assert session.calls[0]["strtDd"] == "20160918"
    assert session.calls[-1]["endDd"] == "20260917"
    assert [bar.volume for bar in bars] == [10, 20, 30, 40, 50, 60]


def test_일별_시세는_날짜순으로_정렬된다():
    payload = {
        "output": [
            {"TRD_DD": "2026/09/17", "ACC_TRDVOL": "200", "TDD_CLSPRC": "1,100", "ACC_TRDVAL": "220,000"},
            {"TRD_DD": "2026/09/16", "ACC_TRDVOL": "100", "TDD_CLSPRC": "1,000", "ACC_TRDVAL": "100,000"},
            {"TRD_DD": "-", "ACC_TRDVOL": "0"},
        ]
    }
    client, session = make_client([FakeResponse(payload)])
    bars = client.fetch_daily_bars("KR7005930003", "2026-09-01", "2026-09-17")

    assert [bar.date for bar in bars] == ["2026-09-16", "2026-09-17"]
    assert [bar.volume for bar in bars] == [100, 200]
    assert len(session.calls) == 1
    assert session.calls[0]["bld"] == BLD_DAILY
    assert session.calls[0]["strtDd"] == "20260901"
    assert session.calls[0]["endDd"] == "20260917"
    assert session.calls[0]["isuCd"] == "KR7005930003"


def test_일시적_오류는_재시도한다():
    responses = [
        requests.ConnectionError("boom"),
        FakeResponse({"output": [{"TRD_DD": "20260917", "ACC_TRDVOL": "10"}]}),
    ]
    client, session = make_client(responses, max_retries=3)
    bars = client.fetch_daily_bars("KR7005930003", "2026-09-01", "2026-09-17")

    assert len(bars) == 1
    assert len(session.calls) == 2


def test_JSON_이_아니면_KrxError():
    client, _ = make_client([FakeResponse(None, text="<html>점검중</html>")] * 3, max_retries=2)
    with pytest.raises(KrxError):
        client.fetch_snapshot("2026-09-17")


def test_영업일수_근사():
    assert business_days_between("2026-09-14", "2026-09-18") == 5
    assert business_days_between("2026-09-18", "2026-09-14") == 0
