"""네트워크 없이 도는 소설 매크로 테스트 — Claude 호출은 대역으로 바꾼다."""

import json
from pathlib import Path

import pytest

from novel_writer.claude_client import Usage, _check_stop, _text_of, ClaudeError
from novel_writer.config import Brief, NovelConfig, slugify
from novel_writer.exporter import build_markdown, build_text
from novel_writer.pipeline import build_mail_body, run
from novel_writer.planner import normalize_plan, plan_digest
from novel_writer.prompts import chapter_prompt
from novel_writer.state import NovelState
from novel_writer.writer import max_tokens_for, strip_heading, tail

PLAN = {
    "title": "등대의 계절",
    "logline": "등대를 지키는 소년이 사라진 형의 흔적을 좇는다.",
    "synopsis": "소년은 등대에서 형의 일지를 발견하고 섬의 비밀에 다가간다.",
    "genre": "미스터리",
    "tone": "담백한 문체",
    "pov": "1인칭 주인공",
    "characters": [{"name": "해준", "role": "주인공", "profile": "형을 잃은 열일곱 살"}],
    "settings": [{"name": "무령도", "description": "배가 하루 한 번 드나드는 섬"}],
    "chapters": [
        {"number": 1, "title": "일지", "summary": "형의 일지를 발견한다.", "beats": ["등대 청소", "일지 발견"]},
        {"number": 2, "title": "안개", "summary": "섬 사람들이 입을 닫는다.", "beats": ["이장과의 대화"]},
        {"number": 3, "title": "불빛", "summary": "진실을 마주한다.", "beats": ["등대 점등"]},
    ],
}


class FakeClient:
    """정해진 기획과 본문을 돌려주는 Claude 대역."""

    def __init__(self, plan=None):
        self.plan = json.loads(json.dumps(plan or PLAN))
        self.usage = Usage()
        self.written = []
        self.prompts = []

    def json(self, system, prompt, schema, what="기획", max_tokens=16000, effort=""):
        self.usage.add(None)
        return json.loads(json.dumps(self.plan))

    def write(self, system, prompt, what="본문", max_tokens=32000, effort=""):
        self.usage.add(None)
        self.prompts.append(prompt)
        if what.endswith("요약"):
            return f"- {what} 메모"
        self.written.append(what)
        return f"## {what}\n\n" + ("파도가 등대 아래에서 부서졌다. " * 20)


def _config(tmp_path, **kwargs):
    return NovelConfig(api_key="test", out_dir=str(tmp_path / "out"), chapters=3, **kwargs)


# -- 설정 -------------------------------------------------------------------


def test_slugify_keeps_hangul_and_drops_path_characters():
    assert slugify("등대의 계절") == "등대의-계절"
    assert slugify("a/b:c*d") == "a-b-c-d"
    assert slugify("   ") == "novel"


def test_validate_reports_missing_key_and_bad_numbers():
    problems = NovelConfig(api_key="", chapters=0, chapter_chars=10, effort="turbo").validate()
    assert len(problems) == 4
    assert any("ANTHROPIC_API_KEY" in problem for problem in problems)


def test_brief_lines_skip_empty_fields():
    lines = Brief(idea="등대 소년", genre="미스터리").as_lines()
    assert "- 소재: 등대 소년" in lines
    assert "독자층" not in lines


# -- 기획 -------------------------------------------------------------------


def test_normalize_plan_renumbers_chapters():
    plan = normalize_plan(
        {"title": " 등대 ", "chapters": [{"number": 7, "title": "가", "summary": "", "beats": ["a", " "]}]},
        chapters=1,
    )
    assert plan["title"] == "등대"
    assert plan["chapters"][0]["number"] == 1
    assert plan["chapters"][0]["beats"] == ["a"]


def test_normalize_plan_rejects_empty_chapters():
    with pytest.raises(ClaudeError):
        normalize_plan({"title": "x", "chapters": []}, chapters=3)


