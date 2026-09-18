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

  return {
    title: clean(document.title),
    url: location.href,
    inputs, selects, buttons, forms, iframes,
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

    draft = draft_login_steps(data)
    if draft:
        lines.append(_section("로그인 단계 초안 — 시나리오에 붙여 넣고 확인하세요"))
        lines.extend(f"  {line}" for line in draft)

    return "\n".join(lines)


def probe_url(page: Any, url: str, config: BookingConfig) -> str:
    """URL 을 열어 화면 구조를 뜯어보고, HTML·화면을 파일로 남긴다."""
    page.goto(url, timeout=config.nav_timeout_ms)
    try:
        page.wait_for_load_state("networkidle", timeout=config.step_timeout_ms)
    except Exception:  # noqa: BLE001 - 계속 통신하는 화면이면 그냥 넘어간다
        log.debug("networkidle 대기를 건너뜁니다.")

    data = page.evaluate(EXTRACT_JS)
    report = format_report(data)

    directory = Path(config.out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stem = "probe-" + re.sub(r"[^A-Za-z0-9]+", "_", urlparse(url).netloc or "page")
    html_path = directory / f"{stem}.html"
    try:
        html_path.write_text(page.content(), encoding="utf-8")
        report += f"\n\n  (HTML 저장: {html_path})"
    except Exception as exc:  # noqa: BLE001
        log.warning("HTML 저장 실패: %s", exc)
    try:
        page.screenshot(path=str(directory / f"{stem}.png"), full_page=True)
        report += f"\n  (화면 저장: {directory / f'{stem}.png'})"
    except Exception as exc:  # noqa: BLE001
        log.warning("화면 저장 실패: %s", exc)

    return report
