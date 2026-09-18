"""CLI 인자 처리 테스트."""

from __future__ import annotations

from volume_peak import __main__ as cli
from volume_peak.config import ScreenConfig
from volume_peak.krx_client import KrxError
from volume_peak.pipeline import PipelineResult
from volume_peak.screener import Breakout, ScreenSummary


def parse(argv):
    return cli.build_parser().parse_args(argv)


def test_인자가_설정을_덮어쓴다():
    config = cli._apply_args(
        ScreenConfig(),
        parse(
            [
                "--date", "20260917",
                "--years", "5",
                "--market", "코스닥",
                "--min-volume", "50000",
                "--top", "30",
                "--sort", "ratio",
                "--include-preferred",
                "--include-short-history",
            ]
        ),
    )

    assert config.trade_date == "2026-09-17"
    assert config.years == 5
    assert config.market == "KSQ"
    assert config.min_volume == 50_000
    assert config.top == 30
    assert config.sort == "ratio"
    assert config.include_preferred is True
    assert config.include_short_history is True


def test_인자가_없으면_기본값_유지():
    config = cli._apply_args(ScreenConfig(), parse([]))
    assert config == ScreenConfig()


def _fake_result() -> PipelineResult:
    hit = Breakout(
        code="000100",
        name="신고거래량",
        market="KOSPI",
        as_of="2026-09-17",
        volume=5_000_000,
        prev_peak=2_000_000,
        prev_peak_date="2020-03-19",
        close=10_000,
        change_rate=12.5,
        value=10**11,
        history_from="2017-03-02",
        history_days=2_300,
    )
    return PipelineResult(
        as_of="2026-09-17",
        start="2016-09-18",
        breakouts=[hit],
        summary=ScreenSummary(as_of="2026-09-17", breakouts=1),
        excel_path=None,
    )


def test_엑셀만_만드는_실행(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run", lambda *args, **kwargs: _fake_result())

    assert cli.main(["--no-email", "--date", "2026-09-17"]) == 0
    out = capsys.readouterr().out
    assert "신고 거래량 1종목" in out
    assert "신고거래량(000100)" in out
    assert "2.50배" in out
    assert "메일 미발송" in out


def test_메일_설정이_없으면_2번으로_끝난다(monkeypatch, capsys):
    for name in ("SMTP_HOST", "MAIL_FROM", "SMTP_USER", "MAIL_TO"):
        monkeypatch.delenv(name, raising=False)

    assert cli.main([]) == 2
    assert "메일 설정 오류" in capsys.readouterr().err


def test_잘못된_인자는_2번(capsys):
    assert cli.main(["--no-email", "--date", "2026-13-01"]) == 2
    assert cli.main(["--no-email", "--years", "0"]) == 2
    assert "오류" in capsys.readouterr().err


def test_조회_실패는_1번(monkeypatch):
    def boom(*args, **kwargs):
        raise KrxError("차단됨")

    monkeypatch.setattr(cli, "run", boom)
    assert cli.main(["--no-email"]) == 1
