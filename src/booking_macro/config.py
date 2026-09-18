"""예약 매크로 실행 설정(환경변수 기반).

아이디·비밀번호는 시나리오 파일이 아니라 환경변수에 두고,
시나리오에서는 `{{ env.BOOKING_PASSWORD }}` 로 참조한다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from kind_managed.config import KST, now_kst  # noqa: F401  (다른 모듈에서 재사용)

BROWSERS = ("chromium", "firefox", "webkit")

# 시나리오에 넘길 환경변수 이름 규칙 — 자격증명 전체가 아니라 이 접두사만 노출한다.
ENV_PREFIXES = ("BOOKING_", "RESERVE_")


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"환경변수 {name} 값이 정수가 아닙니다: {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"환경변수 {name} 값이 숫자가 아닙니다: {raw!r}") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class BookingConfig:
    """브라우저 구동과 실행 방식 설정."""

    browser: str = "chromium"
    headless: bool = True
    slow_mo_ms: int = 0
    nav_timeout_ms: int = 20000
    step_timeout_ms: int = 10000
    out_dir: str = "out/booking"
    screenshot: str = "change"  # always | change | never
    state_file: str = ""  # 로그인 세션 저장 경로(비우면 매번 로그인)
    user_agent: str = ""
    dry_run: bool = False
    attempts: int = 0  # 0 이면 시나리오 값을 따름
    interval_sec: float = 0.0
    executable_path: str = ""

    @classmethod
    def from_env(cls) -> "BookingConfig":
        browser = _env("BOOKING_BROWSER", "chromium").lower()
        if browser not in BROWSERS:
            raise ValueError(f"BOOKING_BROWSER 는 {', '.join(BROWSERS)} 중 하나여야 합니다: {browser!r}")
        return cls(
            browser=browser,
            headless=_env_bool("BOOKING_HEADLESS", True),
            slow_mo_ms=_env_int("BOOKING_SLOW_MO_MS", 0),
            nav_timeout_ms=_env_int("BOOKING_NAV_TIMEOUT_MS", 20000),
            step_timeout_ms=_env_int("BOOKING_STEP_TIMEOUT_MS", 10000),
            out_dir=_env("BOOKING_OUT_DIR", "out/booking"),
            screenshot=_env("BOOKING_SCREENSHOT", "change").lower(),
            state_file=_env("BOOKING_STATE_FILE"),
            user_agent=_env("BOOKING_USER_AGENT"),
            dry_run=_env_bool("BOOKING_DRY_RUN", False),
            attempts=_env_int("BOOKING_ATTEMPTS", 0),
            interval_sec=_env_float("BOOKING_INTERVAL_SEC", 0.0),
            executable_path=_env("PLAYWRIGHT_EXECUTABLE_PATH"),
        )

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.browser not in BROWSERS:
            problems.append(f"browser 는 {', '.join(BROWSERS)} 중 하나여야 합니다.")
        if self.screenshot not in {"always", "change", "never"}:
            problems.append("BOOKING_SCREENSHOT 은 always / change / never 중 하나여야 합니다.")
        if self.nav_timeout_ms <= 0 or self.step_timeout_ms <= 0:
            problems.append("타임아웃은 0보다 커야 합니다.")
        return problems


def scenario_env(required: list[str]) -> dict[str, str]:
    """시나리오가 참조하는 환경변수만 골라 담는다.

    시나리오 파일이 임의의 환경변수를 읽어 가지 못하도록,
    `BOOKING_`/`RESERVE_` 로 시작하는 이름만 허용한다.
    """
    values: dict[str, str] = {}
    rejected: list[str] = []
    missing: list[str] = []
    for name in required:
        if not name.startswith(ENV_PREFIXES):
            rejected.append(name)
            continue
        value = _env(name)
        if not value:
            missing.append(name)
            continue
        values[name] = value

    if rejected:
        raise ValueError(
            "시나리오에서 쓸 수 있는 환경변수는 "
            + " / ".join(f"{prefix}*" for prefix in ENV_PREFIXES)
            + f" 뿐입니다. 허용되지 않은 이름: {', '.join(rejected)}"
        )
    if missing:
        raise ValueError(
            "시나리오가 필요로 하는 환경변수가 비어 있습니다: " + ", ".join(missing)
        )
    return values
