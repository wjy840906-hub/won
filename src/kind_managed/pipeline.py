"""수집 → 사업자번호 결합 → 엑셀 → 메일 전체 흐름."""

from __future__ import annotations

import html
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .config import AppConfig, MailConfig, now_kst
from .dart_client import DartClient, DartError
from .excel_writer import write_excel
from .kind_client import KindClient, ManagedStock
from .mailer import build_message, send_message

log = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """파이프라인 실행 결과."""

    as_of: str
    rows: list[dict[str, str]] = field(default_factory=list)
    excel_path: Path | None = None
    mail_sent: bool = False
    matched_biz_no: int = 0

    @property
    def total(self) -> int:
        return len(self.rows)


def collect_rows(
    stocks: list[ManagedStock],
    dart: DartClient | None,
    as_of: str,
) -> list[dict[str, str]]:
    """관리종목 목록에 DART 기업정보(사업자등록번호 등)를 결합한다."""
    rows: list[dict[str, str]] = []
    for index, stock in enumerate(stocks, start=1):
        row = {
            "no": str(index),
            "market": stock.market,
            "code": stock.code,
            "name": stock.name,
            "biz_no": "",
            "corp_reg_no": "",
            "ceo_name": "",
            "reason": stock.reason,
            "designated_on": stock.designated_on,
            "note": "",
        }
        if dart is None:
            row["note"] = "DART_API_KEY 미설정"
        else:
            info, problem = dart.lookup(stock_code=stock.code, name=stock.name)
            if info is not None:
                row["biz_no"] = info.biz_no
                row["corp_reg_no"] = info.corp_reg_no
                row["ceo_name"] = info.ceo_name
                # KIND 관리종목 표에는 종목코드가 없어 DART 조회 결과로 채운다.
                # 단, 우선주를 보통주로 매칭한 경우의 종목코드는 이 종목의 것이 아니다.
                if not row["code"] and info.stock_code and not info.via_common_stock:
                    row["code"] = info.stock_code.zfill(6)
            if problem:
                row["note"] = problem
        rows.append(row)

    matched = sum(1 for row in rows if row["biz_no"])
    log.info("사업자등록번호 매칭: %d/%d건", matched, len(rows))

    unmatched = [row["name"] for row in rows if not row["biz_no"]]
    if unmatched:
        # 엑셀 '비고' 에도 남지만, 로그에서 바로 보이도록 함께 출력한다.
        log.warning(
            "사업자등록번호 미확인 %d건: %s",
            len(unmatched),
            ", ".join(unmatched[:20]) + (" 외" if len(unmatched) > 20 else ""),
        )
    return rows


def filter_by_from_date(
    stocks: list[ManagedStock], from_date: str
) -> tuple[list[ManagedStock], int]:
    """지정일이 from_date 이후인 종목만 남긴다(빈 값이면 전체).

    지정일을 읽지 못한 행은 누락을 막기 위해 남겨 둔다.
    Returns: (남은 종목, 걸러낸 건수)
    """
    if not from_date:
        return stocks, 0
    kept = [
        stock
        for stock in stocks
        if not stock.designated_on or stock.designated_on >= from_date
    ]
    return kept, len(stocks) - len(kept)


def _summary_lines(rows: list[dict[str, str]], as_of: str) -> list[str]:
    by_market = Counter(row["market"] or "미상" for row in rows)
    new_today = [row for row in rows if row["designated_on"] == as_of]
    matched = sum(1 for row in rows if row["biz_no"])

    lines = [
        f"기준일: {as_of}",
        f"관리종목 수: {len(rows)}종목",
        "시장별: " + (", ".join(f"{k} {v}" for k, v in sorted(by_market.items())) or "-"),
        f"사업자등록번호 확인: {matched}/{len(rows)}건",
        f"당일({as_of}) 신규 지정: {len(new_today)}종목",
    ]
    if new_today:
        lines.append("")
        lines.append("[당일 신규 지정]")
        lines.extend(
            f"  - {row['name']}({row['code'] or '-'}) : {row['reason']}" for row in new_today
        )
    return lines


