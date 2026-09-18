"""Playwright Page 를 흉내 내는 가짜 페이지.

브라우저 없이 시나리오 실행 흐름 전체를 검증하기 위한 것으로,
`steps.py` 가 실제로 부르는 메서드만 갖추고 있다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable


class FakeTimeout(RuntimeError):
    """Playwright TimeoutError 대용."""


class FakeDialog:
    def __init__(self) -> None:
        self.accepted = False
        self.dismissed = False

    def accept(self) -> None:
        self.accepted = True

    def dismiss(self) -> None:
        self.dismissed = True


class FakePage:
    """클릭에 반응해 화면 상태가 바뀌는 가짜 페이지."""

    def __init__(
        self,
        text: str = "",
        visible: tuple[str, ...] = (),
        on_click: dict[str, Callable[["FakePage"], None]] | None = None,
        fail_on: dict[str, str] | None = None,
    ) -> None:
        self.text = text
        self.visible: set[str] = set(visible)
        self.on_click = on_click or {}
        self.fail_on = fail_on or {}
        self.actions: list[tuple[str, str, str]] = []
        self.url = ""
        self.dialog_handlers: list[Callable[[FakeDialog], None]] = []
        self.screenshots: list[Path] = []
        self.evaluate_result: dict = {}

    # -- 기록 도우미 -----------------------------------------------------
    def _record(self, action: str, selector: str = "", value: str = "") -> None:
        if selector in self.fail_on:
            raise FakeTimeout(self.fail_on[selector])
        self.actions.append((action, selector, value))

    @property
    def clicked(self) -> list[str]:
        return [selector for action, selector, _ in self.actions if action == "click"]

    @property
    def filled(self) -> dict[str, str]:
        return {selector: value for action, selector, value in self.actions if action == "fill"}

    # -- Playwright 흉내 -------------------------------------------------
    def goto(self, url: str, **_: object) -> None:
        self._record("goto", url)
        self.url = url

    def fill(self, selector: str, value: str, **_: object) -> None:
        self._record("fill", selector, value)

    def click(self, selector: str, **_: object) -> None:
        self._record("click", selector)
        handler = self.on_click.get(selector)
        if handler is not None:
            handler(self)

    def select_option(self, selector: str, value: str, **_: object) -> None:
        self._record("select", selector, value)

    def check(self, selector: str, **_: object) -> None:
        self._record("check", selector)

    def uncheck(self, selector: str, **_: object) -> None:
        self._record("uncheck", selector)

    def press(self, selector: str, key: str, **_: object) -> None:
        self._record("press", selector, key)

    def wait_for_selector(self, selector: str, **_: object) -> None:
        self._record("wait_for", selector)
        if selector not in self.visible:
            raise FakeTimeout(f"{selector} 를 찾지 못했습니다")

    def wait_for_timeout(self, milliseconds: int) -> None:
        self._record("wait_ms", "", str(milliseconds))

    def wait_for_load_state(self, state: str = "load", **_: object) -> None:
        self._record("load_state", state)

    def evaluate(self, script: str, *_args: object) -> dict:
        self._record("evaluate")
        return self.evaluate_result

    def once(self, event: str, handler: Callable[[FakeDialog], None]) -> None:
        self._record("once", event)
        if event == "dialog":
            self.dialog_handlers.append(handler)

    def fire_dialog(self) -> FakeDialog:
        dialog = FakeDialog()
        if self.dialog_handlers:
            self.dialog_handlers.pop(0)(dialog)
        return dialog

    def is_visible(self, selector: str) -> bool:
        return selector in self.visible

    def inner_text(self, selector: str) -> str:
        if selector != "body":
            raise FakeTimeout(selector)
        return self.text

    def content(self) -> str:
        return f"<html><body>{self.text}</body></html>"

    def screenshot(self, path: str, **_: object) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fake-png")
        self.screenshots.append(target)


class FakeClock:
    """자는 만큼 실제로 시간이 흐르는 가짜 시계."""

    def __init__(self, start):
        self.now = start
        self.slept: list[float] = []

    def __call__(self):
        return self.now

    def sleep(self, seconds: float) -> None:
        from datetime import timedelta

        self.slept.append(seconds)
        self.now = self.now + timedelta(seconds=seconds)

    @property
    def total_slept(self) -> float:
        return sum(self.slept)
