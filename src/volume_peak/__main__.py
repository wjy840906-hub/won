"""CLI 진입점: python -m volume_peak"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace

from kind_managed.config import MailConfig
from kind_managed.mailer import MailError

from .config import MARKET_CHOICES, SORT_CHOICES, ScreenConfig, normalize_date, normalize_market
from .krx_client import KrxError
from .pipeline import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m volume_peak",
        description=(
            "기준일 거래량이 최근 N년(기본 10년) 최고치인 종목을 골라 엑셀로 만들고 메일로 보냅니다."
        ),
    )
    parser.add_argument("--date", default=None, help="기준일 (예: 2026-09-17). 기본: 최근 영업일")
    parser.add_argument("--years", type=int, default=None, help="비교 기간(년, 기본 10)")
    parser.add_argument(
        "--market",
        default=None,
        help="시장 (ALL/STK/KSQ/KNX 또는 유가증권/코스닥/코넥스, 기본 전체)",
    )
    parser.add_argument(
        "--min-volume", type=int, default=None, help="기준일 거래량 하한(주, 기본 100000)"
    )
    parser.add_argument(
        "--min-value", type=int, default=None, help="기준일 거래대금 하한(원, 기본 1000000000)"
    )
    parser.add_argument(
        "--min-history-days",
        type=int,
        default=None,
        help="최소 거래일 수(기본 250). 이보다 짧으면 신규상장으로 보고 제외",
    )
    parser.add_argument(
        "--include-short-history",
        action="store_true",
        help="이력이 짧은 종목도 포함(비고에 표시)",
    )
    parser.add_argument(
        "--include-preferred", action="store_true", help="우선주·신주인수권 등도 포함"
    )
    parser.add_argument("--top", type=int, default=None, help="상위 N종목만 (기본 전체)")
    parser.add_argument(
        "--sort",
        default=None,
        choices=sorted(SORT_CHOICES),
        help="정렬 기준: value=거래대금, ratio=직전 최고 대비 배수, volume=거래량 (기본 value)",
    )
    parser.add_argument("--workers", type=int, default=None, help="동시 조회 수 (기본 8)")
    parser.add_argument("--out-dir", default=None, help="엑셀 저장 폴더 (기본 out)")
    parser.add_argument(
        "--no-cache", action="store_true", help="일별 시세 캐시를 쓰지 않고 매번 새로 받습니다."
    )
    parser.add_argument("--no-email", action="store_true", help="메일 없이 엑셀만 만듭니다.")
    parser.add_argument("--mail-to", default=None, help="수신자(쉼표 구분). 기본값은 MAIL_TO.")
    parser.add_argument("--verbose", "-v", action="store_true", help="상세 로그 출력")
    return parser


def _apply_args(config: ScreenConfig, args: argparse.Namespace) -> ScreenConfig:
    if args.date is not None:
        config = replace(config, trade_date=normalize_date(args.date))
    if args.market is not None:
        config = replace(config, market=normalize_market(args.market))
    for name, field in (
        ("years", "years"),
        ("min_volume", "min_volume"),
        ("min_value", "min_value"),
        ("min_history_days", "min_history_days"),
        ("top", "top"),
        ("workers", "workers"),
        ("sort", "sort"),
        ("out_dir", "out_dir"),
    ):
        value = getattr(args, name)
        if value is not None:
            config = replace(config, **{field: value})
    if args.include_short_history:
        config = replace(config, include_short_history=True)
    if args.include_preferred:
        config = replace(config, include_preferred=True)
    return config


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        config = _apply_args(ScreenConfig.from_env(), args)
    except ValueError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2

    problems = config.validate()
    if problems:
        for problem in problems:
            print(f"오류: {problem}", file=sys.stderr)
        return 2

    mail_config = MailConfig.from_env()
    if args.mail_to:
        recipients = [addr.strip() for addr in args.mail_to.split(",") if addr.strip()]
        mail_config = replace(mail_config, to=recipients)

    send_mail = not args.no_email
    if send_mail:
        mail_problems = mail_config.validate()
        if mail_problems:
            print("메일 설정 오류:", file=sys.stderr)
            for problem in mail_problems:
                print(f"  - {problem}", file=sys.stderr)
            print("  (엑셀만 만들려면 --no-email 을 사용하세요.)", file=sys.stderr)
            return 2

    try:
        result = run(config, mail_config, send_mail=send_mail, use_cache=not args.no_cache)
    except (KrxError, MailError, ValueError) as exc:
        logging.getLogger("volume_peak").error("%s", exc)
        return 1

    market_label = MARKET_CHOICES.get(config.market, config.market)
    print(
        f"\n{result.as_of} 기준 · 최근 {config.years}년({result.start}~{result.as_of}) "
        f"· {market_label} · 신고 거래량 {result.total}종목"
    )
    for index, item in enumerate(result.breakouts[:20], start=1):
        print(
            f"{index:3d}. {item.name}({item.code}) {item.volume:>14,}주  "
            f"직전 최고 {item.prev_peak:>14,}주({item.prev_peak_date}) "
            f"= {item.ratio:>6,.2f}배  종가 {item.close:,}원 {item.change_rate:+.2f}%"
        )
    if result.total > 20:
        print(f"     … 외 {result.total - 20}종목 (전체는 엑셀 참고)")
    print(
        f"\n엑셀: {result.excel_path}"
        + (" / 메일 발송됨" if result.mail_sent else " / 메일 미발송")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
