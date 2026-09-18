"""CLI 진입점: python -m booking_macro"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace

from kind_managed.config import MailConfig

from .browser import BrowserError, open_page
from .config import BookingConfig, now_kst, scenario_env
from .notify import notify
from .runner import Outcome, run_scenario
from .scenario import ACTIONS, ScenarioError, load_scenario
from .scheduler import resolve_open_at
from .slots import resolve_targets

EXIT_OK = 0
EXIT_NOT_RESERVED = 1
EXIT_CONFIG = 2
EXIT_ERROR = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m booking_macro",
        description="시나리오(YAML)에 적어 둔 예약 절차를 브라우저로 대신 수행합니다.",
        epilog="사용할 수 있는 단계: " + ", ".join(f"{name}({desc})" for name, desc in ACTIONS.items()),
    )
    parser.add_argument("scenario", nargs="?", help="시나리오 파일 경로(.yaml / .json)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="commit 으로 표시한 확정 단계를 누르지 않고 직전까지만 진행합니다.",
    )
    parser.add_argument("--headed", action="store_true", help="브라우저 창을 띄워 눈으로 확인합니다.")
    parser.add_argument("--now", action="store_true", help="open_at 을 무시하고 즉시 시도합니다.")
    parser.add_argument("--attempts", type=int, default=None, help="재시도 횟수(시나리오 값보다 우선)")
    parser.add_argument("--interval", type=float, default=None, help="재시도 간격(초)")
    parser.add_argument("--check", action="store_true", help="시나리오만 검사하고 끝냅니다(브라우저 없음).")
    parser.add_argument("--list-targets", action="store_true", help="펼쳐진 예약 후보를 순서대로 보여 줍니다.")
    parser.add_argument("--email", action="store_true", help="결과를 메일로 보냅니다.")
    parser.add_argument("--mail-to", default=None, help="결과 메일 수신자(쉼표 구분)")
    parser.add_argument("--out-dir", default=None, help="화면 저장 폴더 (기본: out/booking)")
    parser.add_argument("--verbose", "-v", action="store_true", help="상세 로그 출력")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.scenario:
        print("시나리오 파일을 지정하세요. 예: python -m booking_macro scenarios/example-meeting-room.yaml",
              file=sys.stderr)
        return EXIT_CONFIG

    try:
        scenario = load_scenario(args.scenario)
    except ScenarioError as exc:
        print(f"시나리오 오류: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    try:
        config = BookingConfig.from_env()
    except ValueError as exc:
        print(f"설정 오류: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    if args.headed:
        config = replace(config, headless=False)
    if args.dry_run:
        config = replace(config, dry_run=True)
    if args.attempts is not None:
        if args.attempts < 1:
            print("오류: --attempts 는 1 이상이어야 합니다.", file=sys.stderr)
            return EXIT_CONFIG
        config = replace(config, attempts=args.attempts)
    if args.interval is not None:
        config = replace(config, interval_sec=args.interval)
    if args.out_dir is not None:
        config = replace(config, out_dir=args.out_dir)

    problems = config.validate()
    if problems:
        print("설정 오류:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return EXIT_CONFIG

    started_at = now_kst()
    try:
        targets = resolve_targets(scenario.targets, started_at.date())
        opens_at = resolve_open_at(scenario.open_at, started_at)
    except ScenarioError as exc:
        print(f"시나리오 오류: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    if args.check or args.list_targets:
        print(f"시나리오: {scenario.name}  ({scenario.base_url})")
        print(f"필요한 환경변수: {', '.join(scenario.env_names) or '없음'}")
        print(f"예약 오픈: {opens_at:%Y-%m-%d %H:%M:%S}" if opens_at else "예약 오픈: 즉시 실행")
        print(f"재시도: {scenario.attempts}회 · 간격 {scenario.interval_sec:g}초")
        print(f"예약 후보 {len(targets)}개 (위에서부터 우선)")
        for target in targets:
            print(f"  {target.describe()}")
        return EXIT_OK

    # 브라우저를 띄우기 전에 아이디·비밀번호가 채워져 있는지 먼저 본다.
    try:
        scenario_env(scenario.env_names)
    except ValueError as exc:
        print(f"설정 오류: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    mail_config = MailConfig.from_env()
    if args.mail_to:
        mail_config = replace(
            mail_config, to=[addr.strip() for addr in args.mail_to.split(",") if addr.strip()]
        )
    send_mail = args.email or bool(args.mail_to)
    if send_mail:
        mail_problems = mail_config.validate()
        if mail_problems:
            print("메일 설정 오류:", file=sys.stderr)
            for problem in mail_problems:
                print(f"  - {problem}", file=sys.stderr)
            return EXIT_CONFIG

    try:
        with open_page(config) as page:
            result = run_scenario(
                scenario, config, page, targets=targets, wait_open=not args.now
            )
    except BrowserError as exc:
        print(f"브라우저 오류: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except ScenarioError as exc:
        print(f"시나리오 오류: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except ValueError as exc:  # 환경변수 누락 등
        print(f"설정 오류: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    print(result.summary())
    for attempt in result.attempts:
        print(f"  - {attempt.describe()}")
    for path in result.screenshots:
        print(f"  화면 저장: {path}")

    if send_mail:
        print("결과 메일 발송됨" if notify(mail_config, result) else "결과 메일 발송 실패")

    if result.error:
        return EXIT_ERROR
    if result.reserved is None:
        return EXIT_NOT_RESERVED
    return EXIT_OK if result.reserved.outcome in {Outcome.SUCCESS, Outcome.DRY_RUN} else EXIT_NOT_RESERVED


if __name__ == "__main__":
    raise SystemExit(main())