def test_plan_digest_contains_characters_and_outline():
    digest = plan_digest(PLAN)
    assert "해준(주인공)" in digest
    assert "3장 「불빛」" in digest


# -- 집필 보조 --------------------------------------------------------------


def test_strip_heading_removes_chapter_title_line():
    assert strip_heading("## 2장 「안개」\n\n본문이다.") == "본문이다."
    assert strip_heading("제 3 장 불빛\n본문") == "본문"
    assert strip_heading("본문만 있다.") == "본문만 있다."


def test_tail_returns_last_characters():
    assert tail("가나다라마", 3) == "다라마"
    assert tail("가나", 5) == "가나"


def test_max_tokens_scales_with_target_length():
    assert max_tokens_for(3000) == 16000
    assert max_tokens_for(100) == 8000
    assert max_tokens_for(50000) == 64000


def test_chapter_prompt_carries_continuity():
    prompt = chapter_prompt(
        plan_digest="기획요약",
        chapter=PLAN["chapters"][1],
        story_so_far="[1장] 일지를 찾았다.",
        previous_tail="…등대 문이 열렸다.",
        chapter_chars=2500,
        total_chapters=3,
        language="한국어",
    )
    assert "기획요약" in prompt
    assert "일지를 찾았다" in prompt
    assert "등대 문이 열렸다" in prompt
    assert "2500자" in prompt
    assert "이장과의 대화" in prompt


def test_chapter_prompt_marks_last_chapter():
    last = chapter_prompt(
        plan_digest="",
        chapter=PLAN["chapters"][2],
        story_so_far="",
        previous_tail="",
        chapter_chars=2000,
        total_chapters=3,
        language="한국어",
    )
    assert "매듭짓는다" in last


# -- 전체 흐름 --------------------------------------------------------------


def test_run_writes_every_chapter_and_manuscript(tmp_path):
    client = FakeClient()
    result = run(_config(tmp_path), Brief(idea="등대 소년"), client=client)

    assert result.finished
    assert result.written == 3
    assert result.title == "등대의 계절"
    assert [path.name for path in result.files] == ["원고.md", "원고.txt"]

    manuscript = result.files[0].read_text(encoding="utf-8")
    assert "# 등대의 계절" in manuscript
    assert "## 1장 일지" in manuscript and "## 3장 불빛" in manuscript
    assert "## 1장 본문" not in manuscript  # 모델이 붙인 제목 줄은 걷어낸다

    for number in (1, 2, 3):
        assert (result.directory / "chapters" / f"{number:02d}.md").exists()
    progress = json.loads((result.directory / "progress.json").read_text(encoding="utf-8"))
    assert [item["number"] for item in progress["chapters"]] == [1, 2, 3]
    assert result.total_chars > 0


def test_last_chapter_skips_summary_call(tmp_path):
    client = FakeClient()
    run(_config(tmp_path), Brief(idea="등대 소년"), client=client)
    # 본문 3회 + 요약 2회(마지막 장은 요약하지 않는다) + 기획 1회
    assert client.usage.calls == 6


def test_batch_then_resume_continues_where_it_stopped(tmp_path):
    first = FakeClient()
    started = run(_config(tmp_path), Brief(idea="등대 소년"), client=first, chapters_limit=1)
    assert started.written == 1 and not started.finished
    assert len(first.written) == 1

    second = FakeClient()
    finished = run(_config(tmp_path), client=second, resume_dir=started.directory)
    assert finished.finished
    assert finished.directory == started.directory
    assert second.written == ["2장 본문", "3장 본문"]  # 1장은 다시 쓰지 않는다


def test_resume_prompt_includes_previous_chapter_tail(tmp_path):
    first = FakeClient()
    started = run(_config(tmp_path), Brief(idea="등대 소년"), client=first, chapters_limit=1)
    first_text = (started.directory / "chapters" / "01.md").read_text(encoding="utf-8")

    second = FakeClient()
    run(_config(tmp_path), client=second, resume_dir=started.directory, chapters_limit=1)
    assert first_text[-50:] in second.prompts[0]
    assert "1장 요약 메모" in second.prompts[0]   # 앞 장 메모가 다음 장 프롬프트로 이어진다


