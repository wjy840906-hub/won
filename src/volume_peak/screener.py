"""'기준일 거래량이 최근 N년 최고치인가' 를 판정한다(네트워크 없음)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .krx_client import DailyBar, Quote, is_common_stock


@dataclass
class Breakout:
    """신고 거래량 종목 한 건."""

    code: str
    name: str
    market: str
    as_of: str
    volume: int                 # 기준일 거래량
    prev_peak: int              # 기준일을 뺀 기간 내 최고 거래량
    prev_peak_date: str         # 그 최고 거래량을 기록한 날
    close: int = 0
    change_rate: float = 0.0
    value: int = 0              # 기준일 거래대금
    history_from: str = ""      # 확보한 이력의 첫 거래일
    history_days: int = 0       # 확보한 거래일 수
    note: str = ""

    @property
    def ratio(self) -> float:
        """직전 최고 거래량 대비 배수(직전 기록이 없으면 0)."""
        return round(self.volume / self.prev_peak, 2) if self.prev_peak else 0.0


@dataclass
class ScreenSummary:
    """선별 과정 요약(메일 본문·로그용)."""

    as_of: str = ""
    listed: int = 0            # 기준일 전종목 수
    candidates: int = 0        # 거래량/거래대금 조건을 통과해 이력을 조회한 수
    checked: int = 0           # 이력 조회에 성공한 수
    breakouts: int = 0         # 신고 거래량 종목 수
    short_history: int = 0     # 이력이 짧아 제외(또는 표시)한 수
    failed: list[str] = field(default_factory=list)  # 이력 조회 실패 종목


def filter_candidates(
    quotes: list[Quote],
    min_volume: int = 0,
    min_value: int = 0,
    include_preferred: bool = False,
) -> list[Quote]:
    """거래량·거래대금 하한과 보통주 여부로 조회 대상을 줄인다.

    하한을 두는 이유는 조회 건수를 줄이기 위해서다. 거래가 거의 없는 종목은
    몇 천 주만으로도 '10년 최고'가 되어 목록만 흐려진다.
    """
    kept: list[Quote] = []
    for quote in quotes:
        if quote.volume < min_volume or quote.value < min_value:
            continue
        if not include_preferred and not is_common_stock(quote.code):
            continue
        kept.append(quote)
    return kept


def window_bars(bars: list[DailyBar], start: str, end: str) -> list[DailyBar]:
    """[start, end] 안의 거래일만 날짜순으로 남긴다."""
    return sorted(
        (bar for bar in bars if start <= bar.date <= end), key=lambda bar: bar.date
    )


def evaluate(
    quote: Quote,
    bars: list[DailyBar],
    as_of: str,
    start: str,
    min_history_days: int = 0,
    include_short_history: bool = False,
) -> Breakout | None:
    """한 종목이 기준일에 기간 내 최고 거래량을 새로 썼으면 Breakout 을 돌려준다.

    - 기준일 거래량은 이력에 그 날이 있으면 이력 값을, 없으면 스냅샷 값을 쓴다.
    - 직전 최고치와 '같기만' 한 경우(타이)는 새로 쓴 것이 아니므로 제외한다.
    - 이력이 짧은 신규 상장 종목은 min_history_days 로 걸러낸다
      (include_short_history 면 비고에 남기고 통과시킨다).
    """
    inside = window_bars(bars, start, as_of)
    if not inside:
        return None

    today = next((bar for bar in inside if bar.date == as_of), None)
    volume = today.volume if today is not None else quote.volume
    if volume <= 0:
        return None

    prior = [bar for bar in inside if bar.date != as_of]
    if not prior:
        return None

    prev_peak = max(bar.volume for bar in prior)
    if volume <= prev_peak:
        return None

    # 같은 최고치가 여러 번이면 가장 최근 날짜를 '직전 기록일'로 본다.
    prev_peak_date = max(bar.date for bar in prior if bar.volume == prev_peak)

    note = ""
    history_days = len(inside)
    if min_history_days and history_days < min_history_days:
        if not include_short_history:
            return None
        note = f"이력 {history_days}거래일(기간 전체 아님)"

    return Breakout(
        code=quote.code,
        name=quote.name,
        market=quote.market,
        as_of=as_of,
        volume=volume,
        prev_peak=prev_peak,
        prev_peak_date=prev_peak_date,
        close=quote.close or (today.close if today else 0),
        change_rate=quote.change_rate,
        value=quote.value or (today.value if today else 0),
        history_from=inside[0].date,
        history_days=history_days,
        note=note,
    )


def sort_key(sort: str):
    """정렬 기준 이름 → 정렬 키(모두 내림차순)."""
    if sort == "ratio":
        return lambda item: (item.ratio, item.value)
    if sort == "volume":
        return lambda item: (item.volume, item.value)
    return lambda item: (item.value, item.volume)


def screen(
    quotes: list[Quote],
    histories: dict[str, list[DailyBar]],
    as_of: str,
    start: str,
    min_history_days: int = 0,
    include_short_history: bool = False,
    sort: str = "value",
    top: int = 0,
) -> list[Breakout]:
    """후보 전체를 판정해 정렬된 신고 거래량 목록을 만든다."""
    found: list[Breakout] = []
    for quote in quotes:
        bars = histories.get(quote.code)
        if not bars:
            continue
        hit = evaluate(
            quote,
            bars,
            as_of=as_of,
            start=start,
            min_history_days=min_history_days,
            include_short_history=include_short_history,
        )
        if hit is not None:
            found.append(hit)

    found.sort(key=sort_key(sort), reverse=True)
    return found[:top] if top else found


def to_rows(breakouts: list[Breakout]) -> list[dict[str, str]]:
    """엑셀 작성용 문자열 행으로 바꾼다."""
    rows: list[dict[str, str]] = []
    for index, item in enumerate(breakouts, start=1):
        rows.append(
            {
                "no": str(index),
                "market": item.market,
                "code": item.code,
                "name": item.name,
                "volume": f"{item.volume:,}",
                "prev_peak": f"{item.prev_peak:,}",
                "prev_peak_date": item.prev_peak_date,
                "ratio": f"{item.ratio:,.2f}배",
                "close": f"{item.close:,}",
                "change_rate": f"{item.change_rate:+.2f}%",
                "value": f"{item.value:,}",
                "history_from": item.history_from,
                "note": item.note,
            }
        )
    return rows
