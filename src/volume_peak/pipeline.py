"""전종목 시세 → 10년 이력 조회 → 신고 거래량 선별 → 엑셀 → 메일."""

from __future__ import annotations

import html
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from kind_managed.config import MailConfig
from kind_managed.mailer import build_message, send_message

from .cache import CachedHistory, HistoryCache, merge_bars, plan_fetch
from .config import ScreenConfig, years_before
from .excel_writer import write_excel
from .krx_client import DailyBar, KrxClient, KrxError, Quote
from .screener import Breakout, ScreenSummary, filter_candidates, screen

log = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """실행 결과."""

    as_of: str
    start: str
    breakouts: list[Breakout] = field(default_factory=list)
    summary: ScreenSummary = field(default_factory=ScreenSummary)
    excel_path: Path | None = None
    mail_sent: bool = False

    @property
    def total(self) -> int:
        return len(self.breakouts)


def fetch_histories(
    quotes: list[Quote],
    isin_map: dict[str, str],
    start: str,
    end: str,
    client_factory: Callable[[], KrxClient],
    cache: HistoryCache | None = None,
    workers: int = 8,
) -> tuple[dict[str, list[DailyBar]], list[str]]:
    """후보 종목의 일별 시세를 모은다(캐시가 있으면 모자란 구간만 이어 받는다).

    Returns: (종목코드 → 일별 시세, 실패한 종목 설명)
    """
    local = threading.local()
    histories: dict[str, list[DailyBar]] = {}
    failures: list[str] = []
    lock = threading.Lock()
    done = 0

    def client() -> KrxClient:
        if not hasattr(local, "client"):
            local.client = client_factory()
        return local.client

    def work(quote: Quote) -> None:
        nonlocal done
        code = quote.code
        try:
            isin = isin_map.get(code)
            if not isin:
                raise KrxError("표준코드(KR7…)를 찾지 못했습니다")

            cached = cache.load(code) if cache else None
            plan = plan_fetch(cached, start, end)
            if plan is None and cached is not None:
                bars = cached.bars
            else:
                fetch_start, fetch_end = plan  # type: ignore[misc]
                fetched = client().fetch_daily_bars(isin, fetch_start, fetch_end)
                bars = merge_bars(cached.bars if cached else [], fetched)
                if cache is not None:
                    cache.save(
                        code,
                        CachedHistory(
                            bars=bars,
                            start=min(cached.start, start) if cached and cached.start else start,
                            end=max(cached.end, end) if cached and cached.end else end,
                        ),
                    )
            with lock:
                histories[code] = bars
        except (KrxError, OSError) as exc:
            with lock:
                failures.append(f"{quote.name}({code}): {exc}")
        finally:
            with lock:
                done += 1
                if done % 200 == 0:
                    log.info("일별 시세 조회 %d/%d", done, len(quotes))

    if quotes:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            list(pool.map(work, quotes))

    if failures:
        log.warning(
            "일별 시세 조회 실패 %d건: %s",
            len(failures),
            "; ".join(failures[:10]) + (" 외" if len(failures) > 10 else ""),
        )
    return histories, failures


def _summary_lines(result: PipelineResult, config: ScreenConfig) -> list[str]:
    summary = result.summary
    lines = [
        f"기준일: {result.as_of}",
        f"비교 기간: {result.start} ~ {result.as_of} (최근 {config.years}년)",
        f"시장: {config.market_label}",
        (
            f"조회 대상: 전종목 {summary.listed:,}종목 중 "
            f"거래량 {config.min_volume:,}주 · 거래대금 {config.min_value:,}원 이상 "
            f"{summary.candidates:,}종목"
        ),
        f"신고 거래량 종목: {summary.breakouts:,}종목",
    ]
    if summary.failed:
        lines.append(f"이력 조회 실패: {len(summary.failed):,}종목")
    return lines


