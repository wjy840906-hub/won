"""예약 시나리오(YAML/JSON) 로딩과 검증.

사이트마다 다른 것은 "어떤 셀렉터를 어떤 순서로 누르는가" 뿐이므로,
그 부분만 시나리오 파일로 빼고 코드는 공통으로 둔다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .template import referenced_names

# 액션별 설명 — CLI 도움말과 오류 메시지에 그대로 쓴다.
ACTIONS: dict[str, str] = {
    "goto": "주소로 이동 (값: URL)",
    "fill": "입력란 채우기 (셀렉터 + 값)",
    "click": "클릭 (셀렉터)",
    "select": "드롭다운 선택 (셀렉터 + 값)",
    "check": "체크박스 켜기 (셀렉터)",
    "uncheck": "체크박스 끄기 (셀렉터)",
    "press": "키 입력 (셀렉터 + 값, 예: Enter)",
    "wait_for": "요소가 나타날 때까지 대기 (셀렉터)",
    "wait_ms": "고정 시간 대기 (값: 밀리초)",
    "accept_dialog": "다음에 뜨는 confirm/alert 을 확인 (값: true/false)",
    "screenshot": "화면 저장 (값: 파일 이름표)",
    "expect_text": "화면에 이 문구가 있어야 함 (값: 문구)",
}

# 셀렉터를 주 인자로 받는 액션
SELECTOR_ACTIONS = {"fill", "click", "select", "check", "uncheck", "press", "wait_for"}
# 값을 주 인자로 받는 액션
VALUE_ACTIONS = {"goto", "wait_ms", "accept_dialog", "screenshot", "expect_text"}
# 값이 반드시 있어야 하는 액션
VALUE_REQUIRED = {"goto", "fill", "select", "press", "wait_ms", "expect_text"}

STEP_OPTIONS = {"action", "selector", "value", "timeout", "timeout_ms", "commit", "optional", "label"}

MATCH_KEYS = {"text_contains", "text_missing", "visible", "hidden"}


class ScenarioError(ValueError):
    """시나리오 파일이 잘못되었을 때."""


def _as_str_tuple(raw: Any, where: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,) if raw else ()
    if isinstance(raw, (list, tuple)):
        values = []
        for item in raw:
            if not isinstance(item, (str, int, float)):
                raise ScenarioError(f"{where}: 문자열 목록이어야 합니다.")
            values.append(str(item))
        return tuple(values)
    raise ScenarioError(f"{where}: 문자열 또는 문자열 목록이어야 합니다.")


@dataclass(frozen=True)
class Match:
    """화면 상태 판정 조건. 지정한 항목이 모두 맞아야 참."""

    text_contains: tuple[str, ...] = ()
    text_missing: tuple[str, ...] = ()
    visible: tuple[str, ...] = ()
    hidden: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.text_contains or self.text_missing or self.visible or self.hidden)

    @classmethod
    def parse(cls, raw: Any, where: str) -> "Match":
        if raw is None:
            return cls()
        if not isinstance(raw, dict):
            raise ScenarioError(f"{where}: {sorted(MATCH_KEYS)} 를 가진 묶음이어야 합니다.")
        unknown = set(raw) - MATCH_KEYS
        if unknown:
            raise ScenarioError(
                f"{where}: 알 수 없는 항목 {sorted(unknown)} (가능: {sorted(MATCH_KEYS)})"
            )
        return cls(
            text_contains=_as_str_tuple(raw.get("text_contains"), f"{where}.text_contains"),
            text_missing=_as_str_tuple(raw.get("text_missing"), f"{where}.text_missing"),
            visible=_as_str_tuple(raw.get("visible"), f"{where}.visible"),
            hidden=_as_str_tuple(raw.get("hidden"), f"{where}.hidden"),
        )


@dataclass(frozen=True)
class Step:
    """브라우저에서 수행할 동작 한 가지."""

    action: str
    selector: str = ""
    value: str = ""
    timeout_ms: int = 0
    commit: bool = False
    optional: bool = False
    label: str = ""

    def describe(self) -> str:
        if self.label:
            return self.label
        parts = [self.action]
        if self.selector:
            parts.append(self.selector)
        if self.value and self.action != "fill":
            parts.append(f"= {self.value}")
        elif self.value:
            parts.append("= ****")  # 비밀번호가 로그에 남지 않도록
        return " ".join(parts)

    @classmethod
    def parse(cls, raw: Any, where: str) -> "Step":
        if not isinstance(raw, dict):
            raise ScenarioError(f"{where}: 단계는 묶음이어야 합니다. 예: {{click: '#btn'}}")

        action = raw.get("action")
        primary: Any = None
        if action is None:
            found = [key for key in raw if key in ACTIONS]
            if len(found) != 1:
                hint = ", ".join(sorted(ACTIONS))
                raise ScenarioError(
                    f"{where}: 액션을 하나만 적어야 합니다(찾은 것: {found or '없음'}). 가능한 액션: {hint}"
                )
            action = found[0]
            primary = raw[action]
        if action not in ACTIONS:
            raise ScenarioError(f"{where}: 알 수 없는 액션 {action!r}. 가능한 액션: {', '.join(sorted(ACTIONS))}")

        unknown = set(raw) - STEP_OPTIONS - {action}
        if unknown:
            raise ScenarioError(f"{where}: 알 수 없는 항목 {sorted(unknown)}")

        selector = str(raw.get("selector", "") or "")
        value = raw.get("value", None)

        if primary is not None and primary is not True and primary != "":
            if action in SELECTOR_ACTIONS and not selector:
                selector = str(primary)
            elif action in VALUE_ACTIONS and value is None:
                value = primary
        if action == "accept_dialog" and value is None:
            value = primary if primary is not None else True

        value_text = "" if value is None else ("true" if value is True else "false" if value is False else str(value))

        if action in SELECTOR_ACTIONS and not selector:
            raise ScenarioError(f"{where}: {action} 에는 셀렉터가 필요합니다. 예: {{{action}: '#id'}}")
        if action in VALUE_REQUIRED and not value_text:
            raise ScenarioError(f"{where}: {action} 에는 값이 필요합니다 — {ACTIONS[action]}")
        if action == "wait_ms":
            try:
                milliseconds = int(float(value_text))
            except ValueError as exc:
                raise ScenarioError(f"{where}: wait_ms 값이 숫자가 아닙니다: {value_text!r}") from exc
            if milliseconds < 0:
                raise ScenarioError(f"{where}: wait_ms 값은 0 이상이어야 합니다.")

        timeout_raw = raw.get("timeout_ms", raw.get("timeout"))
        timeout_ms = 0
        if timeout_raw is not None:
            try:
                timeout_ms = int(float(timeout_raw))
            except ValueError as exc:
                raise ScenarioError(f"{where}: timeout 값이 숫자가 아닙니다: {timeout_raw!r}") from exc
            if timeout_ms < 0:
                raise ScenarioError(f"{where}: timeout 은 0 이상이어야 합니다.")

        return cls(
            action=action,
            selector=selector,
            value=value_text,
            timeout_ms=timeout_ms,
            commit=bool(raw.get("commit", False)),
            optional=bool(raw.get("optional", False)),
            label=str(raw.get("label", "") or ""),
        )


@dataclass(frozen=True)
class Phase:
    """한 화면 단위의 동작 묶음(로그인, 예약 등)."""

    name: str
    url: str = ""
    steps: tuple[Step, ...] = ()
    success_when: Match = field(default_factory=Match)
    taken_when: Match = field(default_factory=Match)

    @classmethod
    def parse(cls, raw: Any, name: str, *, allow_taken: bool = False) -> "Phase":
        if not isinstance(raw, dict):
            raise ScenarioError(f"{name}: 묶음이어야 합니다.")
        allowed = {"url", "steps", "success_when"} | ({"taken_when"} if allow_taken else set())
        unknown = set(raw) - allowed
        if unknown:
            raise ScenarioError(f"{name}: 알 수 없는 항목 {sorted(unknown)} (가능: {sorted(allowed)})")

        raw_steps = raw.get("steps") or []
        if not isinstance(raw_steps, list):
            raise ScenarioError(f"{name}.steps: 목록이어야 합니다.")
        steps = tuple(
            Step.parse(item, f"{name}.steps[{index}]") for index, item in enumerate(raw_steps)
        )
        if not steps and not raw.get("url"):
            raise ScenarioError(f"{name}: url 또는 steps 중 하나는 있어야 합니다.")

        return cls(
            name=name,
            url=str(raw.get("url", "") or ""),
            steps=steps,
            success_when=Match.parse(raw.get("success_when"), f"{name}.success_when"),
            taken_when=Match.parse(raw.get("taken_when"), f"{name}.taken_when") if allow_taken else Match(),
        )


@dataclass(frozen=True)
class Scenario:
    """예약 시나리오 전체."""

    name: str
    base_url: str
    reserve: Phase
    login: Phase | None = None
    targets: tuple[dict[str, Any], ...] = ()
    open_at: str = ""
    attempts: int = 1
    interval_sec: float = 3.0
    jitter_sec: float = 0.0
    deadline_sec: float = 0.0
    path: Path | None = None

    @property
    def env_names(self) -> list[str]:
        """시나리오가 필요로 하는 환경변수 이름(중복 제거, 등장 순)."""
        names: dict[str, None] = {}
        phases = [phase for phase in (self.login, self.reserve) if phase is not None]
        texts: list[str] = [self.base_url]
        for phase in phases:
            texts.append(phase.url)
            for step in phase.steps:
                texts.extend([step.selector, step.value])
        for target in self.targets:
            for value in target.values():
                texts.extend(value if isinstance(value, list) else [value])
        for text in texts:
            for reference in referenced_names(str(text)):
                if reference.startswith("env."):
                    names.setdefault(reference[4:], None)
        return list(names)


SCENARIO_KEYS = {
    "name",
    "base_url",
    "login",
    "reserve",
    "targets",
    "open_at",
    "attempts",
    "interval_sec",
    "jitter_sec",
    "deadline_sec",
}


def parse_scenario(data: Any, path: Path | None = None) -> Scenario:
    """이미 읽어 들인 자료구조를 Scenario 로 바꾼다."""
    if not isinstance(data, dict):
        raise ScenarioError("시나리오 최상위는 묶음이어야 합니다.")

    unknown = set(data) - SCENARIO_KEYS
    if unknown:
        raise ScenarioError(f"알 수 없는 항목 {sorted(unknown)} (가능: {sorted(SCENARIO_KEYS)})")

    for required in ("name", "base_url", "reserve"):
        if not data.get(required):
            raise ScenarioError(f"{required} 은(는) 반드시 있어야 합니다.")

    raw_targets = data.get("targets") or []
    if not isinstance(raw_targets, list) or not raw_targets:
        raise ScenarioError("targets: 예약하고 싶은 후보를 하나 이상 적어야 합니다(위쪽이 우선순위).")
    targets: list[dict[str, Any]] = []
    for index, item in enumerate(raw_targets):
        if not isinstance(item, dict) or not item:
            raise ScenarioError(f"targets[{index}]: 비어 있지 않은 묶음이어야 합니다. 예: {{date: '+7d', time: '10:00'}}")
        targets.append(dict(item))

    def _number(key: str, default: float) -> float:
        raw = data.get(key)
        if raw is None:
            return default
        try:
            number = float(raw)
        except (TypeError, ValueError) as exc:
            raise ScenarioError(f"{key}: 숫자여야 합니다 ({raw!r}).") from exc
        if number < 0:
            raise ScenarioError(f"{key}: 0 이상이어야 합니다.")
        return number

    attempts = int(_number("attempts", 1))
    if attempts < 1:
        raise ScenarioError("attempts: 1 이상이어야 합니다.")

    return Scenario(
        name=str(data["name"]),
        base_url=str(data["base_url"]).rstrip("/"),
        reserve=Phase.parse(data["reserve"], "reserve", allow_taken=True),
        login=Phase.parse(data["login"], "login") if data.get("login") else None,
        targets=tuple(targets),
        open_at=str(data.get("open_at", "") or ""),
        attempts=attempts,
        interval_sec=_number("interval_sec", 3.0),
        jitter_sec=_number("jitter_sec", 0.0),
        deadline_sec=_number("deadline_sec", 0.0),
        path=path,
    )


def load_scenario(path: str | Path) -> Scenario:
    """YAML(.yaml/.yml) 또는 JSON(.json) 시나리오 파일을 읽는다."""
    path = Path(path)
    if not path.exists():
        raise ScenarioError(f"시나리오 파일이 없습니다: {path}")

    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ScenarioError(f"{path}: JSON 을 읽을 수 없습니다 — {exc}") from exc
    else:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - 의존성 누락 시에만
            raise ScenarioError(
                "YAML 시나리오를 읽으려면 PyYAML 이 필요합니다: pip install PyYAML"
            ) from exc
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ScenarioError(f"{path}: YAML 을 읽을 수 없습니다 — {exc}") from exc

    try:
        return parse_scenario(data, path=path)
    except ScenarioError as exc:
        raise ScenarioError(f"{path}: {exc}") from exc
