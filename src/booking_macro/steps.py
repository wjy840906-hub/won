"""시나리오 단계를 실제 브라우저 페이지에서 실행한다.

Playwright 의 sync `Page` 를 그대로 받지만 타입으로 묶지 않았다.
같은 메서드만 가지면 되므로 테스트에서는 가짜 페이지를 넣어 검증한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from .config import BookingConfig
from .scenario import Match, Step
from .template import TemplateError, render

log = logging.getLogger(__name__)


class StepError(RuntimeError):
    """단계 실행 실패."""


@dataclass
class StepContext:
    """단계 실행에 필요한 주변 정보."""

    config: BookingConfig
    base_url: str = ""
    variables: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False
    tag: str = ""
    performed: list[str] = field(default_factory=list)
    screenshots: list[Path] = field(default_factory=list)

    def resolve(self, text: str, where: str) -> str:
        try:
            return render(text, self.variables)
        except TemplateError as exc:
            raise StepError(f"{where}: {exc}") from exc

    def absolute(self, url: str) -> str:
        if not url:
            return ""
        if url.startswith(("http://", "https://")):
            return url
        return urljoin(self.base_url.rstrip("/") + "/", url.lstrip("/"))


def page_text(page: Any) -> str:
    """화면에 보이는 글자(불가능하면 HTML 원문)."""
    getter = getattr(page, "inner_text", None)
    if getter is not None:
        try:
            return str(getter("body"))
        except Exception:  # noqa: BLE001 - body 가 아직 없을 수 있다
            pass
    try:
        return str(page.content())
    except Exception as exc:  # noqa: BLE001
        raise StepError(f"화면 내용을 읽을 수 없습니다: {exc}") from exc


def is_visible(page: Any, selector: str) -> bool:
    try:
        return bool(page.is_visible(selector))
    except Exception:  # noqa: BLE001 - 요소가 없으면 예외를 던지는 구현도 있다
        return False


def evaluate_match(page: Any, match: Match) -> tuple[bool, str]:
    """판정 조건을 검사하고 (통과 여부, 이유) 를 돌려준다."""
    if match.is_empty:
        return False, "판정 조건 없음"

    text = page_text(page) if (match.text_contains or match.text_missing) else ""

    for needle in match.text_contains:
        if needle not in text:
            return False, f"'{needle}' 문구가 화면에 없습니다"
    for needle in match.text_missing:
        if needle in text:
            return False, f"'{needle}' 문구가 화면에 남아 있습니다"
    for selector in match.visible:
        if not is_visible(page, selector):
            return False, f"{selector} 가 보이지 않습니다"
    for selector in match.hidden:
        if is_visible(page, selector):
            return False, f"{selector} 가 아직 보입니다"

    reasons = [
        *[f"'{needle}' 확인" for needle in match.text_contains],
        *[f"'{needle}' 사라짐" for needle in match.text_missing],
        *[f"{selector} 보임" for selector in match.visible],
        *[f"{selector} 숨겨짐" for selector in match.hidden],
    ]
    return True, ", ".join(reasons)


def take_screenshot(page: Any, context: StepContext, name: str) -> Path | None:
    """화면을 파일로 남긴다. 실패해도 예약 흐름을 막지 않는다."""
    if context.config.screenshot == "never":
        return None
    safe = "".join(char if char.isalnum() or char in "-_." else "_" for char in name)
    directory = Path(context.config.out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{safe}.png"
    try:
        page.screenshot(path=str(path))
    except Exception as exc:  # noqa: BLE001 - 진단용이므로 실패를 삼킨다
        log.warning("화면 저장 실패(%s): %s", path, exc)
        return None
    context.screenshots.append(path)
    return path


def run_step(page: Any, step: Step, context: StepContext, where: str) -> None:
    """단계 하나를 실행한다."""
    timeout = step.timeout_ms or context.config.step_timeout_ms
    selector = context.resolve(step.selector, where) if step.selector else ""
    value = context.resolve(step.value, where) if step.value else ""
    action = step.action

    if step.commit and context.dry_run:
        context.performed.append(f"[모의] {step.describe()} — 실제로 누르지 않음")
        log.info("모의 실행: %s 단계를 건너뜁니다.", step.describe())
        return

    if action == "goto":
        page.goto(context.absolute(value), timeout=context.config.nav_timeout_ms)
    elif action == "fill":
        page.fill(selector, value, timeout=timeout)
    elif action == "click":
        page.click(selector, timeout=timeout)
    elif action == "select":
        page.select_option(selector, value, timeout=timeout)
    elif action == "check":
        page.check(selector, timeout=timeout)
    elif action == "uncheck":
        page.uncheck(selector, timeout=timeout)
    elif action == "press":
        page.press(selector, value, timeout=timeout)
    elif action == "wait_for":
        page.wait_for_selector(selector, timeout=timeout)
    elif action == "wait_ms":
        page.wait_for_timeout(int(float(value)))
    elif action == "accept_dialog":
        accept = value.lower() not in {"false", "0", "no", "off"}
        page.once("dialog", lambda dialog: dialog.accept() if accept else dialog.dismiss())
    elif action == "screenshot":
        take_screenshot(page, context, f"{context.tag}-{value}" if context.tag else value)
    elif action == "expect_text":
        if value not in page_text(page):
            raise StepError(f"{where}: 화면에 '{value}' 문구가 없습니다.")
    else:  # pragma: no cover - scenario.Step.parse 가 먼저 막는다
        raise StepError(f"{where}: 처리할 수 없는 액션 {action!r}")

    context.performed.append(step.describe())


def run_steps(page: Any, steps: tuple[Step, ...], context: StepContext, where: str) -> None:
    """단계 목록을 순서대로 실행한다. optional 단계는 실패해도 넘어간다."""
    for index, step in enumerate(steps):
        location = f"{where}.steps[{index}]"
        try:
            run_step(page, step, context, location)
        except StepError:
            if step.optional:
                context.performed.append(f"[건너뜀] {step.describe()}")
                continue
            raise
        except Exception as exc:  # noqa: BLE001 - Playwright 예외를 한국어로 감싼다
            if step.optional:
                context.performed.append(f"[건너뜀] {step.describe()} ({type(exc).__name__})")
                log.debug("선택 단계 실패(무시): %s — %s", location, exc)
                continue
            raise StepError(f"{location}: {step.describe()} 실패 — {type(exc).__name__}: {exc}") from exc
