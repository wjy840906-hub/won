"""KRX 정보데이터시스템(data.krx.co.kr) 시세 조회.

화면(bld) 세 개만 사용한다.

- 전종목 시세          MDCSTAT01501 : 기준일 하루치 전 종목 거래량/거래대금
- 개별종목 시세 추이    MDCSTAT01701 : 한 종목의 기간별 일별 시세(거래량 포함)
- 종목 검색            finder_stkisu : 단축코드(6자리) ↔ 표준코드(KR7…) 매핑

응답 껍데기 이름(OutBlock_1 / output / block1)은 화면마다 다르고 바뀌기도 해서,
JSON 안에서 '사전들의 리스트'를 찾아 쓰는 방식으로 읽는다.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
REFERER = "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd"

BLD_SNAPSHOT = "dbms/MDC/STAT/standard/MDCSTAT01501"   # 전종목 시세
BLD_DAILY = "dbms/MDC/STAT/standard/MDCSTAT01701"      # 개별종목 시세 추이
BLD_FINDER = "dbms/comm/finder/finder_stkisu"          # 종목 검색(표준코드)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

_ROW_KEYS = ("OutBlock_1", "output", "block1", "OutBlock_2")
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


class KrxError(RuntimeError):
    """KRX 조회/파싱 실패."""


@dataclass(frozen=True)
class Quote:
    """기준일 하루치 시세 한 종목."""

    code: str
    name: str
    market: str
    close: int = 0
    change_rate: float = 0.0
    volume: int = 0
    value: int = 0
    market_cap: int = 0


@dataclass(frozen=True)
class DailyBar:
    """일별 시세 한 줄."""

    date: str      # YYYY-MM-DD
    volume: int
    close: int = 0
    value: int = 0


def to_int(text: object) -> int:
    """'1,234' · '-' · '' · 1234 → 정수(못 읽으면 0)."""
    if isinstance(text, bool):
        return 0
    if isinstance(text, (int, float)):
        return int(text)
    match = _NUM_RE.search(str(text or "").replace(",", ""))
    return int(float(match.group())) if match else 0


def to_float(text: object) -> float:
    """'-1.23' · '' → 실수(못 읽으면 0.0)."""
    if isinstance(text, bool):
        return 0.0
    if isinstance(text, (int, float)):
        return float(text)
    match = _NUM_RE.search(str(text or "").replace(",", ""))
    return float(match.group()) if match else 0.0


def normalize_date(text: object) -> str:
    """'2026/09/17' · '2026-09-17' · '20260917' → YYYY-MM-DD."""
    digits = re.sub(r"\D", "", str(text or ""))
    if len(digits) != 8:
        return ""
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"


def extract_rows(payload: object) -> list[dict]:
    """KRX 응답에서 데이터 행 목록을 꺼낸다(껍데기 이름이 바뀌어도 견디도록)."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in _ROW_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    for value in payload.values():
        if isinstance(value, list) and value and all(isinstance(row, dict) for row in value):
            return value
    return []


def is_common_stock(code: str) -> bool:
    """보통주로 보이는 단축코드인지(우선주·신주인수권 등은 끝자리가 0 이 아니다)."""
    code = (code or "").strip()
    return len(code) == 6 and code.isdigit() and code.endswith("0")