def test_resume_without_plan_fails(tmp_path):
    with pytest.raises(ClaudeError):
        run(_config(tmp_path), client=FakeClient(), resume_dir=tmp_path / "없는폴더")


def test_run_requires_idea(tmp_path):
    with pytest.raises(ClaudeError):
        run(_config(tmp_path), Brief(idea="  "), client=FakeClient())


def test_plan_only_stops_before_writing(tmp_path):
    client = FakeClient()
    result = run(_config(tmp_path), Brief(idea="등대 소년"), client=client, plan_only=True)
    assert result.written == 0
    assert client.written == []
    assert (result.directory / "plan.json").exists()
    assert not (result.directory / "chapters").exists()


def test_work_dir_does_not_overwrite_previous_run(tmp_path):
    config = _config(tmp_path)
    first = run(config, Brief(idea="등대 소년"), client=FakeClient(), plan_only=True)
    second = run(config, Brief(idea="등대 소년"), client=FakeClient(), plan_only=True)
    assert first.directory != second.directory


# -- 원고·메일 --------------------------------------------------------------


def test_exporter_orders_chapters_and_writes_plain_text(tmp_path):
    state = NovelState(directory=tmp_path / "작품")
    state.save_plan(PLAN)
    for chapter in reversed(PLAN["chapters"]):
        state.save_chapter(chapter, f"{chapter['number']}장 본문입니다.")

    markdown = build_markdown(state)
    assert markdown.index("## 1장") < markdown.index("## 2장") < markdown.index("## 3장")
    assert "> 등대를 지키는 소년" in markdown

    text = build_text(state)
    assert text.startswith("등대의 계절")
    assert "#" not in text


def test_mail_body_marks_written_chapters(tmp_path):
    client = FakeClient()
    result = run(_config(tmp_path), Brief(idea="등대 소년"), client=client, chapters_limit=2)
    state = NovelState.load(result.directory)
    body = build_mail_body(state, result)
    assert "✔ 1장" in body and "✔ 2장" in body
    assert "· 3장" in body
    assert "남은 장은 다음 실행에서" in body


# -- API 응답 처리 ----------------------------------------------------------


class _Block:
    def __init__(self, type_, text=""):
        self.type = type_
        self.text = text


class _Message:
    def __init__(self, content, stop_reason="end_turn", stop_details=None):
        self.content = content
        self.stop_reason = stop_reason
        self.stop_details = stop_details


def test_text_of_keeps_only_text_blocks():
    message = _Message([_Block("thinking"), _Block("text", "본문"), _Block("text", "이어짐")])
    assert _text_of(message) == "본문이어짐"


def test_refusal_becomes_readable_error():
    details = type("D", (), {"category": "violence"})()
    with pytest.raises(ClaudeError, match="거절"):
        _check_stop(_Message([], stop_reason="refusal", stop_details=details), "1장 본문")


def test_max_tokens_stop_is_warned_not_raised(caplog):
    with caplog.at_level("WARNING"):
        _check_stop(_Message([], stop_reason="max_tokens"), "1장 본문")
    assert "잘렸습니다" in caplog.text


def test_usage_summary_includes_cost():
    usage = Usage()
    usage.input_tokens, usage.output_tokens, usage.calls = 1_000_000, 100_000, 3
    assert "약 $7.50" in usage.summary("claude-opus-5")
    assert "$" not in usage.summary("알수없는-모델")


# -- ClaudeClient 호출 모양 (anthropic SDK 를 가짜로 바꿔 확인) ----------------


class _FakeStream:
    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._message


class _FakeMessages:
    def __init__(self, message=None, error=None):
        self.message = message
        self.error = error
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return _FakeStream(self.message)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.message


