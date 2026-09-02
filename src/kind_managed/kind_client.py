"""KIND(한국거래소 상장공시시스템) 관리종목 목록 수집."""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

BASE_URL = "https://kind.krx.co.kr/investwarn/adminissue.do"
MAIN_URL = f"{BASE_URL}?method=searchAdminIssueMain"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# KIND 시장 구분 코드 (marketType 파라미터)
MARKET_CHOICES = {
    "": "전체",
    "stockMkt": "유가증권",
    "kosdaqMkt": "코스닥",
    "konexMkt": "코넥스",
}

_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_DATE_RE = re.compile(r"(\d{4})\D(\d{1,2})\D(\d{1,2})")
_TOTAL_RE = re.compile(r'id=["\']totalCount["\'][^>]*value=["\'](\d+)["\']')

# 회사명 셀 안의 이미지로 시장을 구분한다 (예: /images/common/img_kosdaq.gif)
_MARKET_HINTS = (
    ("konex", "코넥스"),
    ("kosdaq", "코스닥"),
    ("kospi", "유가증권"),
    ("stock", "유가증권"),
    ("yuga", "유가증권"),
)

# 표 헤더 이름 → 내부 필드명
_HEADER_ALIASES = {
    "회사명": "name",
    "종목명": "name",
    "기업명": "name",
    "종목": "name",
    "지정사유": "reason",
    "사유": "reason",
    "지정사유(내용)": "reason",
    "지정일": "designated_on",
    "지정일자": "designated_on",
    "지정일(변경일)": "designated_on",
    "시장구분": "market",
    "시장": "market",
    "종목코드": "code",
    "단축코드": "code",
}


class KindError(RuntimeError):
    """KIND 조회/파싱 실패."""


@dataclass
class ManagedStock:
    """관리종목 한 건."""

    name: str
    reason: str
    designated_on: str
    code: str = ""
    market: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class KindResult:
    """관리종목 조회 결과."""

    rows: list[ManagedStock] = field(default_factory=list)
    total_count: int | None = None
    pages_fetched: int = 0


def _clean(text: str) -> str:
    """공백/개행/비가시 문자를 정리한다."""
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def normalize_date(text: str) -> str:
    """'2025.03.20', '2025-03-20', '20250320' 등을 YYYY-MM-DD 로 통일한다."""
    cleaned = _clean(text)
    match = _DATE_RE.search(cleaned)
    if match:
        year, month, day = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    digits = re.sub(r"\D", "", cleaned)
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return cleaned


def _guess_market(html_fragment: str) -> str:
    lowered = html_fragment.lower()
    for label in ("유가증권", "코스닥", "코넥스"):
        if label in html_fragment:
            return label
    for hint, label in _MARKET_HINTS:
        if hint in lowered:
            return label
    return ""


def _extract_code(cell) -> str:
    """행/셀의 링크 속성에서 6자리 단축코드를 찾는다."""
    for attr in ("onclick", "href", "id", "name", "value", "title"):
        for node in [cell, *cell.find_all(True)]:
            raw = node.get(attr)
            if not raw:
                continue
            if isinstance(raw, list):
                raw = " ".join(raw)
            match = _CODE_RE.search(raw)
            if match:
                return match.group(1)
    return ""


def _header_map(table) -> dict[int, str]:
    """표 헤더를 읽어 컬럼 인덱스 → 내부 필드명 매핑을 만든다."""
    header_row = None
    thead = table.find("thead")
    if thead:
        header_row = thead.find("tr")
    if header_row is None:
        for row in table.find_all("tr"):
            if row.find("th"):
                header_row = row
                break
    if header_row is None:
        return {}

    mapping: dict[int, str] = {}
    for index, cell in enumerate(header_row.find_all(["th", "td"])):
        label = _clean(cell.get_text())
        field_name = _HEADER_ALIASES.get(label)
        if field_name is None:
            for alias, candidate in _HEADER_ALIASES.items():
                if alias and alias in label:
                    field_name = candidate
                    break
        if field_name and field_name not in mapping.values():
            mapping[index] = field_name
    return mapping


def _pick_table(soup: BeautifulSoup):
    """관리종목 목록 표를 고른다(헤더에 회사명/종목명이 있는 표)."""
    best = None
    best_score = 0
    for table in soup.find_all("table"):
        mapping = _header_map(table)
        fields = set(mapping.values())
        if "name" not in fields:
            continue
        score = len(fields & {"name", "reason", "designated_on"})
        if score > best_score:
            best, best_score = (table, mapping), score
    return best if best_score >= 2 else None


