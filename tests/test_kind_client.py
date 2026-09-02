from pathlib import Path

import pytest

from kind_managed.kind_client import (
    KindClient,
    normalize_date,
    parse_rows,
    parse_total_count,
)

FIXTURE = Path(__file__).parent / "fixtures" / "adminissue_sub.html"


@pytest.fixture(scope="module")
def html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_parse_rows_extracts_all_columns(html):
    rows = parse_rows(html)
    assert len(rows) == 3

    first = rows[0]
    assert first.name == "에이제이네트웍스"
    assert first.code == "095570"
    assert first.market == "유가증권"
    assert first.reason == "감사의견 거절"
    assert first.designated_on == "2026-09-02"


def test_parse_rows_normalizes_market_and_date(html):
    rows = parse_rows(html)
    assert [row.market for row in rows] == ["유가증권", "코스닥", "코넥스"]
    assert [row.designated_on for row in rows] == ["2026-09-02", "2026-03-20", "2025-04-15"]


def test_parse_total_count(html):
    assert parse_total_count(html) == 3


def test_parse_rows_ignores_unrelated_tables():
    noise = "<table><tr><th>구분</th><th>값</th></tr><tr><td>a</td><td>b</td></tr></table>"
    assert parse_rows(noise) == []


def test_parse_rows_handles_alternate_headers():
    html = """
    <table>
      <thead><tr><th>종목코드</th><th>종목명</th><th>시장구분</th><th>사유</th><th>지정일자</th></tr></thead>
      <tbody><tr><td>005930</td><td>테스트전자</td><td>유가증권</td><td>자본잠식</td><td>2026/01/05</td></tr></tbody>
    </table>
    """
    rows = parse_rows(html)
    assert len(rows) == 1
    assert rows[0].code == "005930"
    assert rows[0].name == "테스트전자"
    assert rows[0].market == "유가증권"
    assert rows[0].designated_on == "2026-01-05"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-09-02", "2026-09-02"),
        ("2026.9.2", "2026-09-02"),
        ("20260902", "2026-09-02"),
        (" 2026 / 09 / 02 ", "2026-09-02"),
        ("", ""),
    ],
)
def test_normalize_date(raw, expected):
    assert normalize_date(raw) == expected


class _FakeResponse:
    def __init__(self, text):
        self.text = text
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    def raise_for_status(self):
        return None


class _FakeSession:
    """KIND 서버 대신 고정 HTML 을 돌려주는 세션."""

    def __init__(self, html):
        self.html = html
        self.headers = {}
        self.posts = []

    def get(self, *args, **kwargs):
        return _FakeResponse("")

    def post(self, url, data=None, timeout=None):
        self.posts.append(data)
        return _FakeResponse(self.html)


def test_fetch_managed_stocks_stops_when_page_not_full(html):
    session = _FakeSession(html)
    client = KindClient(session=session, page_size=100)
    result = client.fetch_managed_stocks()

    assert len(result.rows) == 3
    assert result.total_count == 3
    assert result.pages_fetched == 1
    assert session.posts[0]["method"] == "searchAdminIssueSub"


def test_fetch_managed_stocks_stops_at_total_count(html):
    session = _FakeSession(html)
    # 페이지가 가득 찬 것처럼 보여도 totalCount 에 도달하면 더 요청하지 않는다.
    client = KindClient(session=session, page_size=3, max_pages=5)
    result = client.fetch_managed_stocks()

    assert len(result.rows) == 3
    assert result.pages_fetched == 1


def test_fetch_managed_stocks_deduplicates_repeated_pages(html):
    # totalCount 가 없으면 페이지가 가득 찬 동안 계속 요청하지만, 같은 행은 누적하지 않는다.
    without_total = html.split("</div>", 1)[1]
    session = _FakeSession(without_total)
    client = KindClient(session=session, page_size=3, max_pages=5)
    result = client.fetch_managed_stocks()

    assert len(result.rows) == 3  # 중복 페이지는 누적되지 않는다
    assert result.pages_fetched == 2
