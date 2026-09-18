"""시나리오 문자열 안의 {{ ... }} 자리표시자를 채운다.

별도 템플릿 엔진을 쓰지 않는다. 예약 시나리오에 필요한 것은
`{{ env.BOOKING_USER }}`, `{{ target.date }}` 같은 단순 치환뿐이고,
조건문·반복문을 허용하면 시나리오가 읽기 어려워진다.
"""

from __future__ import annotations

import re
from typing import Any

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][\w]*(?:\.[\w]+)*)\s*\}\}")


class TemplateError(ValueError):
    """자리표시자를 채울 값이 없을 때."""


def _lookup(path: str, context: dict[str, Any]) -> str:
    current: Any = context
    walked: list[str] = []
    for part in path.split("."):
        walked.append(part)
        if not isinstance(current, dict) or part not in current:
            where = ".".join(walked)
            if walked[0] == "env" and len(walked) == 2:
                raise TemplateError(
                    f"환경변수 {walked[1]} 가 비어 있습니다. "
                    f"(.env 또는 GitHub Secrets 에 {walked[1]} 를 넣어 주세요)"
                )
            raise TemplateError(f"시나리오에서 참조한 {{{{ {path} }}}} 값을 찾을 수 없습니다 ({where}).")
        current = current[part]
    if isinstance(current, dict):
        raise TemplateError(f"{{{{ {path} }}}} 는 값이 아니라 하위 항목을 가진 묶음입니다.")
    return str(current)


def render(template: str, context: dict[str, Any]) -> str:
    """문자열 안의 `{{ 경로 }}` 를 context 값으로 바꾼다."""
    if not template or "{{" not in template:
        return template
    return PLACEHOLDER.sub(lambda m: _lookup(m.group(1), context), template)


def referenced_names(template: str) -> list[str]:
    """문자열이 참조하는 자리표시자 경로 목록(검증·진단용)."""
    return PLACEHOLDER.findall(template or "")