def _fake_anthropic(monkeypatch, message=None, error=None):
    """anthropic 패키지 대신 쓸 최소 대역을 sys.modules 에 끼워 넣는다."""
    import sys
    import types

    module = types.ModuleType("anthropic")

    class APIStatusError(Exception):
        def __init__(self, message="", status_code=500):
            super().__init__(message)
            self.message = message
            self.status_code = status_code

    module.APIStatusError = APIStatusError
    module.AuthenticationError = type("AuthenticationError", (APIStatusError,), {})
    module.RateLimitError = type("RateLimitError", (APIStatusError,), {})
    module.APIConnectionError = type("APIConnectionError", (Exception,), {})

    messages = _FakeMessages(message=message, error=error)
    module.Anthropic = lambda **kwargs: type("C", (), {"messages": messages})()
    monkeypatch.setitem(sys.modules, "anthropic", module)
    return module, messages


def _client(monkeypatch, message=None, error=None):
    from novel_writer.claude_client import ClaudeClient

    module, messages = _fake_anthropic(monkeypatch, message, error)
    return ClaudeClient(api_key="k", model="claude-opus-5", effort="high"), module, messages


def test_write_streams_with_adaptive_thinking_and_effort(monkeypatch):
    message = _Message([_Block("thinking"), _Block("text", " 본문이다. ")])
    message.usage = type("U", (), {"input_tokens": 10, "output_tokens": 20})()
    client, _, messages = _client(monkeypatch, message=message)

    text = client.write(system="시스템", prompt="프롬프트", what="1장 본문", max_tokens=12345)

    assert text == "본문이다."
    sent = messages.calls[0]
    assert sent["model"] == "claude-opus-5"
    assert sent["max_tokens"] == 12345
    assert sent["thinking"] == {"type": "adaptive"}
    assert sent["output_config"] == {"effort": "high"}
    assert sent["messages"] == [{"role": "user", "content": "프롬프트"}]
    assert client.usage.output_tokens == 20


def test_write_uses_per_call_effort(monkeypatch):
    client, _, messages = _client(monkeypatch, message=_Message([_Block("text", "메모")]))
    client.write(system="s", prompt="p", what="1장 요약", effort="low")
    assert messages.calls[0]["output_config"]["effort"] == "low"


def test_json_asks_for_schema_and_parses(monkeypatch):
    client, _, messages = _client(monkeypatch, message=_Message([_Block("text", '{"title":"등대"}')]))
    schema = {"type": "object"}
    assert client.json(system="s", prompt="p", schema=schema) == {"title": "등대"}
    assert messages.calls[0]["output_config"]["format"] == {"type": "json_schema", "schema": schema}


def test_json_reports_broken_response(monkeypatch):
    client, _, _ = _client(monkeypatch, message=_Message([_Block("text", "{깨진")]))
    with pytest.raises(ClaudeError, match="JSON"):
        client.json(system="s", prompt="p", schema={})


def test_empty_response_is_an_error(monkeypatch):
    client, _, _ = _client(monkeypatch, message=_Message([_Block("thinking")]))
    with pytest.raises(ClaudeError, match="비어"):
        client.write(system="s", prompt="p")


@pytest.mark.parametrize(
    "error_name, expected",
    [
        ("AuthenticationError", "ANTHROPIC_API_KEY"),
        ("RateLimitError", "요청 한도"),
        ("APIConnectionError", "네트워크"),
        ("APIStatusError", r"실패\(500\)"),
    ],
)
def test_sdk_errors_become_korean_messages(monkeypatch, error_name, expected):
    from novel_writer.claude_client import ClaudeClient

    module, messages = _fake_anthropic(monkeypatch)
    messages.error = getattr(module, error_name)("boom")
    client = ClaudeClient(api_key="k", model="claude-opus-5")

    with pytest.raises(ClaudeError, match=expected):
        client.write(system="s", prompt="p", what="1장 본문")