class KrxClient:
    """data.krx.co.kr JSON 엔드포인트 클라이언트."""

    def __init__(
        self,
        timeout: int = 30,
        session: requests.Session | None = None,
        max_retries: int = 3,
        pause: float = 0.1,
        chunk_days: int = 730,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.pause = pause
        self.chunk_days = max(1, chunk_days)
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Referer": REFERER,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            }
        )

    # ── 저수준 ────────────────────────────────────────────────────────
    def _post(self, params: dict[str, str]) -> list[dict]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.post(BASE_URL, data=params, timeout=self.timeout)
                response.raise_for_status()
                payload = response.json()
            except ValueError as exc:  # JSON 이 아님 = 차단/점검 페이지
                last_error = KrxError(f"KRX 응답을 JSON 으로 읽지 못했습니다: {exc}")
            except requests.RequestException as exc:
                last_error = exc
            else:
                return extract_rows(payload)
            if attempt < self.max_retries:
                time.sleep(self.pause * (2 ** (attempt - 1)))
        raise KrxError(f"KRX 조회 실패({params.get('bld')}): {last_error}") from last_error

    # ── 화면별 조회 ───────────────────────────────────────────────────
    def fetch_snapshot(self, trade_date: str, market: str = "ALL") -> list[Quote]:
        """기준일(YYYY-MM-DD) 전종목 시세. 휴장일이면 빈 목록."""
        rows = self._post(
            {
                "bld": BLD_SNAPSHOT,
                "mktId": market or "ALL",
                "trdDd": trade_date.replace("-", ""),
                "share": "1",
                "money": "1",
                "csvxls_isNo": "false",
            }
        )
        quotes: list[Quote] = []
        for row in rows:
            code = str(row.get("ISU_SRT_CD") or row.get("ISU_CD") or "").strip()
            if not code:
                continue
            quotes.append(
                Quote(
                    code=code.zfill(6),
                    name=str(row.get("ISU_ABBRV") or row.get("ISU_NM") or "").strip(),
                    market=str(row.get("MKT_NM") or "").strip(),
                    close=to_int(row.get("TDD_CLSPRC")),
                    change_rate=to_float(row.get("FLUC_RT")),
                    volume=to_int(row.get("ACC_TRDVOL")),
                    value=to_int(row.get("ACC_TRDVAL")),
                    market_cap=to_int(row.get("MKTCAP")),
                )
            )
        if not quotes:
            log.debug("%s 전종목 시세가 비어 있습니다(휴장일로 봅니다).", trade_date)
        return quotes

    def latest_trading_day(
        self, on: str = "", lookback: int = 14, market: str = "ALL"
    ) -> tuple[str, list[Quote]]:
        """on(빈 값이면 오늘)부터 거꾸로 훑어 거래가 있었던 날과 그 날 시세를 돌려준다."""
        anchor = (
            datetime.strptime(on, "%Y-%m-%d").date()
            if on
            else datetime.now().date()
        )
        for offset in range(lookback + 1):
            day = anchor - timedelta(days=offset)
            if day.weekday() >= 5:  # 주말은 조회하지 않는다
                continue
            quotes = self.fetch_snapshot(day.isoformat(), market=market)
            if quotes:
                return day.isoformat(), quotes
        raise KrxError(
            f"{anchor.isoformat()} 이전 {lookback}일 안에 거래일을 찾지 못했습니다."
        )

    def fetch_isin_map(self, market: str = "ALL") -> dict[str, str]:
        """단축코드(6자리) → 표준코드(KR7…) 매핑."""
        rows = self._post(
            {
                "bld": BLD_FINDER,
                "mktsel": market or "ALL",
                "typeNo": "0",
                "searchText": "",
            }
        )
        mapping: dict[str, str] = {}
        for row in rows:
            short = str(row.get("short_code") or row.get("ISU_SRT_CD") or "").strip()
            full = str(row.get("full_code") or row.get("ISU_CD") or "").strip()
            if short and full:
                mapping[short.zfill(6)] = full
        if not mapping:
            raise KrxError("KRX 종목 검색에서 표준코드를 얻지 못했습니다.")
        return mapping

    def fetch_daily_bars(self, isin: str, start: str, end: str) -> list[DailyBar]:
        """한 종목의 기간별 일별 시세(오래된 날짜 → 최근 날짜 순).

        긴 기간은 chunk_days 단위로 나눠 받는다. 한 번에 10년을 요청하면 화면 쪽에서
        조용히 잘린 결과가 올 수 있고, 그러면 '10년 최고'를 잘못 판정하게 된다.
        """
        merged: dict[str, DailyBar] = {}
        for chunk_start, chunk_end in split_range(start, end, self.chunk_days):
            for bar in self._fetch_daily_chunk(isin, chunk_start, chunk_end):
                merged[bar.date] = bar
        return [merged[day] for day in sorted(merged)]

    def _fetch_daily_chunk(self, isin: str, start: str, end: str) -> list[DailyBar]:
        """개별종목 시세 추이 한 번 조회(한 구간)."""
        rows = self._post(
            {
                "bld": BLD_DAILY,
                "isuCd": isin,
                "isuCd2": isin,
                "strtDd": start.replace("-", ""),
                "endDd": end.replace("-", ""),
                "share": "1",
                "money": "1",
                "adjStkPrc": "2",   # 수정주가 기준(거래량에는 영향이 없다)
                "adjStkPrc_check": "Y",
                "csvxls_isNo": "false",
            }
        )
        bars: list[DailyBar] = []
        for row in rows:
            day = normalize_date(row.get("TRD_DD"))
            if not day:
                continue
            bars.append(
                DailyBar(
                    date=day,
                    volume=to_int(row.get("ACC_TRDVOL")),
                    close=to_int(row.get("TDD_CLSPRC")),
                    value=to_int(row.get("ACC_TRDVAL")),
                )
            )
        bars.sort(key=lambda bar: bar.date)
        return bars


def split_range(start: str, end: str, chunk_days: int) -> list[tuple[str, str]]:
    """[start, end] 를 chunk_days 이하 구간들로 나눈다(경계는 겹치지 않는다)."""
    first = datetime.strptime(start, "%Y-%m-%d").date()
    last = datetime.strptime(end, "%Y-%m-%d").date()
    if last < first:
        return []
    chunks: list[tuple[str, str]] = []
    cursor = first
    step = timedelta(days=max(1, chunk_days) - 1)
    while cursor <= last:
        stop = min(cursor + step, last)
        chunks.append((cursor.isoformat(), stop.isoformat()))
        cursor = stop + timedelta(days=1)
    return chunks


def business_days_between(start: str, end: str) -> int:
    """주말을 뺀 달력 일수(이력 길이 판단용 근사치)."""
    first = datetime.strptime(start, "%Y-%m-%d").date()
    last = datetime.strptime(end, "%Y-%m-%d").date()
    if last < first:
        return 0
    days = 0
    current: date = first
    while current <= last:
        if current.weekday() < 5:
            days += 1
        current += timedelta(days=1)
    return days
