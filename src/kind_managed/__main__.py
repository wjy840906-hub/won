"""CLI 진입점: python -m kind_managed"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path

from .config import AppConfig, MailConfig
from .dart_client import DartError
from .kind_client import MARKET_CHOICES, KindError, parse_rows
from .mailer import MailError
from .pipeline import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m kind_managed",
        description="KIND 관리종목을 수집해 사업자등록번호를 붙인 엑셀을 만들고 메일로 보냅니다.",
    )
    parser.add_argument(
        "--market",
        default=None,
        choices=sorted(MARKET_CHOICES),
        help="시장 구분 (기본: 전체). stockMkt=유가증권, kosdaqMkt=코스닥, konexMkt=코넥스",
    )
    parser.add_argument("--out-dir", default=None, help="엑셀 저장 폴더 (기본: out)")
    parser.add_argument(
        "--no-email", action="store_true", help="메일을 보내지 않고 엑셀만 만듭니다."
    )
    parser.add_argument(
        "--mail-to", default=None, help="수신자(쉼표 구분). 기본값은 MAIL_TO 환경변수."
    )
    parser.add_argument(
        "--html-file",
        default=None,
        help="KIND 대신 로컬 HTML 파일을 파싱합니다(오프라인 점검용).",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="상세 로그 출력")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    app_config = AppConfig.from_env()
    if args.market is not None:
        app_config = replace(app_config, market=args.market)
    if args.out_dir is not None:
        app_config = replace(app_config, out_dir=args.out_dir)

    mail_config = MailConfig.from_env()
    if args.mail_to:
        recipients = [addr.strip() for addr in args.mail_to.split(",") if addr.strip()]
        mail_config = replace(mail_config, to=recipients)

    send_mail = not args.no_email
    if send_mail:
        problems = mail_config.validate()
        if problems:
            print("메일 설정 오류:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            print(
                "  (엑셀만 만들려면 --no-email 을 사용하세요.)",
                file=sys.stderr,
            )
            return 2

    stocks = None
    if args.html_file:
        stocks = parse_rows(Path(args.html_file).read_text(encoding="utf-8"))
        print(f"로컬 HTML에서 {len(stocks)}건을 파싱했습니다: {args.html_file}")

    try:
        result = run(app_config, mail_config, send_mail=send_mail, stocks=stocks)
    except (KindError, DartError, MailError) as exc:
        logging.getLogger("kind_managed").error("%s", exc)
        return 1

    print(
        f"완료: {result.as_of} 기준 {result.total}종목 "
        f"(사업자번호 {result.matched_biz_no}건) → {result.excel_path}"
        + (" / 메일 발송됨" if result.mail_sent else " / 메일 미발송")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
