"""CLI 동작과 종료 코드."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from booking_macro.__main__ import EXIT_CONFIG, EXIT_OK, main

EXAMPLE = str(Path(__file__).resolve().parents[1] / "scenarios" / "example-meeting-room.yaml")


def test_후보_목록을_보여_준다(capsys):
    코드 = main([EXAMPLE, "--list-targets"])

    출력 = capsys.readouterr().out
    assert 코드 == EXIT_OK
    assert "예약 후보 4개" in 출력
    assert "1순위" in 출력
    assert "BOOKING_USER, BOOKING_PASSWORD" in 출력


def test_검사만_할_때는_브라우저를_띄우지_않는다(capsys, monkeypatch):
    def 터지는_브라우저(*args, **kwargs):  # pragma: no cover - 불리면 실패
        raise AssertionError("브라우저를 띄우면 안 됩니다")

    monkeypatch.setattr("booking_macro.__main__.open_page", 터지는_브라우저)

    assert main([EXAMPLE, "--check"]) == EXIT_OK
    assert "사내 회의실 예약" in capsys.readouterr().out


def test_시나리오를_주지_않으면_사용법을_알려_준다(capsys):
    코드 = main([])

    assert 코드 == EXIT_CONFIG
    assert "시나리오 파일을 지정하세요" in capsys.readouterr().err


def test_깨진_시나리오는_설정_오류로_끝난다(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"name": "x"}), encoding="utf-8")

    코드 = main([str(path), "--check"])

    assert 코드 == EXIT_CONFIG
    assert "시나리오 오류" in capsys.readouterr().err


def test_재시도_횟수는_1_이상이어야_한다(capsys):
    코드 = main([EXAMPLE, "--check", "--attempts", "0"])

    assert 코드 == EXIT_CONFIG
    assert "--attempts" in capsys.readouterr().err


@pytest.mark.parametrize("옵션", ["--email", "--mail-to=a@b.com"])
def test_메일_설정이_없으면_실행_전에_알려_준다(옵션, capsys, monkeypatch):
    monkeypatch.setenv("BOOKING_USER", "hong")
    monkeypatch.setenv("BOOKING_PASSWORD", "비밀")
    for name in ("SMTP_HOST", "MAIL_FROM", "SMTP_USER", "MAIL_TO"):
        monkeypatch.delenv(name, raising=False)

    코드 = main([EXAMPLE, 옵션])

    assert 코드 == EXIT_CONFIG
    assert "메일 설정 오류" in capsys.readouterr().err


def test_브라우저_설정이_잘못되면_설정_오류다(capsys, monkeypatch):
    monkeypatch.setenv("BOOKING_BROWSER", "익스플로러")

    코드 = main([EXAMPLE, "--check"])

    assert 코드 == EXIT_CONFIG
    assert "BOOKING_BROWSER" in capsys.readouterr().err


def test_계정_환경변수가_비면_브라우저를_띄우기_전에_멈춘다(capsys, monkeypatch):
    monkeypatch.delenv("BOOKING_PASSWORD", raising=False)
    monkeypatch.setenv("BOOKING_USER", "hong")

    def 터지는_브라우저(*args, **kwargs):  # pragma: no cover - 불리면 실패
        raise AssertionError("브라우저를 띄우면 안 됩니다")

    monkeypatch.setattr("booking_macro.__main__.open_page", 터지는_브라우저)

    코드 = main([EXAMPLE])

    assert 코드 == EXIT_CONFIG
    assert "BOOKING_PASSWORD" in capsys.readouterr().err
