"""예약 사이트 화면 구조 진단 도구.

시나리오를 쓰려면 "어떤 입력칸과 버튼이 있고 셀렉터가 무엇인지"를 알아야 한다.
개발자도구로 하나씩 찾는 대신, 페이지를 열어 누를 수 있는 것들을 모아
셀렉터 후보와 시나리오 초안까지 뽑아 준다.

    python -m booking_macro --probe https://example.com/login
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import BookingConfig

log = logging.getLogger(__name__)

# CSS 에서 #id 로 바로 쓸 수 있는 형태인지
SAFE_ID = re.compile(r"[A-Za-z_][\w\-]*")

# 아이디 입력칸으로 보이는 이름들
USER_HINTS = ("id", "user", "login", "mbr", "member", "account", "email")
PASSWORD_HINTS = ("pw", "pass", "secret")

EXTRACT_JS = """
() => {
  const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim().slice(0, 80);
  const seen = (el) => {
    const r = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return r.width > 0 && r.height > 0 && style.visibility !== 'hidden';
  };
  const base = (el) => ({
    tag: el.tagName.toLowerCase(),
    type: clean(el.getAttribute('type')),
    id: clean(el.id),
    name: clean(el.getAttribute('name')),
    cls: clean(el.getAttribute('class')),
    placeholder: clean(el.getAttribute('placeholder')),
    label: clean(el.getAttribute('aria-label') || el.getAttribute('title')),
    text: clean(el.innerText || el.textContent),
    visible: seen(el),
  });

  const inputs = [...document.querySelectorAll('input, textarea')]
    .filter((el) => !['hidden'].includes((el.getAttribute('type') || '').toLowerCase()))
    .map(base);

  const selects = [...document.querySelectorAll('select')].map((el) => ({
    ...base(el),
    options: [...el.options].slice(0, 15).map((o) => clean(o.textContent)),
    optionCount: el.options.length,
  }));

  const buttons = [...document.querySelectorAll(
    'button, a, input[type=submit], input[type=button], [role=button]'
  )].map(base).filter((el) => el.text || el.id || el.name);

  const forms = [...document.querySelectorAll('form')].map((el) => ({
    id: clean(el.id),
    name: clean(el.getAttribute('name')),
    action: clean(el.getAttribute('action')),
    method: clean(el.getAttribute('method')) || 'get',
    fields: [...el.elements].map((f) => clean(f.getAttribute('name'))).filter(Boolean),
  }));

  const iframes = [...document.querySelectorAll('iframe, frame')].map((el) => ({
    id: clean(el.id),
    name: clean(el.getAttribute('name')),
    src: clean(el.getAttribute('src')),
  }));

  // 예약 표의 뼈대. click_cell 에 쓸 열 이름(colspan 포함)과 행 이름을 본다.
  const tables = [...document.querySelectorAll('table')].slice(0, 6).map((table) => {
    const rows = [...table.rows];
    return {
      id: clean(table.id),
      cls: clean(table.getAttribute('class')),
      rowCount: rows.length,
      header: rows.slice(0, 3).map((line) =>
        [...line.cells].map((cell) => ({ text: clean(cell.innerText), span: cell.colSpan || 1 }))
      ),
      // 행마다 어떤 값들이 있는지(중복 제거). click_cell 의 row 에 뭘 적어야
      // 하는지 바로 보이도록 — 시간표라면 ['×', '06:00~07:00'] 처럼 나온다.
      rowSamples: rows.slice(0, 30).map((line) => {
        const 값 = [...new Set([...line.cells].map((cell) => clean(cell.innerText)))];
        return 값.filter(Boolean).slice(0, 4);
      }).filter((값) => 값.length),
      pressable: table.querySelectorAll(
        'a, button, input:not([type=hidden]), select, [onclick]'
      ).length,
    };
  });

  return {
    title: clean(document.title),
    url: location.href,
    inputs, selects, buttons, forms, iframes, tables,
    textSample: clean(document.body ? document.body.innerText : '').slice(0, 300),
  };
}
"""


def suggest_selector(item: dict[str, Any], *, prefer_text: bool = False) -> str:
    """이 요소를 시나리오에서 가리킬 때 쓸 만한 셀렉터."""
    element_id = item.get("id") or ""
    name = item.get("name") or ""
    text = item.get("text") or ""
    classes = [part for part in (item.get("cls") or "").split() if part]

    if prefer_text and text and len(text) <= 20:
        return f"text={text}"
    if element_id and SAFE_ID.fullmatch(element_id):
        return f"#{element_id}"
    if name:
        return f"[name=\"{name}\"]"
    if text and len(text) <= 20:
        return f"text={text}"
    if classes:
        return item.get("tag", "") + "".join(f".{part}" for part in classes[:2])
    return item.get("tag", "") or "(셀렉터를 찾기 어려움)"


def _looks_like(item: dict[str, Any], hints: tuple[str, ...]) -> bool:
    haystack = " ".join(
        str(item.get(key, "")) for key in ("id", "name", "placeholder", "label")
    ).lower()
    return any(hint in haystack for hint in hints)


def draft_login_steps(data: dict[str, Any]) -> list[str]:
    """화면에서 찾은 것들로 로그인 단계 초안을 만든다(그대로 믿지 말고 확인할 것)."""
    inputs = [item for item in data.get("inputs", []) if item.get("visible")]
    password = next(
        (item for item in inputs if item.get("type") == "password"),
        next((item for item in inputs if _looks_like(item, PASSWORD_HINTS)), None),
    )
    if password is None:
        return []

    before_password = inputs[: inputs.index(password)]
    user = next(
        (item for item in reversed(before_password) if _looks_like(item, USER_HINTS)),
        before_password[-1] if before_password else None,
    )

    submit = next(
        (
            item
            for item in data.get("buttons", [])
            if item.get("visible")
            and (
                item.get("type") == "submit"
                or any(word in (item.get("text") or "") for word in ("로그인", "확인", "Login"))
            )
        ),
        None,
    )

    lines = ["login:", f"  url: {urlparse(data.get('url', '')).path or '/'}", "  steps:"]
    if user is not None:
        lines += [f"    - fill: \"{suggest_selector(user)}\"", "      value: \"{{ env.BOOKING_USER }}\""]
    lines += [
        f"    - fill: \"{suggest_selector(password)}\"",
        "      value: \"{{ env.BOOKING_PASSWORD }}\"",
    ]
    if submit is not None:
        lines.append(f"    - click: \"{suggest_selector(submit)}\"")
    lines += [
        "  success_when:",
        "    text_missing: \"로그인\"        # ← 로그인 후 사라지는 문구로 바꾸세요",
    ]
    return lines


class ProbeError(RuntimeError):
    """진단할 화면을 열지 못했을 때."""


def _has_content(page: Any) -> bool:
    """뭐라도 그려졌는지(빈 about:blank 가 아닌지)."""
    try:
        return len((page.content() or "").strip()) > 200
    except Exception:  # noqa: BLE001
        return False


def _접속_실패_안내(url: str, exc: Exception) -> str:
    return (
        f"{url} 을(를) 열지 못했습니다 — {type(exc).__name__}: {exc}\n"
        "  짚어 볼 것:\n"
        "  1) 이 사이트가 해외 IP 를 막고 있을 수 있습니다. 공공기관 사이트에 흔합니다.\n"
        "     GitHub Actions 러너는 해외에 있으므로, 이 경우 국내에서 직접 돌려야 합니다.\n"
        "  2) 사이트가 느린 것이라면 시간을 늘려 보세요: BOOKING_PROBE_TIMEOUT_MS=120000\n"
        "  3) load 가 끝나지 않는 화면이면: BOOKING_WAIT_UNTIL=commit"
    )


def _save_screenshot(page: Any, path: Path, config: BookingConfig) -> bool:
    """화면을 남긴다. 전체 화면이 안 되면 보이는 부분만이라도 남긴다.

    full_page 는 Chromium 이 로딩이 끝나기를 기다리므로, 끝나지 않는 화면에서는
    그대로 멈춘다. 진단이 목적이니 절반이라도 건지는 편이 낫다.
    """
    timeout = min(config.step_timeout_ms, SETTLE_MS)
    # 로딩이 끝나지 않으면 Chromium 이 화면을 찍어 주지 않는다. 필요한 내용은
    # 이미 읽어 둔 뒤이므로, 남은 요청을 끊고 지금 보이는 대로 찍는다.
    try:
        page.evaluate("() => window.stop()")
    except Exception as exc:  # noqa: BLE001
        log.debug("로딩 중단 실패: %s", exc)
    for 전체화면 in (True, False):
        try:
            page.screenshot(path=str(path), full_page=전체화면, timeout=timeout)
            return True
        except Exception as exc:  # noqa: BLE001 - 진단용이라 실패해도 계속 간다
            log.debug("화면 저장 실패(full_page=%s): %s", 전체화면, exc)
    log.warning("화면을 저장하지 못했습니다: %s", path)
    return False


def _current_url(page: Any) -> str:
    try:
        return str(page.url)
    except Exception:  # noqa: BLE001
        return "(주소를 읽지 못함)"


def _section(title: str) -> str:
    return f"\n{'=' * 78}\n{title}\n{'=' * 78}"


def format_report(data: dict[str, Any]) -> str:
    """진단 결과를 사람이 읽을 수 있는 형태로 만든다."""
    lines: list[str] = []
    lines.append(_section("페이지"))
    lines.append(f"  제목: {data.get('title') or '(없음)'}")
    lines.append(f"  주소: {data.get('url') or '(없음)'}")
    if data.get("textSample"):
        lines.append(f"  화면 글자: {data['textSample']}")

    iframes = data.get("iframes") or []
    if iframes:
        lines.append(_section(f"iframe {len(iframes)}개 — 예약 화면이 이 안에 있을 수 있습니다"))
        for frame in iframes:
            이름 = frame.get("id") or frame.get("name") or "(이름 없음)"
            lines.append(f"  {이름:<24} src={frame.get('src') or '(없음)'}")
        lines.append("  ※ iframe 안의 요소는 지금 시나리오 문법으로 다룰 수 없습니다.")
        lines.append("     src 주소로 직접 접속되는지 먼저 확인해 보세요.")

    inputs = [item for item in (data.get("inputs") or []) if item.get("visible")]
    lines.append(_section(f"입력칸 {len(inputs)}개"))
    if not inputs:
        lines.append("  (없음 — 로그인 화면이 아니거나 iframe 안에 있을 수 있습니다)")
    for item in inputs:
        설명 = item.get("placeholder") or item.get("label") or item.get("name") or ""
        종류 = item.get("type") or item.get("tag")
        lines.append(f"  {suggest_selector(item):<34} {종류:<10} {설명}")

    selects = [item for item in (data.get("selects") or []) if item.get("visible")]
    if selects:
        lines.append(_section(f"선택 상자 {len(selects)}개"))
        for item in selects:
            보기 = " / ".join(item.get("options", [])[:8])
            더 = f" … (전체 {item.get('optionCount')}개)" if item.get("optionCount", 0) > 8 else ""
            lines.append(f"  {suggest_selector(item):<34} {보기}{더}")

    buttons = [item for item in (data.get("buttons") or []) if item.get("visible") and item.get("text")]
    lines.append(_section(f"버튼·링크 {len(buttons)}개"))
    for item in buttons[:60]:
        lines.append(f"  {suggest_selector(item):<34} '{item.get('text')}'")
    if len(buttons) > 60:
        lines.append(f"  … 그 외 {len(buttons) - 60}개")

    forms = data.get("forms") or []
    if forms:
        lines.append(_section(f"form {len(forms)}개"))
        for form in forms:
            이름 = form.get("id") or form.get("name") or "(이름 없음)"
            lines.append(f"  {이름:<24} {form.get('method', 'get').upper()} {form.get('action') or '(현재 주소)'}")
            if form.get("fields"):
                lines.append(f"    보내는 값: {', '.join(form['fields'][:20])}")

    tables = [item for item in (data.get("tables") or []) if item.get("rowCount", 0) > 1]
    if tables:
        lines.append(_section(f"표 {len(tables)}개 — click_cell 에 쓸 이름"))
        for index, table in enumerate(tables, start=1):
            이름 = table.get("id") or table.get("cls") or f"{index}번째 표"
            lines.append(
                f"  [{이름}] {table.get('rowCount')}행 · 누를 수 있는 것 {table.get('pressable')}개"
            )
            for 줄 in table.get("header") or []:
                조각 = [
                    f"{cell['text'] or '(빈칸)'}" + (f"×{cell['span']}" if cell.get("span", 1) > 1 else "")
                    for cell in 줄
                ]
                if 조각:
                    lines.append("    열: " + " | ".join(조각[:14]))
            for 값 in (table.get("rowSamples") or [])[:8]:
                lines.append("    행: " + " / ".join(값))
        lines.append("    → click_cell 의 column 에는 '열', row 에는 '행' 이름을 그대로 적으세요.")

    draft = draft_login_steps(data)
    if draft:
        lines.append(_section("로그인 단계 초안 — 시나리오에 붙여 넣고 확인하세요"))
        lines.extend(f"  {line}" for line in draft)

    return "\n".join(lines)


# 통신이 잦아들기를 기다리는 시간. 추적 스크립트가 끝나지 않는 화면이 흔하므로
# 여기서 오래 붙잡지 않는다 — 어차피 그려진 내용만 있으면 진단할 수 있다.
SETTLE_MS = 3000


def _settle(page: Any, config: BookingConfig) -> None:
    """화면이 자리잡을 때까지 잠깐 기다린다(끝나지 않아도 넘어간다)."""
    try:
        page.wait_for_load_state("networkidle", timeout=min(config.step_timeout_ms, SETTLE_MS))
    except Exception:  # noqa: BLE001 - 계속 통신하는 화면이면 그냥 넘어간다
        log.debug("networkidle 대기를 건너뜁니다.")


def probe_url(
    page: Any,
    url: str,
    config: BookingConfig,
    clicks: tuple[str, ...] = (),
) -> str:
    """URL 을 열어 화면 구조를 뜯어보고, HTML·화면을 파일로 남긴다.

    예약 화면이 메뉴 몇 단계 안에 있으면 `clicks` 로 그 경로를 따라간 뒤
    도착한 화면을 뜯어본다(--probe-click). 누르는 것은 이동·조회 뿐이라고
    보고, 예약을 확정하는 버튼은 넣지 말아야 한다.
    """
    덜_불러옴 = ""
    try:
        page.goto(url, timeout=config.probe_timeout_ms, wait_until=config.wait_until)
    except Exception as exc:  # noqa: BLE001 - 느린 사이트라도 그려진 만큼은 진단한다
        if not _has_content(page):
            raise ProbeError(_접속_실패_안내(url, exc)) from exc
        덜_불러옴 = f"{type(exc).__name__} — 화면을 끝까지 불러오지는 못했습니다"
        log.warning("페이지를 끝까지 불러오지 못했지만 그려진 내용으로 진단합니다: %s", exc)
    _settle(page, config)

    걸어온_길: list[str] = []
    for selector in clicks:
        try:
            page.click(selector, timeout=config.step_timeout_ms)
        except Exception as exc:  # noqa: BLE001 - 어디서 끊겼는지 보여 주고 계속 진단
            걸어온_길.append(f"{selector} → 누르지 못함 ({type(exc).__name__})")
            break
        _settle(page, config)
        걸어온_길.append(f"{selector} → {_current_url(page)}")

    data = page.evaluate(EXTRACT_JS)
    report = format_report(data)
    if 덜_불러옴:
        report = _section("주의") + f"\n  {덜_불러옴}\n  (아래 내용이 비어 있으면 시간을 늘려 보세요: BOOKING_PROBE_TIMEOUT_MS=120000)" + report
    if 걸어온_길:
        길 = "\n".join(f"  {index}. {걸음}" for index, 걸음 in enumerate(걸어온_길, start=1))
        report = _section("따라간 경로") + "\n" + 길 + report

    directory = Path(config.out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stem = "probe-" + re.sub(r"[^A-Za-z0-9]+", "_", urlparse(url).netloc or "page")
    if clicks:
        stem += f"-{len(clicks)}단계"
    html_path = directory / f"{stem}.html"
    try:
        html_path.write_text(page.content(), encoding="utf-8")
        report += f"\n\n  (HTML 저장: {html_path})"
    except Exception as exc:  # noqa: BLE001
        log.warning("HTML 저장 실패: %s", exc)
    shot_path = directory / f"{stem}.png"
    if _save_screenshot(page, shot_path, config):
        report += f"\n  (화면 저장: {shot_path})"

    return report
