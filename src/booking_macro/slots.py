"""예약 후보(날짜·시간·장소)를 실제 값으로 펼친다."""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .scenario import ScenarioError

WEEKDAYS_KO = ("월", "화", "수", "목", "금", "토", "일")

_WEEKDAY_ALIASES: dict[str, int] = {}
for _index, (_ko, _en) in enumerate(
    zip(WEEKDAYS_KO, ("mon", "tue", "wed", "thu", "fri", "sat", "sun"))
):
    _WEEKDAY_ALIASES[_ko] = _index
    _WEEKDAY_ALIASES[f"{_ko}요일"] = _index
    _WEEKDAY_ALIASES[_en] = _index
    _WEEKDAY_ALIASES[_en + "day" if _index < 5 else _en] = _index

_OFFSET = re.compile(r"^([+-])\s*(\d+)\s*([dwDW일주])$")
_ISO = re.compile(r"^(\d{4})[-./](\d{1,2})[-./](\d{1,2})$")
_COMPACT = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


def resolve_date(expr: str, today: date) -> date:
    """날짜 표기를 실제 날짜로 바꾼다.

    허용: '2026-10-01', '20261001', 'today'/'오늘', 'tomorrow'/'내일', '모레',
          '+7d'/'+1w'/'-1d', '월'/'mon'(다음에 오는 그 요일).
    """
    text = (expr or "").strip()
    if not text:
        raise ScenarioError("date 가 비어 있습니다.")

    lowered = text.lower()
    if lowered in {"today", "오늘"}:
        return today
    if lowered in {"tomorrow", "내일"}:
        return today + timedelta(days=1)
    if lowered in {"모레", "day_after_tomorrow"}:
        return today + timedelta(days=2)

    match = _ISO.match(text) or _COMPACT.match(text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        try:
            return date(year, month, day)
        except ValueError as exc:
            raise ScenarioError(f"날짜가 잘못되었습니다: {expr!r} — {exc}") from exc

    match = _OFFSET.match(text)
    if match:
        sign, amount, unit = match.groups()
        days = int(amount) * (7 if unit in {"w", "W", "주"} else 1)
        return today + timedelta(days=days if sign == "+" else -days)

    key = lowered.removeprefix("next ").removeprefix("다음주 ").removeprefix("다음 ").strip()
    if key in _WEEKDAY_ALIASES:
        ahead = (_WEEKDAY_ALIASES[key] - today.weekday()) % 7
        return today + timedelta(days=ahead or 7)

    raise ScenarioError(
        f"날짜 표기를 알 수 없습니다: {expr!r} "
        "(예: 2026-10-01, +7d, +1w, 내일, 월요일)"
    )


@dataclass(frozen=True)
class ResolvedTarget:
    """실제 값으로 확정된 예약 후보 하나.

    `fields` 는 시나리오에서 `{{ target.* }}` 로 쓸 수 있는 전체 값이고
    (날짜는 date_compact·weekday 등 파생 표기까지 들어 있다),
    `summary` 는 사람에게 보여 줄 때 쓰는 요약이다.
    """

    index: int
    fields: dict[str, str] = field(default_factory=dict)
    summary: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return " ".join(part for part in self.summary if part) or f"후보 {self.index}"

    def describe(self) -> str:
        return f"{self.index}순위 · {self.label}"


def _date_fields(value: date) -> dict[str, str]:
    return {
        "date": value.isoformat(),
        "date_compact": value.strftime("%Y%m%d"),
        "date_dot": value.strftime("%Y.%m.%d"),
        "year": f"{value.year:04d}",
        "month": f"{value.month:02d}",
        "day": f"{value.day:02d}",
        "weekday": WEEKDAYS_KO[value.weekday()],
    }


def resolve_targets(raw_targets: tuple[dict[str, Any], ...], today: date) -> list[ResolvedTarget]:
    """시나리오의 targets 를 우선순위 순서의 후보 목록으로 펼친다.

    값에 목록을 쓰면 조합으로 펼쳐지며, 적은 순서가 그대로 우선순위가 된다.
    예: {date: '+7d', time: ['10:00', '14:00']} → 2개 후보.
    """
    resolved: list[ResolvedTarget] = []
    seen: set[tuple[tuple[str, str], ...]] = set()

    for position, target in enumerate(raw_targets):
        keys = list(target)
        choices: list[list[str]] = []
        for key in keys:
            value = target[key]
            values = value if isinstance(value, list) else [value]
            if not values:
                raise ScenarioError(f"targets[{position}].{key}: 값이 비어 있습니다.")
            choices.append([str(item) for item in values])

        for combination in itertools.product(*choices):
            fields: dict[str, str] = {}
            summary: list[str] = []
            for key, value in zip(keys, combination):
                if key == "date":
                    day = resolve_date(value, today)
                    fields.update(_date_fields(day))
                    summary.append(f"{day.isoformat()}({WEEKDAYS_KO[day.weekday()]})")
                else:
                    fields[key] = value
                    summary.append(value)
            signature = tuple(sorted(fields.items()))
            if signature in seen:
                continue
            seen.add(signature)
            resolved.append(
                ResolvedTarget(index=len(resolved) + 1, fields=fields, summary=tuple(summary))
            )

    if not resolved:
        raise ScenarioError("펼쳐진 예약 후보가 없습니다.")
    return resolved
