"""기획·집필·요약 단계에서 쓰는 프롬프트."""

from __future__ import annotations

SYSTEM_PLANNER = """당신은 장편 소설의 구성을 짜는 편집자다.
주어진 소재로 끝까지 읽히는 이야기의 뼈대를 만든다.

원칙
- 인물에게 분명한 결핍과 목표, 그것을 막는 장애를 준다.
- 각 장은 '상황 변화'로 끝난다. 정보만 나열하고 끝나는 장을 만들지 않는다.
- 전체를 도입 → 상승 → 전환 → 절정 → 결말의 흐름으로 배치하고, 마지막 장에서 갈등을 매듭짓는다.
- 복선은 심은 장과 회수하는 장을 함께 계획한다.
- 기존 작품의 설정이나 문장을 옮겨 오지 말고, 실존 인물을 그대로 등장시키지 않는다.
- 요청받은 언어로만 쓴다."""

SYSTEM_WRITER = """당신은 소설가다. 주어진 기획과 앞 장의 내용을 이어받아 지정된 장의 본문만 쓴다.

원칙
- 설명하지 말고 장면으로 보여 준다. 감각·행동·대사로 상황을 전달한다.
- 앞 장에서 정해진 이름·설정·문체·시제·시점을 절대 바꾸지 않는다.
- 요약하거나 건너뛰지 않는다. 지정된 분량을 장면으로 채운다.
- 대사는 한국어 소설 관습대로 큰따옴표로 쓰고, 화자를 알 수 있게 한다.
- 장 제목, 머리말, 해설, '계속' 같은 군더더기를 붙이지 않는다. 본문만 출력한다."""

SYSTEM_SUMMARIZER = """당신은 편집자다. 다음 장을 쓰는 작가가 앞 내용을 잊지 않도록 간결한 메모를 만든다.
사건의 결과, 인물 관계의 변화, 새로 생긴 설정과 미회수 복선을 빠짐없이 적는다. 감상이나 평가는 쓰지 않는다."""


def plan_prompt(brief_lines: str, chapters: int, chapter_chars: int, language: str) -> str:
    """기획(제목·시놉시스·인물·장별 개요) 요청 프롬프트."""
    return f"""아래 요구로 {language} 장편 소설을 기획하라.

{brief_lines}

조건
- 전체 {chapters}개 장, 장마다 약 {chapter_chars}자 분량으로 쓸 수 있게 사건을 배분한다.
- chapters 배열은 정확히 {chapters}개, number 는 1부터 차례대로 매긴다.
- 각 장의 summary 에는 그 장에서 '무엇이 어떻게 달라지는지'를 쓴다.
- beats 에는 그 장의 장면을 3~5개로 나눠 순서대로 적는다.
- characters 에는 주요 인물 3~6명을 넣고, profile 에 결핍·목표·말투를 적는다.
- 모든 값은 {language}로 쓴다."""


def chapter_prompt(
    *,
    plan_digest: str,
    chapter: dict,
    story_so_far: str,
    previous_tail: str,
    chapter_chars: int,
    total_chapters: int,
    language: str,
) -> str:
    """한 장의 본문 집필 프롬프트."""
    number = chapter.get("number", 0)
    beats = "\n".join(f"  {i}. {beat}" for i, beat in enumerate(chapter.get("beats") or [], 1))
    blocks = [f"""[기획]
{plan_digest}"""]

    if story_so_far:
        blocks.append(f"""[여기까지의 줄거리]
{story_so_far}""")
    if previous_tail:
        blocks.append(
            f"""[직전 장의 마지막 대목 — 문체와 호흡을 그대로 이어받되 다시 쓰지 말 것]
…{previous_tail}"""
        )

    position = "마지막 장이므로 남은 갈등과 복선을 모두 매듭짓는다."
    if number == 1:
        position = "첫 장이므로 인물과 세계를 장면 속에서 소개하고, 이야기를 끌고 갈 문제를 드러낸다."
    elif number < total_chapters:
        position = "중간 장이므로 상황을 한 단계 악화시키고, 다음 장을 읽게 만드는 문장으로 끝낸다."

    blocks.append(
        f"""[이번에 쓸 장]
- {number}장 「{chapter.get('title', '')}」 (전체 {total_chapters}장 중)
- 내용: {chapter.get('summary', '')}
- 장면 순서:
{beats or '  (자유롭게 구성)'}
- {position}

{language}로 {number}장의 본문만 써라. 공백을 포함해 {chapter_chars}자 안팎으로 쓴다."""
    )
    return "\n\n".join(blocks)


def summary_prompt(chapter: dict, text: str) -> str:
    """집필한 장을 다음 장 집필용 메모로 줄이는 프롬프트."""
    return f"""다음은 방금 쓴 {chapter.get('number', 0)}장 「{chapter.get('title', '')}」의 본문이다.

---
{text}
---

이 장의 메모를 5줄 이내로 정리하라. 각 줄은 '- ' 로 시작한다.
사건의 결과, 인물의 상태·관계 변화, 새로 등장한 설정이나 이름, 아직 회수되지 않은 복선을 담는다."""
