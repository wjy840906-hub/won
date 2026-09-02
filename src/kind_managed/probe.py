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
    session = _session()

    print("=" * 78)
    print("1) 메인 페이지 조회:", MAIN_URL)
    print("=" * 78)
    try:
        response = session.get(MAIN_URL, timeout=30)
        response.encoding = response.apparent_encoding or "utf-8"
        html = response.text
        print(f"    status={response.status_code} len={len(html)} "
              f"encoding={response.encoding} content-type={response.headers.get('Content-Type')}")
        print(f"    쿠키: {list(session.cookies.keys())}")
        _describe_forms(html)
        _describe_js(html)
        _describe_tables(html)
        print("    --- 본문 앞 1200자 ---")
        print(re.sub(r"\n\s*\n", "\n", html[:1200]))
        if dump_path:
            with open(dump_path, "w", encoding="utf-8") as handle:
                handle.write(html)
            print(f"    (전체 HTML 저장: {dump_path})")
    except requests.RequestException as exc:
        print(f"    !! 메인 페이지 조회 실패: {exc}")
        return 1

    for label, verb, payload in CANDIDATES:
        print()
        print("=" * 78)
        print(f"2) 후보 {label} [{verb}] {payload}")
        print("=" * 78)
        try:
            if verb == "POST":
                response = session.post(BASE_URL, data=payload, timeout=30)
            else:
                response = session.get(BASE_URL, params=payload, timeout=30)
            response.encoding = response.apparent_encoding or "utf-8"
            body = response.text
        except requests.RequestException as exc:
            print(f"    !! 요청 실패: {exc}")
            continue

        rows = parse_rows(body)
        print(f"    status={response.status_code} len={len(body)} 파싱행수={len(rows)}")
        if rows:
            print(f"    첫 행: {rows[0]}")
        _describe_tables(body, limit=4)
        print("    --- 본문 앞 800자 ---")
        print(re.sub(r"\n\s*\n", "\n", body[:800]))

    return 0
