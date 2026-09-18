"""CLI 진입점: python -m novel_writer"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace

from .claude_client import ClaudeError
from .config import EFFORT_CHOICES, Brief, NovelConfig
from .pipeline import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m novel_writer",
        description="소재 한 줄을 주면 기획을 짜고 장별로 소설을 써서 원고 파일로 저장합니다.",
    )
    parser.add_argument(
        "idea",
        nargs="?",
        default="",
        help='무엇을 쓸지 한두 문장으로 (예: "퇴근길 지하철에서 어제로 돌아가는 남자")',
    )
    parser.add_argument("--title", default="", help="희망 제목(비우면 모델이 짓습니다)")
    parser.add_argument("--genre", default="", help="장르 (예: 미스터리, 로맨스, SF)")
    parser.add_argument("--tone", default="", help="분위기·문체 (예: 담백하고 건조한 문체)")
    parser.add_argument("--pov", default="", help="시점 (예: 1인칭 주인공, 3인칭 관찰자)")
    parser.add_argument("--audience", default="", help="독자층 (예: 성인 일반, 청소년)")
    parser.add_argument("--notes", default="", help="그 밖의 요구 (예: 결말은 열린 결말로)")
    parser.add_argument("--chapters", type=int, default=None, help="장 수 (기본: 10)")
    parser.add_argument(
        "--chars", type=int, default=None, help="장당 목표 글자수 (기본: 3000)"
    )
    parser.add_argument("--model", default=None, help="모델 (기본: claude-opus-5)")
    parser.add_argument(
        "--effort", default=None, choices=sorted(EFFORT_CHOICES), help="공들이는 정도 (기본: high)"
    )
    parser.add_argument("--out-dir", default=None, help="작업 폴더 상위 경로 (기본: out/novel)")
    parser.add_argument(
        "--resume", default=None, metavar="폴더", help="저장된 작업 폴더를 이어서 씁니다."
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=0,
        metavar="N",
        help="이번 실행에서 N장만 씁니다 (연재처럼 나눠 쓸 때).",
    )
    parser.add_argument(
        "--plan-only", action="store_true", help="기획(줄거리·인물·장 구성)만 만들고 멈춥니다."
    )
    parser.add_argument("--email", action="store_true", help="완성된 원고를 메일로 보냅니다.")
    parser.add_argument("--mail-to", default=None, help="수신자(쉼표 구분). 기본값은 MAIL_TO 환경변수.")
    parser.add_argument("--verbose", "-v", action="store_true", help="상세 로그 출력")
    return parser


def _mail_config(args):
    """--email 일 때만 메일 설정을 만든다(설정은 kind_managed 와 공유)."""
    from kind_managed.config import MailConfig

    config = MailConfig.from_env()
    if args.mail_to:
        recipients = [addr.strip() for addr in args.mail_to.split(",") if addr.strip()]
        config = replace(config, to=recipients)
    return config


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.idea and not args.resume:
        print(
            '무엇을 쓸지 알려 주세요. 예: python -m novel_writer "낡은 등대를 지키는 소년"',
            file=sys.stderr,
        )
        return 2

    config = NovelConfig.from_env()
    if args.model:
        config = replace(config, model=args.model)
    if args.effort:
        config = replace(config, effort=args.effort)
    if args.chapters is not None:
        config = replace(config, chapters=args.chapters)
    if args.chars is not None:
        config = replace(config, chapter_chars=args.chars)
    if args.out_dir:
        config = replace(config, out_dir=args.out_dir)

    problems = config.validate()
    if problems:
        print("설정 오류:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2

    mail_config = None
    if args.email:
        mail_config = _mail_config(args)
        mail_problems = mail_config.validate()
        if mail_problems:
            print("메일 설정 오류:", file=sys.stderr)
            for problem in mail_problems:
                print(f"  - {problem}", file=sys.stderr)
            print("  (메일 없이 쓰려면 --email 을 빼세요.)", file=sys.stderr)
            return 2

    brief = Brief(
        idea=args.idea,
        title=args.title,
        genre=args.genre,
        tone=args.tone,
        pov=args.pov,
        audience=args.audience,
        notes=args.notes,
    )

    try:
        result = run(
            config,
            brief,
            resume_dir=args.resume,
            plan_only=args.plan_only,
            chapters_limit=args.batch,
            mail_config=mail_config,
        )
    except ClaudeError as exc:
        logging.getLogger("novel_writer").error("%s", exc)
        return 1
    except KeyboardInterrupt:
        print("\n중단했습니다. 쓴 장까지는 저장돼 있습니다.", file=sys.stderr)
        return 1

    if args.plan_only:
        print(f"기획 완료: 「{result.title}」 {result.total_chapters}장 → {result.directory}")
        print(f"  이어서 쓰려면: python -m novel_writer --resume {result.directory}")
    else:
        state = "완성" if result.finished else f"{result.written}/{result.total_chapters}장"
        print(
            f"「{result.title}」 {state} · {result.total_chars:,}자 → {result.files[0]}"
            + (" / 메일 발송됨" if result.mail_sent else "")
        )
        if not result.finished:
            print(f"  이어서 쓰려면: python -m novel_writer --resume {result.directory}")
    if result.usage:
        print(f"  사용량: {result.usage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