def build_mail_bodies(
    result: PipelineResult, config: ScreenConfig, filename: str, preview: int = 10
) -> tuple[str, str]:
    """메일 본문(텍스트/HTML)을 만든다."""
    lines = _summary_lines(result, config)
    top = result.breakouts[:preview]

    text_rows = [
        f"  {index}. {item.name}({item.code}) "
        f"{item.volume:,}주 / 직전 최고 {item.prev_peak:,}주({item.prev_peak_date}) "
        f"= {item.ratio:,.2f}배, 종가 {item.close:,}원 {item.change_rate:+.2f}%"
        for index, item in enumerate(top, start=1)
    ]
    text = "\n".join(
        [
            "안녕하세요.",
            "",
            f"{result.as_of} 기준, 최근 {config.years}년 중 최고 거래량을 새로 쓴 종목을 전달드립니다.",
            "",
            *lines,
            "",
            (f"[상위 {len(top)}종목]" if top else "[해당 종목 없음]"),
            *text_rows,
            "",
            f"전체 목록은 첨부파일({filename})을 확인해 주세요.",
            "",
            "※ 출처: 한국거래소 정보데이터시스템(data.krx.co.kr)",
            "※ 거래량은 수정주가와 무관한 원자료이며, 액면분할·병합 종목은 과거 거래량과 단순 비교가 어렵습니다.",
            "",
            "본 메일은 자동 발송되었습니다.",
        ]
    )

    rows_html = "".join(
        "<tr>"
        f"<td>{html.escape(item.name)}</td>"
        f"<td style='text-align:center'>{html.escape(item.code)}</td>"
        f"<td style='text-align:right'>{item.volume:,}</td>"
        f"<td style='text-align:right'>{item.prev_peak:,}</td>"
        f"<td style='text-align:center'>{html.escape(item.prev_peak_date)}</td>"
        f"<td style='text-align:right'>{item.ratio:,.2f}배</td>"
        f"<td style='text-align:right'>{item.change_rate:+.2f}%</td>"
        "</tr>"
        for item in top
    )
    table_html = (
        "<table cellspacing='0' cellpadding='6' "
        "style='border-collapse:collapse;border:1px solid #ddd;font-size:13px'>"
        "<thead><tr style='background:#1F4E79;color:#fff'>"
        "<th>종목명</th><th>종목코드</th><th>기준일 거래량</th><th>직전 최고</th>"
        "<th>직전 기록일</th><th>배수</th><th>등락률</th>"
        "</tr></thead>"
        f"<tbody>{rows_html}</tbody></table>"
        if top
        else "<p style='color:#666'>조건을 만족하는 종목이 없습니다.</p>"
    )

    summary_html = "".join(f"<li>{html.escape(line)}</li>" for line in lines)
    body_html = f"""<html><body style="font-family:'맑은 고딕',Malgun Gothic,sans-serif;font-size:14px;color:#222">
<p>안녕하세요.</p>
<p><b>{html.escape(result.as_of)}</b> 기준, 최근 {config.years}년 중 <b>최고 거래량</b>을 새로 쓴 종목을 전달드립니다.</p>
<ul style="line-height:1.7">{summary_html}</ul>
<h4 style="margin:16px 0 6px">상위 {len(top)}종목</h4>
{table_html}
<p>전체 목록은 첨부파일(<b>{html.escape(filename)}</b>)을 확인해 주세요.</p>
<p style="color:#888;font-size:12px">
※ 출처: 한국거래소 정보데이터시스템(data.krx.co.kr)<br>
※ 거래량은 수정주가와 무관한 원자료이며, 액면분할·병합 종목은 과거 거래량과 단순 비교가 어렵습니다.<br>
본 메일은 자동 발송되었습니다.
</p>
</body></html>"""
    return text, body_html


def run(
    config: ScreenConfig,
    mail_config: MailConfig | None = None,
    send_mail: bool = False,
    client: KrxClient | None = None,
    client_factory: Callable[[], KrxClient] | None = None,
    use_cache: bool = True,
) -> PipelineResult:
    """전체 흐름을 실행한다.

    Args:
        client: 스냅샷·표준코드 조회에 쓸 클라이언트(테스트에서 주입).
        client_factory: 일별 시세를 병렬로 받을 때 스레드마다 만들 클라이언트.
    """
    problems = config.validate()
    if problems:
        raise ValueError(" / ".join(problems))

    if client is None:
        client = KrxClient(timeout=config.request_timeout)
    if client_factory is None:
        factory: Callable[[], KrxClient] = lambda: KrxClient(timeout=config.request_timeout)
    else:
        factory = client_factory

    as_of, quotes = client.latest_trading_day(on=config.trade_date, market=config.market)
    start = years_before(as_of, config.years)
    log.info("기준일 %s / 비교 기간 %s ~ %s / 전종목 %d개", as_of, start, as_of, len(quotes))

    candidates = filter_candidates(
        quotes,
        min_volume=config.min_volume,
        min_value=config.min_value,
        include_preferred=config.include_preferred,
    )
    log.info(
        "1차 후보 %d종목 (거래량 %s주 · 거래대금 %s원 이상%s)",
        len(candidates),
        f"{config.min_volume:,}",
        f"{config.min_value:,}",
        "" if config.include_preferred else ", 보통주만",
    )

    isin_map = client.fetch_isin_map(market=config.market)
    cache = HistoryCache(config.cache_dir) if use_cache else None
    histories, failures = fetch_histories(
        candidates,
        isin_map,
        start=start,
        end=as_of,
        client_factory=factory,
        cache=cache,
        workers=config.workers,
    )

    breakouts = screen(
        candidates,
        histories,
        as_of=as_of,
        start=start,
        min_history_days=config.min_history_days,
        include_short_history=config.include_short_history,
        sort=config.sort,
        top=config.top,
    )
    summary = ScreenSummary(
        as_of=as_of,
        listed=len(quotes),
        candidates=len(candidates),
        checked=len(histories),
        breakouts=len(breakouts),
        failed=failures,
    )
    log.info("신고 거래량 %d종목", len(breakouts))

    period = f"최근 {config.years}년({start}~{as_of})"
    filename = f"신고거래량_{as_of.replace('-', '')}.xlsx"
    excel = write_excel(
        breakouts, Path(config.out_dir) / filename, as_of=as_of, period=period
    )
    log.info("엑셀 생성 완료: %s (%d행)", excel.path, excel.row_count)

    result = PipelineResult(
        as_of=as_of,
        start=start,
        breakouts=breakouts,
        summary=summary,
        excel_path=excel.path,
    )

    if send_mail:
        if mail_config is None:
            raise ValueError("메일을 보내려면 MailConfig 가 필요합니다.")
        subject = (
            f"[신고거래량] {as_of} 기준 최근 {config.years}년 최고 거래량 {len(breakouts)}종목"
        )
        text, body_html = build_mail_bodies(result, config, filename)
        message = build_message(
            mail_config,
            subject=subject,
            body_text=text,
            body_html=body_html,
            attachments=[excel.path],
            sender_name="거래량 알리미",
        )
        send_message(mail_config, message)
        result.mail_sent = True

    return result
