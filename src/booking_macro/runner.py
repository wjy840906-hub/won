"""로그인 → 후보 순회 → 예약 시도 전체 흐름."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from .config import BookingConfig, now_kst, scenario_env
from .scenario import Phase, Scenario
from .scheduler import deadline_passed, resolve_open_at, retry_delay, wait_until
from .slots import ResolvedTarget, resolve_targets
from .steps import (
    SlotUnavailable,
    StepContext,
    StepError,
    evaluate_match,
    run_steps,
    take_screenshot,
)

log = logging.getLogger(__name__)


class LoginError(RuntimeError):
    """로그인 단계 실패 — 후보를 돌려 봐야 소용없으므로 즉시 중단한다."""


class Outcome(str, Enum):
    """후보 하나에 대한 시도 결과."""

    SUCCESS = "예약됨"
    TAKEN = "마감"
    FAILED = "실패"
    DRY_RUN = "모의"

    @property
    def is_final(self) -> bool:
        """더 시도할 필요가 없는 결과인지."""
        return self in {Outcome.SUCCESS, Outcome.DRY_RUN}


@dataclass
class Attempt:
    """후보 하나를 한 번 시도한 기록."""

    round_no: int
    target: ResolvedTarget
    outcome: Outcome
    message: str = ""
    steps: list[str] = field(default_factory=list)
    screenshot: Path | None = None

    def describe(self) -> str:
        return f"{self.round_no}회차 · {self.target.describe()} → {self.outcome.value}" + (
            f" ({self.message})" if self.message else ""
        )


@dataclass
class BookingResult:
    """실행 전체 결과."""

    scenario_name: str
    started_at: datetime
    finished_at: datetime | None = None
    dry_run: bool = False
    attempts: list[Attempt] = field(default_factory=list)
    reserved: Attempt | None = None
    error: str = ""

    @property
    def succeeded(self) -> bool:
        return self.reserved is not None and self.reserved.outcome is Outcome.SUCCESS

    @property
    def rounds(self) -> int:
        return max((attempt.round_no for attempt in self.attempts), default=0)

    @property
    def screenshots(self) -> list[Path]:
        return [attempt.screenshot for attempt in self.attempts if attempt.screenshot]

    def summary(self) -> str:
        if self.error:
            return f"중단: {self.error}"
        if self.reserved is None:
            return f"예약하지 못했습니다 ({self.rounds}회차 · 시도 {len(self.attempts)}건)"
        prefix = "모의 실행 성공" if self.reserved.outcome is Outcome.DRY_RUN else "예약 성공"
        return f"{prefix}: {self.reserved.target.label}"


def _run_login(page: Any, phase: Phase, context: StepContext) -> None:
    """로그인 단계를 실행하고 성공 조건을 확인한다."""
    if phase.url:
        page.goto(
            context.absolute(context.resolve(phase.url, "login.url")),
            timeout=context.config.nav_timeout_ms,
            wait_until=context.config.wait_until,
        )
    try:
        run_steps(page, phase.steps, context, "login")
    except StepError as exc:
        take_screenshot(page, context, "login-실패")
        raise LoginError(f"로그인 실패 — {exc}") from exc

    if not phase.success_when.is_empty:
        ok, reason = evaluate_match(page, phase.success_when)
        if not ok:
            take_screenshot(page, context, "login-실패")
            raise LoginError(f"로그인 후 확인 실패 — {reason}")
    log.info("로그인 완료")


def _attempt_target(
    page: Any,
    scenario: Scenario,
    config: BookingConfig,
    target: ResolvedTarget,
    round_no: int,
    variables: dict[str, Any],
    dry_run: bool,
) -> Attempt:
    """후보 하나에 대해 예약 단계를 한 번 실행한다."""
    phase = scenario.reserve
    tag = f"r{round_no}-t{target.index}"
    context = StepContext(
        config=config,
        base_url=scenario.base_url,
        variables={**variables, "target": target.fields},
        dry_run=dry_run,
        tag=tag,
    )

    try:
        if phase.url:
            page.goto(
                context.absolute(context.resolve(phase.url, "reserve.url")),
                timeout=config.nav_timeout_ms,
                wait_until=config.wait_until,
            )
        run_steps(page, phase.steps, context, "reserve")
    except SlotUnavailable as exc:
        # 코드가 잘못된 것이 아니라 그 자리가 안 되는 것이다. 다음 후보로 넘어간다.
        shot = take_screenshot(page, context, f"{tag}-마감") if config.screenshot == "always" else None
        return Attempt(round_no, target, Outcome.TAKEN, str(exc), context.performed, shot)
    except StepError as exc:
        shot = take_screenshot(page, context, f"{tag}-실패") if config.screenshot != "never" else None
        return Attempt(round_no, target, Outcome.FAILED, str(exc), context.performed, shot)
    except Exception as exc:  # noqa: BLE001 - 한 후보의 사고가 전체를 멈추지 않도록
        shot = take_screenshot(page, context, f"{tag}-오류") if config.screenshot != "never" else None
        return Attempt(
            round_no, target, Outcome.FAILED, f"{type(exc).__name__}: {exc}", context.performed, shot
        )

    taken_ok, taken_reason = (
        evaluate_match(page, phase.taken_when) if not phase.taken_when.is_empty else (False, "")
    )
    if taken_ok:
        shot = take_screenshot(page, context, f"{tag}-마감") if config.screenshot == "always" else None
        return Attempt(round_no, target, Outcome.TAKEN, taken_reason, context.performed, shot)

    if phase.success_when.is_empty:
        outcome = Outcome.DRY_RUN if dry_run else Outcome.SUCCESS
        message = "success_when 이 없어 단계 완료를 성공으로 봅니다"
        shot = take_screenshot(page, context, f"{tag}-완료")
        return Attempt(round_no, target, outcome, message, context.performed, shot)

    success_ok, success_reason = evaluate_match(page, phase.success_when)
    if success_ok:
        shot = take_screenshot(page, context, f"{tag}-성공")
        outcome = Outcome.DRY_RUN if dry_run else Outcome.SUCCESS
        return Attempt(round_no, target, outcome, success_reason, context.performed, shot)

    if dry_run:
        # 마지막 확정 클릭을 누르지 않았으니 성공 문구가 없는 것이 정상이다.
        shot = take_screenshot(page, context, f"{tag}-모의")
        return Attempt(
            round_no, target, Outcome.DRY_RUN, "확정 단계를 건너뛰어 성공 문구는 확인하지 않음",
            context.performed, shot,
        )

    shot = take_screenshot(page, context, f"{tag}-확인불가")
    return Attempt(round_no, target, Outcome.FAILED, f"성공 확인 실패 — {success_reason}",
                   context.performed, shot)


def run_scenario(
    scenario: Scenario,
    config: BookingConfig,
    page: Any,
    *,
    targets: list[ResolvedTarget] | None = None,
    dry_run: bool | None = None,
    wait_open: bool = True,
    now_fn: Callable[[], datetime] = now_kst,
    sleep: Callable[[float], None] = time.sleep,
) -> BookingResult:
    """시나리오를 실행한다. 페이지는 호출한 쪽에서 준비해 넘긴다."""
    dry_run = config.dry_run if dry_run is None else dry_run
    started_at = now_fn()
    result = BookingResult(
        scenario_name=scenario.name, started_at=started_at, dry_run=dry_run
    )

    variables: dict[str, Any] = {
        "env": scenario_env(scenario.env_names),
        "today": started_at.date().isoformat(),
        "now": started_at.strftime("%Y-%m-%d %H:%M:%S"),
    }
    candidates = targets if targets is not None else resolve_targets(scenario.targets, started_at.date())

    if wait_open and scenario.open_at:
        opens_at = resolve_open_at(scenario.open_at, started_at)
        if opens_at is not None:
            wait_until(opens_at, now_fn=now_fn, sleep=sleep)

    login_context = StepContext(
        config=config, base_url=scenario.base_url, variables=variables, dry_run=dry_run, tag="login"
    )
    if scenario.login is not None:
        try:
            _run_login(page, scenario.login, login_context)
        except LoginError as exc:
            result.error = str(exc)
            result.finished_at = now_fn()
            return result

    attempts = config.attempts or scenario.attempts
    interval = config.interval_sec or scenario.interval_sec

    for round_no in range(1, attempts + 1):
        for target in candidates:
            log.info("시도: %s (%d/%d회차)", target.describe(), round_no, attempts)
            attempt = _attempt_target(
                page, scenario, config, target, round_no, variables, dry_run
            )
            result.attempts.append(attempt)
            log.info("결과: %s", attempt.describe())
            if attempt.outcome.is_final:
                result.reserved = attempt
                result.finished_at = now_fn()
                return result

        if round_no >= attempts:
            break
        if deadline_passed(started_at, scenario.deadline_sec, now_fn()):
            result.error = f"제한 시간({scenario.deadline_sec:.0f}초)을 넘겨 중단했습니다."
            break
        sleep(retry_delay(interval, scenario.jitter_sec))

    result.finished_at = now_fn()
    return result
