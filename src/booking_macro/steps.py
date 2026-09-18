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


class SlotUnavailable(StepError):
    """칸은 찾았지만 누를 수 있는 것이 없다 — 이미 찼거나 선택할 수 없는 자리.

    코드가 잘못된 것이 아니라 그 자리가 안 되는 것이므로,
    실행기는 이것을 '실패' 가 아니라 '마감' 으로 보고 다음 후보로 넘어간다.
    """


# 예약 표(코트 × 시간)에서 칸을 찾아 표시해 두는 스크립트.
#
# 한국 공공시설 예약 화면은 대개 이런 표를 쓴다.
#
#     |  실외코트4  |  실외코트5  |     ← colspan=2 짜리 시설 헤더
#     | 선택 | 시간 | 선택 | 시간 |
#     |  ×   |06:00~07:00| ○ |06:00~07:00|
#
# 그래서 (1) 헤더에서 colspan 을 세어 그 시설의 열 범위를 구하고,
# (2) 시간 글자가 있는 행을 찾아 (3) 교차 지점에서 누를 수 있는 것을 고른다.
# 실제 클릭은 Playwright 가 해야 하므로, 찾은 요소에 표시만 남기고 돌려준다.
FIND_CELL_JS = """
(args) => {
  const MARK = 'data-booking-cell';
  const norm = (value) => (value || '').replace(/\s+/g, '');
  const column = norm(args.column);
  const row = norm(args.row);
  const contains = (args.contains || []).map(norm).filter(Boolean);
  const exact = (args.exact || []).map(norm).filter(Boolean);

  // '5' 를 찾을 때 '15'·'25' 칸이 걸리지 않도록, 통째로 같은 조각이 있는지 본다.
  // 달력은 <td><span>5</span><span>예약가능</span></td> 처럼 날짜를 따로 담는다.
  const hasExact = (cell, needle) => {
    if (norm(cell.innerText) === needle) return true;
    for (const child of cell.querySelectorAll('*')) {
      if (norm(child.innerText !== undefined ? child.innerText : child.textContent) === needle) return true;
    }
    for (const node of cell.childNodes) {
      if (node.nodeType === 3 && norm(node.textContent) === needle) return true;
    }
    return false;
  };

  document.querySelectorAll('[' + MARK + ']').forEach((el) => el.removeAttribute(MARK));

  // 누를 수 있는 것: 링크·버튼·입력칸·onclick 이 달린 요소. 글자뿐인 칸은 제외된다.
  const pressable = (cell) => {
    if (cell.matches('a, button, input:not([type=hidden]), select, label, [onclick]')) return cell;
    return cell.querySelector('a, button, input:not([type=hidden]), select, label, [onclick]');
  };

  const 후보 = [];
  for (const table of document.querySelectorAll('table')) {
    const rows = [...table.rows];

    // 시설 헤더의 열 범위 (colspan 반영)
    let range = null;
    if (column) {
      for (const header of rows) {
        let at = 0;
        for (const cell of header.cells) {
          const span = cell.colSpan || 1;
          if (norm(cell.innerText) === column) { range = [at, at + span - 1]; break; }
          at += span;
        }
        if (range) break;
      }
      if (!range) continue;  // 이 표에는 그 시설이 없다
    }

    for (const line of rows) {
      if (row && !norm(line.innerText).includes(row)) continue;
      let at = 0;
      for (const cell of line.cells) {
        const span = cell.colSpan || 1;
        const start = at;
        const end = at + span - 1;
        at += span;
        if (range && (end < range[0] || start > range[1])) continue;
        if (range && span > 1) continue;            // 헤더 자신은 건너뛴다
        const text = norm(cell.innerText);
        if (contains.length && !contains.every((needle) => text.includes(needle))) continue;
        if (exact.length && !exact.every((needle) => hasExact(cell, needle))) continue;
        if (!column && !contains.length && !exact.length && !row) continue;
        후보.push(cell);
      }
    }
  }

  for (const cell of 후보) {
    const target = pressable(cell);
    if (target) {
      target.setAttribute(MARK, '1');
      return { found: true, text: (cell.innerText || '').trim().slice(0, 40), matched: 후보.length };
    }
  }
  if (후보.length) {
    return {
      found: false, reason: 'unavailable', matched: 후보.length,
      text: (후보[0].innerText || '').trim().slice(0, 40),
    };
  }
  return { found: false, reason: 'missing', matched: 0 };
}
"""


def click_cell(page: Any, step: Step, context: StepContext, where: str, timeout: int) -> None:
    """표에서 열·행이 만나는 칸을 눌러 준다."""
    조건 = {
        "column": context.resolve(step.column, where),
        "row": context.resolve(step.row, where),
        "contains": [context.resolve(needle, where) for needle in step.contains],
        "exact": [context.resolve(needle, where) for needle in step.exact],
    }
    찾은_것 = " × ".join(
        부분
        for 부분 in (조건["column"], 조건["row"], *조건["exact"], *조건["contains"])
        if 부분
    )

    result = page.evaluate(FIND_CELL_JS, 조건)
    if result.get("found"):
        page.click('[data-booking-cell="1"]', timeout=timeout)
        return

    if result.get("reason") == "unavailable":
        raise SlotUnavailable(
            f"{where}: '{찾은_것}' 칸은 있지만 선택할 수 없습니다"
            f" (표시: {result.get('text') or '비어 있음'}) — 이미 찼거나 예약할 수 없는 자리입니다."
        )
    raise StepError(
        f"{where}: 표에서 '{찾은_것}' 에 해당하는 칸이 없습니다."
        " 그 자리가 화면에 아예 없거나(마감·휴장으로 표시가 바뀐 경우),"
        " 시설 이름·시간 표기가 화면과 다를 수 있습니다(--probe 로 확인하세요)."
    )


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
    elif action == "click_cell":
        click_cell(page, step, context, where, timeout)
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
