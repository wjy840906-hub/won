"""Playwright 브라우저를 띄우고 페이지를 넘겨준다.

playwright 는 여기서만 import 한다. 시나리오 검증·후보 확인 같은 작업은
브라우저 없이도 돌아야 하고, 테스트도 playwright 없이 통과해야 한다.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import BookingConfig

log = logging.getLogger(__name__)

INSTALL_HINT = (
    "Playwright 가 없습니다. 아래를 실행하세요:\n"
    "  pip install playwright\n"
    "  python -m playwright install chromium"
)


class BrowserError(RuntimeError):
    """브라우저를 띄우지 못했을 때."""


@contextmanager
def open_page(config: BookingConfig) -> Iterator[Any]:
    """브라우저를 띄우고 페이지를 넘긴 뒤, 끝나면 정리한다.

    `state_file` 을 지정하면 로그인 쿠키를 저장/복원해 다음 실행에서
    로그인 단계를 건너뛸 수 있다(사이트가 세션을 유지하는 경우).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - 설치 여부에 따라 갈린다
        raise BrowserError(INSTALL_HINT) from exc

    state_path = Path(config.state_file) if config.state_file else None
    launch_options: dict[str, Any] = {"headless": config.headless}
    if config.slow_mo_ms:
        launch_options["slow_mo"] = config.slow_mo_ms
    if config.executable_path:
        launch_options["executable_path"] = config.executable_path

    context_options: dict[str, Any] = {}
    if config.user_agent:
        context_options["user_agent"] = config.user_agent
    if state_path and state_path.exists():
        context_options["storage_state"] = str(state_path)
        log.info("저장된 로그인 세션을 불러옵니다: %s", state_path)

    with sync_playwright() as playwright:
        try:
            browser = getattr(playwright, config.browser).launch(**launch_options)
        except Exception as exc:  # noqa: BLE001
            raise BrowserError(f"{config.browser} 를 띄우지 못했습니다 — {exc}\n{INSTALL_HINT}") from exc

        context = browser.new_context(**context_options)
        context.set_default_timeout(config.step_timeout_ms)
        context.set_default_navigation_timeout(config.nav_timeout_ms)
        page = context.new_page()
        try:
            yield page
        finally:
            if state_path:
                try:
                    state_path.parent.mkdir(parents=True, exist_ok=True)
                    context.storage_state(path=str(state_path))
                except Exception as exc:  # noqa: BLE001 - 저장 실패가 결과를 뒤집지 않도록
                    log.warning("로그인 세션 저장 실패(%s): %s", state_path, exc)
            context.close()
            browser.close()
