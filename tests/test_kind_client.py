from pathlib import Path

import pytest

from kind_managed.kind_client import (
    KindClient,
    KindError,
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


# ---------------------------------------------------------------- 실제 KIND 응답

REAL_FIXTURE = Path(__file__).parent / "fixtures" / "kind_adminissue_real.html"

# 실제 페이징 영역 마크업 (전체 건수는 여기에만 있다)
PAGING_HTML = (
    "<section class='paging-group'><div class='info type-00'>"
    "전체 <em>172</em>건 : <strong>1</strong>/2</div></section>"
)


@pytest.fixture(scope="module")
def real_html() -> str:
    return REAL_FIXTURE.read_text(encoding="utf-8")


def test_parses_real_kind_markup_with_empty_thead(real_html):
    """KIND 의 <thead> 는 JS 가 채워 비어 있다. summary 속성으로 컬럼을 잡아야 한다."""
    rows = parse_rows(real_html)
    assert len(rows) == 3

    first = rows[0]
    assert first.name == "모바일어플라이언스"
    assert first.designated_on == "2026-09-02"
    assert first.reason == "상장적격성 실질심사 대상 결정"
    assert first.market == "코스닥"


def test_real_markup_column_order_is_name_date_reason(real_html):
    """실제 컬럼 순서는 종목명 | 지정일 | 지정사유 다."""
    rows = parse_rows(real_html)
    assert [row.designated_on for row in rows] == ["2026-09-02", "2026-08-13", "2025-07-21"]
    assert [row.reason for row in rows] == [
        "상장적격성 실질심사 대상 결정",
        "시가총액 미달",
        "감사의견 거절",
    ]


def test_market_comes_from_icon_alt_not_badges(real_html):
    """관리종목/투자주의환기종목 배지 아이콘을 시장으로 오인하면 안 된다."""
    rows = parse_rows(real_html)
    assert [row.market for row in rows] == ["코스닥", "유가증권", "유가증권"]


def test_parse_total_count_from_paging_markup():
    assert parse_total_count(PAGING_HTML) == 172


def test_error_page_is_not_parsed_as_a_row():
    """KIND 오류 페이지의 안내 표를 목록으로 착각하면 안 된다."""
    error_page = (
        "<html><head><title>페이지 오류</title></head><body>"
        "<table class='pcontents' summary=''><caption>주의사항</caption>"
        "<tr><td>잠시 후 다시 이용해 주세요. 문의사항은 담당자에게 연락해 주세요.</td></tr>"
        "</table></body></html>"
    )
    assert parse_rows(error_page) == []


def test_fetch_rejects_result_without_dates():
    """지정일이 없는 결과는 오류로 막아 쓰레기 엑셀이 발송되지 않게 한다."""
    junk = (
        "<table summary='종목명, 지정일, 지정사유'><tbody>"
        "<tr><td>안내</td><td>-</td><td>잠시 후 다시 이용해 주세요</td></tr>"
        "</tbody></table>"
    )
    client = KindClient(session=_FakeSession(junk), page_size=500)
    with pytest.raises(KindError, match="관리종목 목록으로 보이지 않습니다"):
        client.fetch_managed_stocks()


def test_market_filter_is_applied_client_side(real_html):
    """이 엔드포인트는 marketType 을 지원하지 않아 받은 뒤 걸러낸다."""
    session = _FakeSession(real_html)
    client = KindClient(session=session, page_size=500)

    result = client.fetch_managed_stocks(market="kosdaqMkt")

    assert [row.name for row in result.rows] == ["모바일어플라이언스"]
    # 요청 자체에는 marketType 을 보내지 않는다
    assert "marketType" not in session.posts[0]


def test_market_filter_accepts_korean_label(real_html):
    client = KindClient(session=_FakeSession(real_html), page_size=500)
    result = client.fetch_managed_stocks(market="유가증권")
    assert [row.name for row in result.rows] == ["태원물산", "삼부토건"]


def test_unknown_market_is_rejected(real_html):
    client = KindClient(session=_FakeSession(real_html), page_size=500)
    with pytest.raises(KindError, match="지원하지 않는 시장"):
        client.fetch_managed_stocks(market="nasdaq")


def test_repeated_last_page_does_not_duplicate(real_html):
    """KIND 는 마지막 페이지를 넘어선 pageIndex 에도 같은 내용을 돌려준다."""
    session = _FakeSession(real_html)
    client = KindClient(session=session, page_size=3, max_pages=5)

    result = client.fetch_managed_stocks()

    assert len(result.rows) == 3
    assert result.pages_fetched == 2
