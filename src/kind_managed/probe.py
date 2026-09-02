"""KIND 응답 구조 진단 도구.

로컬에서 KIND 에 접근할 수 없는 환경을 위해, 실행 환경(예: GitHub Actions)에서
실제 응답을 뜯어 로그로 출력한다. 파서를 고칠 때 필요한 정보만 압축해서 보여준다.
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from .kind_client import BASE_URL, MAIN_URL, USER_AGENT, parse_rows

# 실제 파라미터를 모를 때 시도해 볼 후보들
CANDIDATES: list[tuple[str, str, dict[str, str]]] = [
    (
        "A. searchAdminIssueSub (현재 코드)",
        "POST",
        {
            "method": "searchAdminIssueSub",
            "currentPageSize": "100",
            "pageIndex": "1",
            "forward": "adminissue_sub",
            "orderMode": "1",
            "orderStat": "D",
            "marketType": "",
        },
    ),
    (
        "B. searchAdminIssueSub (최소 파라미터)",
        "POST",
        {"method": "searchAdminIssueSub", "currentPageSize": "100", "pageIndex": "1"},
    ),
    (
        "C. searchAdminIssueMain (POST)",
        "POST",
        {"method": "searchAdminIssueMain", "currentPageSize": "100", "pageIndex": "1"},
    ),
    (
        "D. searchAdminIssueMain (GET)",
        "GET",
        {"method": "searchAdminIssueMain"},
    ),
]


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html, */*; q=0.01",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": MAIN_URL,
            "Origin": "https://kind.krx.co.kr",
            "X-Requested-With": "XMLHttpRequest",
        }
    )
    return session


def _describe_tables(html: str, limit: int = 6) -> None:
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")
    print(f"    표 개수: {len(tables)}")
    for index, table in enumerate(tables[:limit]):
        caption = table.find("caption")
        headers = [
            re.sub(r"\s+", " ", cell.get_text()).strip()
            for cell in table.find_all("th")[:12]
        ]
        body_rows = len(table.find_all("tr"))
        print(
            f"    [표{index}] class={table.get('class')} "
            f"caption={caption.get_text(strip=True) if caption else None} "
            f"tr={body_rows} 헤더={headers}"
        )
        first = table.find("tbody")
        first_row = (first or table).find("tr")
        if first_row is not None:
            cells = [
                re.sub(r"\s+", " ", cell.get_text()).strip()
                for cell in first_row.find_all(["td", "th"])[:12]
            ]
            print(f"           첫 행: {cells}")


def _describe_forms(html: str) -> None:
    soup = BeautifulSoup(html, "lxml")
    for form in soup.find_all("form"):
        print(f"    <form name={form.get('name')} id={form.get('id')} action={form.get('action')}>")
        for field in form.find_all(["input", "select"])[:40]:
            print(
                f"      {field.name} name={field.get('name')!r} "
                f"id={field.get('id')!r} value={field.get('value')!r}"
            )


def _describe_js(html: str) -> None:
    """JS 안에서 실제로 쓰이는 method / forward 값을 뽑는다."""
    methods = sorted(set(re.findall(r"""method['"]?\s*[=:,]\s*['"]([A-Za-z0-9_]+)['"]""", html)))
    methods += sorted(set(re.findall(r"method=([A-Za-z0-9_]+)", html)))
    forwards = sorted(set(re.findall(r"""forward['"]?\s*[=:,]\s*['"]([A-Za-z0-9_]+)['"]""", html)))
    urls = sorted(set(re.findall(r"""['"](/[A-Za-z0-9_/]+\.do)""", html)))
    print(f"    JS method 후보: {sorted(set(methods))}")
    print(f"    JS forward 후보: {forwards}")
    print(f"    .do 엔드포인트: {urls[:20]}")


def run_probe(dump_path: str = "") -> int:
    """실제 응답의 페이지네이션 동작을 확인한다."""
    session = _session()
    base_payload = {
        "method": "searchAdminIssueSub",
        "forward": "adminissue_sub",
        "orderMode": "1",
        "orderStat": "D",
        "marketType": "",
    }

    def call(page_size: int, page_index: int) -> tuple[str, list]:
        payload = dict(base_payload, currentPageSize=str(page_size), pageIndex=str(page_index))
        response = session.post(BASE_URL, data=payload, timeout=30)
        response.encoding = response.apparent_encoding or "utf-8"
        return response.text, parse_rows(response.text)

    print("=" * 78)
    print("1) 페이지 크기 100, pageIndex 1~4")
    print("=" * 78)
    seen: set[str] = set()
    for page_index in range(1, 5):
        body, rows = call(100, page_index)
        names = [row.name for row in rows]
        overlap = len(seen & set(names))
        seen |= set(names)
        print(
            f"  page {page_index}: len={len(body)} rows={len(rows)} "
            f"이전페이지와중복={overlap} 첫={names[0] if names else None} 끝={names[-1] if names else None}"
        )
        if page_index == 1:
            print("  --- 응답 마지막 1500자 (페이징 마크업 확인) ---")
            print(re.sub(r"\n\s*\n", "\n", body[-1500:]))
        if not rows:
            break
    print(f"  누적 고유 종목 수: {len(seen)}")

    print()
    print("=" * 78)
    print("2) 페이지 크기를 키워서 한 번에 받아지는지")
    print("=" * 78)
    for page_size in (500, 5000):
        body, rows = call(page_size, 1)
        dates = sorted({row.designated_on for row in rows if row.designated_on})
        print(
            f"  size={page_size}: len={len(body)} rows={len(rows)} "
            f"지정일범위={dates[0] if dates else None} ~ {dates[-1] if dates else None}"
        )
        if dump_path and page_size == 5000:
            with open(dump_path, "w", encoding="utf-8") as handle:
                handle.write(body)
            print(f"  (전체 HTML 저장: {dump_path})")

    print()
    print("=" * 78)
    print("3) 시장 구분 파라미터(marketType) 반응")
    print("=" * 78)
    for market in ("", "stockMkt", "kosdaqMkt", "konexMkt"):
        payload = dict(base_payload, currentPageSize="5000", pageIndex="1", marketType=market)
        response = session.post(BASE_URL, data=payload, timeout=30)
        response.encoding = response.apparent_encoding or "utf-8"
        rows = parse_rows(response.text)
        markets = sorted({row.market for row in rows})
        print(f"  marketType={market!r:12} rows={len(rows)} 포함시장={markets}")

    return 0