def parse_rows(html: str) -> list[ManagedStock]:
    """KIND 응답 HTML에서 관리종목 행을 추출한다."""
    soup = BeautifulSoup(html, "lxml")
    picked = _pick_table(soup)
    if picked is None:
        return []
    table, mapping = picked

    body = table.find("tbody") or table
    rows: list[ManagedStock] = []
    for tr in body.find_all("tr"):
        cells = tr.find_all("td")
        if not cells:
            continue  # 헤더 행
        values = {"name": "", "reason": "", "designated_on": "", "code": "", "market": ""}
        for index, cell in enumerate(cells):
            field_name = mapping.get(index)
            if field_name is None:
                continue
            values[field_name] = _clean(cell.get_text(" "))

        if not values["name"]:
            continue

        name_cell = next(
            (cells[i] for i, f in mapping.items() if f == "name" and i < len(cells)),
            cells[0],
        )
        if not values["code"]:
            values["code"] = _extract_code(name_cell) or _extract_code(tr)
        if not values["market"]:
            values["market"] = _guess_market(str(name_cell)) or _guess_market(str(tr))

        rows.append(
            ManagedStock(
                name=values["name"],
                reason=values["reason"],
                designated_on=normalize_date(values["designated_on"]),
                code=values["code"].zfill(6) if values["code"] else "",
                market=values["market"],
            )
        )
    return rows


def parse_total_count(html: str) -> int | None:
    """응답에 포함된 totalCount 값을 읽는다(없으면 None)."""
    match = _TOTAL_RE.search(html)
    if match:
        return int(match.group(1))
    match = re.search(r"총\s*<?[^>]*>?\s*([\d,]+)\s*건", html)
    if match:
        return int(match.group(1).replace(",", ""))
    return None


class KindClient:
    """KIND 관리종목 조회 클라이언트."""

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: int = 30,
        page_size: int = 100,
        max_pages: int = 50,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "text/html, */*; q=0.01",
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
                "Referer": MAIN_URL,
                "Origin": "https://kind.krx.co.kr",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        self.timeout = timeout
        self.page_size = page_size
        self.max_pages = max_pages

    def _post(self, data: dict[str, str]) -> str:
        try:
            response = self.session.post(BASE_URL, data=data, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:  # 네트워크/HTTP 오류
            raise KindError(f"KIND 요청 실패: {exc}") from exc
        response.encoding = response.apparent_encoding or "utf-8"
        return response.text

    def fetch_page(self, page_index: int, market: str = "") -> tuple[list[ManagedStock], int | None]:
        """관리종목 목록 한 페이지를 조회한다."""
        payload = {
            "method": "searchAdminIssueSub",
            "currentPageSize": str(self.page_size),
            "pageIndex": str(page_index),
            "forward": "adminissue_sub",
            "orderMode": "1",
            "orderStat": "D",
            "searchMode": "",
            "searchCodeType": "",
            "repIsuSrtCd": "",
            "allRepIsuSrtCd": "",
            "marketType": market,
        }
        html = self._post(payload)
        return parse_rows(html), parse_total_count(html)

    def fetch_managed_stocks(self, market: str = "") -> KindResult:
        """모든 페이지를 순회해 관리종목 전체 목록을 모은다."""
        if market not in MARKET_CHOICES:
            raise KindError(
                f"지원하지 않는 시장 구분입니다: {market!r} (가능: {sorted(MARKET_CHOICES)})"
            )

        # 세션 쿠키 확보 목적으로 메인 페이지를 먼저 연다(실패해도 진행).
        try:
            self.session.get(MAIN_URL, timeout=self.timeout)
        except requests.RequestException as exc:
            log.warning("KIND 메인 페이지 접근 실패(무시하고 진행): %s", exc)

        result = KindResult()
        seen: set[tuple[str, str, str]] = set()

        for page_index in range(1, self.max_pages + 1):
            rows, total = self.fetch_page(page_index, market=market)
            result.pages_fetched = page_index
            if total is not None:
                result.total_count = total

            new_rows = 0
            for row in rows:
                key = (row.code or row.name, row.reason, row.designated_on)
                if key in seen:
                    continue
                seen.add(key)
                result.rows.append(row)
                new_rows += 1

            log.info(
                "KIND %d페이지: 수신 %d건 / 신규 %d건 (누적 %d건)",
                page_index,
                len(rows),
                new_rows,
                len(result.rows),
            )

            if not rows or new_rows == 0 or len(rows) < self.page_size:
                break
            if result.total_count is not None and len(result.rows) >= result.total_count:
                break
        else:
            log.warning("최대 페이지 수(%d)에 도달해 조회를 중단했습니다.", self.max_pages)

        if not result.rows:
            raise KindError(
                "관리종목을 한 건도 파싱하지 못했습니다. "
                "KIND 페이지 구조가 변경되었거나 접근이 차단되었을 수 있습니다."
            )
        return result
