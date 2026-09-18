"""Claude API(Anthropic Messages) 호출 래퍼.

장문 생성은 스트리밍으로 받는다(응답이 길어 HTTP 타임아웃에 걸리는 것을 막는다).
기획처럼 형식이 정해진 응답은 structured outputs(JSON 스키마)로 받아 파싱 실패를 없앤다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# 1M 토큰당 (입력, 출력) 달러 단가. 비용 안내용이라 표에 없는 모델은 0 으로 둔다.
PRICING_USD = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


class ClaudeError(RuntimeError):
    """Claude API 호출 실패."""


@dataclass
class Usage:
    """토큰 사용량 누적."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0

    def add(self, usage: object) -> None:
        self.calls += 1
        self.input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
        self.output_tokens += int(getattr(usage, "output_tokens", 0) or 0)
        self.cache_read_tokens += int(getattr(usage, "cache_read_input_tokens", 0) or 0)

    def cost_usd(self, model: str) -> float:
        """대략적인 비용(달러). 단가를 모르는 모델이면 0."""
        price_in, price_out = PRICING_USD.get(model, (0.0, 0.0))
        return (self.input_tokens * price_in + self.output_tokens * price_out) / 1_000_000

    def summary(self, model: str) -> str:
        cost = self.cost_usd(model)
        text = (
            f"호출 {self.calls}회 / 입력 {self.input_tokens:,} 토큰 / 출력 {self.output_tokens:,} 토큰"
        )
        return text + (f" / 약 ${cost:.2f}" if cost else "")


def _text_of(message: object) -> str:
    """응답에서 text 블록만 이어 붙인다(thinking 블록은 버린다)."""
    parts = []
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", "") == "text":
            parts.append(getattr(block, "text", ""))
    return "".join(parts).strip()


def _check_stop(message: object, what: str) -> None:
    """거절·길이 초과를 사람이 읽을 수 있는 오류로 바꾼다."""
    stop_reason = getattr(message, "stop_reason", "")
    if stop_reason == "refusal":
        details = getattr(message, "stop_details", None)
        category = getattr(details, "category", "") or "미상"
        raise ClaudeError(
            f"모델이 {what} 생성을 거절했습니다(사유: {category}). 소재나 요구사항을 조정해 보세요."
        )
    if stop_reason == "max_tokens":
        log.warning("%s 응답이 max_tokens 에서 잘렸습니다. 장당 분량을 줄이거나 장 수를 늘리세요.", what)


class ClaudeClient:
    """Claude 호출에 필요한 것만 감싼 얇은 래퍼."""

    def __init__(
        self,
        api_key: str,
        model: str,
        effort: str = "high",
        timeout: int = 900,
        max_retries: int = 4,
    ) -> None:
        self.model = model
        self.effort = effort
        self.usage = Usage()
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - 설치 안내
            raise ClaudeError(
                "anthropic 패키지가 없습니다. pip install -r requirements.txt 를 실행하세요."
            ) from exc
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(
            api_key=api_key or None, timeout=timeout, max_retries=max_retries
        )

    # -- 내부 ---------------------------------------------------------------

    def _fail(self, exc: Exception, what: str) -> ClaudeError:
        anthropic = self._anthropic
        if isinstance(exc, anthropic.AuthenticationError):
            return ClaudeError(f"{what} 실패: ANTHROPIC_API_KEY 가 올바르지 않습니다.")
        if isinstance(exc, anthropic.RateLimitError):
            return ClaudeError(f"{what} 실패: 요청 한도를 초과했습니다. 잠시 뒤 다시 실행하세요.")
        if isinstance(exc, anthropic.APIStatusError):
            return ClaudeError(f"{what} 실패({exc.status_code}): {exc.message}")
        if isinstance(exc, anthropic.APIConnectionError):
            return ClaudeError(f"{what} 실패: 네트워크 오류입니다. 연결을 확인하세요.")
        return ClaudeError(f"{what} 실패: {exc}")

    # -- 공개 API -----------------------------------------------------------

    def write(
        self,
        system: str,
        prompt: str,
        what: str = "본문",
        max_tokens: int = 32000,
        effort: str = "",
    ) -> str:
        """긴 산문을 스트리밍으로 받아 문자열로 돌려준다."""
        try:
            with self._client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                thinking={"type": "adaptive"},
                output_config={"effort": effort or self.effort},
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                message = stream.get_final_message()
        except Exception as exc:  # SDK 예외를 한국어 메시지로 바꾼다
            raise self._fail(exc, what) from exc

        self.usage.add(getattr(message, "usage", None))
        _check_stop(message, what)
        text = _text_of(message)
        if not text:
            raise ClaudeError(f"{what} 응답이 비어 있습니다.")
        return text

    def json(
        self,
        system: str,
        prompt: str,
        schema: dict,
        what: str = "기획",
        max_tokens: int = 16000,
        effort: str = "",
    ) -> dict:
        """JSON 스키마에 맞춘 응답을 dict 로 돌려준다."""
        try:
            message = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                thinking={"type": "adaptive"},
                output_config={
                    "effort": effort or self.effort,
                    "format": {"type": "json_schema", "schema": schema},
                },
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            raise self._fail(exc, what) from exc

        self.usage.add(getattr(message, "usage", None))
        _check_stop(message, what)
        text = _text_of(message)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ClaudeError(f"{what} 응답을 JSON 으로 읽지 못했습니다: {exc}") from exc