def build_mail_bodies(
    rows: list[dict[str, str]], as_of: str, filename: str, period: str = ""
) -> tuple[str, str]:
    """메일 본문(텍스트/HTML)을 만든다."""
    lines = _summary_lines(rows, as_of)
    if period:
        lines.insert(1, f"수집 범위: {period}")
    text = "\n".join(
        [
            "안녕하세요.",
            "",
            f"{as_of} 기준 한국거래소 KIND 관리종목 현황"
            + (f" ({period})" if period else "")
            + "을 전달드립니다.",
            "",
            *lines,
            "",
            f"상세 내역은 첨부파일({filename})을 확인해 주세요.",
            "",
            "※ 관리종목: 한국거래소 KIND(kind.krx.co.kr)",
            "※ 사업자등록번호/법인등록번호/대표자: 금융감독원 DART 기업개황",
            "",
            "본 메일은 자동 발송되었습니다.",
        ]
    )

    new_today = [row for row in rows if row["designated_on"] == as_of]
    rows_html = "".join(
        "<tr>"
        f"<td>{html.escape(row['name'])}</td>"
        f"<td style='text-align:center'>{html.escape(row['code'] or '-')}</td>"
        f"<td style='text-align:center'>{html.escape(row['biz_no'] or '-')}</td>"
        f"<td>{html.escape(row['reason'])}</td>"
        "</tr>"
        for row in new_today
    )
    new_section = (
        "<h4 style='margin:16px 0 6px'>당일 신규 지정</h4>"
        "<table cellspacing='0' cellpadding='6' "
        "style='border-collapse:collapse;border:1px solid #ddd;font-size:13px'>"
        "<thead><tr style='background:#1F4E79;color:#fff'>"
        "<th>종목명</th><th>종목코드</th><th>사업자등록번호</th><th>지정사유</th>"
        "</tr></thead>"
        f"<tbody>{rows_html}</tbody></table>"
        if new_today
        else "<p style='color:#666'>당일 신규 지정 종목은 없습니다.</p>"
    )

    summary_html = "".join(f"<li>{html.escape(line)}</li>" for line in lines[:5])
    body_html = f"""<html><body style="font-family:'맑은 고딕',Malgun Gothic,sans-serif;font-size:14px;color:#222">
<p>안녕하세요.</p>
<p><b>{html.escape(as_of)}</b> 기준 한국거래소 KIND 관리종목 현황{html.escape(f" ({period})" if period else "")}을 전달드립니다.</p>
<ul style="line-height:1.7">{summary_html}</ul>
{new_section}
<p>상세 내역은 첨부파일(<b>{html.escape(filename)}</b>)을 확인해 주세요.</p>
<p style="color:#888;font-size:12px">
※ 관리종목: 한국거래소 KIND(kind.krx.co.kr)<br>
※ 사업자등록번호/법인등록번호/대표자: 금융감독원 DART 기업개황<br>
본 메일은 자동 발송되었습니다.
</p>
</body></html>"""
    return text, body_html


def run(
    app_config: AppConfig,
    mail_config: MailConfig,
    send_mail: bool = True,
    stocks: list[ManagedStock] | None = None,
) -> PipelineResult:
    """전체 파이프라인을 실행한다.

    Args:
        stocks: 미리 확보한 관리종목 목록(테스트/재실행용). None 이면 KIND 에서 조회한다.
    """
    as_of = now_kst().strftime("%Y-%m-%d")

    if stocks is None:
        client = KindClient(
            timeout=app_config.request_timeout,
            page_size=app_config.page_size,
            max_pages=app_config.max_pages,
        )
        fetched = client.fetch_managed_stocks(market=app_config.market)
        stocks = fetched.rows
        log.info("KIND 관리종목 %d건 수집 완료", len(stocks))

    if app_config.from_date:
        stocks, dropped = filter_by_from_date(stocks, app_config.from_date)
        log.info(
            "지정일 %s 이후로 한정: %d건 남음 (%d건 제외)",
            app_config.from_date,
            len(stocks),
            dropped,
        )

    dart: DartClient | None = None
    if app_config.dart_api_key:
        try:
            dart = DartClient(
                api_key=app_config.dart_api_key,
                timeout=app_config.request_timeout,
                cache_dir=app_config.cache_dir,
            )
        except DartError as exc:
            log.warning("DART 클라이언트 초기화 실패, 사업자번호 없이 진행합니다: %s", exc)
    else:
        log.warning("DART_API_KEY 가 없어 사업자등록번호 없이 진행합니다.")

    rows = collect_rows(stocks, dart, as_of)

    period = f"{app_config.from_date} 이후 지정분" if app_config.from_date else ""
    filename = f"관리종목_{as_of.replace('-', '')}.xlsx"
    excel = write_excel(
        rows, Path(app_config.out_dir) / filename, as_of=as_of, period=period
    )
    log.info("엑셀 생성 완료: %s (%d행)", excel.path, excel.row_count)

    result = PipelineResult(
        as_of=as_of,
        rows=rows,
        excel_path=excel.path,
        matched_biz_no=sum(1 for row in rows if row["biz_no"]),
    )

    if send_mail:
        scope = f" {app_config.from_date}~" if app_config.from_date else ""
        subject = f"[관리종목] {as_of} 기준{scope} 관리종목 현황 ({len(rows)}종목)"
        text, body_html = build_mail_bodies(rows, as_of, filename, period=period)
        message = build_message(
            mail_config,
            subject=subject,
            body_text=text,
            body_html=body_html,
            attachments=[excel.path],
        )
        send_message(mail_config, message)
        result.mail_sent = True

    return result
