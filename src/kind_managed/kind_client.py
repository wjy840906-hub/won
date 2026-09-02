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

# 시장 구분 선택지.
# 이 엔드포인트는 marketType 파라미터를 지원하지 않아(빈 응답 반환) 받은 뒤 걸러낸다.
MARKET_CHOICES = {
    "": "전체",
    "stockMkt": "유가증권",
    "kosdaqMkt": "코스닥",
    "konexMkt": "코넥스",
    "유가증권": "유가증권",
    "코스닥": "코스닥",
    "코넥스": "코넥스",
}

_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_DATE_RE = re.compile(r"(\d{4})\D(\d{1,2})\D(\d{1,2})")
_TOTAL_RE = re.compile(r'id=["\']totalCount["\'][^>]*value=["\'](\d+)["\']')
# 페이징 영역: 전체 <em>172</em>건 : <strong>1</strong>/2
_TOTAL_EM_RE = re.compile(r"전체\s*<em>\s*([\d,]+)\s*</em>\s*건")

# 종목명 셀 안의 아이콘으로 시장을 구분한다.
# 예: <img src="/images/common/icn_t_yu.gif" alt="유가증권">, icn_t_ko.gif alt="코스닥"
MARKET_LABELS = ("유가증권", "코스닥", "코넥스")
_MARKET_HINTS = (
    ("icn_t_yu", "유가증권"),
    ("icn_t_ko", "코스닥"),
    ("icn_t_kx", "코넥스"),
    ("konex", "코넥스"),
    ("kosdaq", "코스닥"),
    ("kospi", "유가증권"),
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


def _market_from_cell(cell) -> str:
    """셀 안 아이콘의 alt / 파일명으로 시장 구분을 알아낸다."""
    for image in cell.find_all("img"):
        alt = _clean(image.get("alt", ""))
        if alt in MARKET_LABELS:
            return alt
        source = (image.get("src") or "").lower()
        for hint, label in _MARKET_HINTS:
            if hint in source:
                return label
    return _guess_market(str(cell))


def _guess_market(html_fragment: str) -> str:
    lowered = html_fragment.lower()
    for label in MARKET_LABELS:
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


def _map_labels(labels: list[str]) -> dict[int, str]:
    """컬럼 라벨 목록을 인덱스 → 내부 필드명 매핑으로 바꾼다."""
    mapping: dict[int, str] = {}
    for index, label in enumerate(labels):
        field_name = _HEADER_ALIASES.get(label)
        if field_name is None:
            for alias, candidate in _HEADER_ALIASES.items():
                if alias in label:
                    field_name = candidate
                    break
        if field_name and field_name not in mapping.values():
            mapping[index] = field_name
    return mapping


def _map_from_headers(table) -> dict[int, str]:
    """<th> 헤더에서 컬럼 매핑을 만든다. KIND 처럼 헤더가 비어 있으면 {} 를 준다."""
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
    labels = [_clean(cell.get_text()) for cell in header_row.find_all(["th", "td"])]
    return _map_labels(labels) if any(labels) else {}


def _map_from_summary(table) -> dict[int, str]:
    """summary 속성에서 컬럼 순서를 읽는다.

    KIND 는 헤더를 JS 로 채우기 때문에 <th> 가 비어 있고,
    대신 <table summary="종목명, 지정일, 지정사유"> 가 컬럼 순서를 알려준다.
    """
    summary = _clean(table.get("summary", ""))
    if not summary or "," not in summary:
        return {}
    return _map_labels([part.strip() for part in summary.split(",")])


def _map_from_content(table) -> dict[int, str]:
    """헤더도 summary 도 없을 때, 본문 첫 행의 값 모양으로 컬럼을 추정한다."""
    body = table.find("tbody") or table
    sample = None
    for row in body.find_all("tr"):
        cells = row.find_all("td")
        if cells:
            sample = [_clean(cell.get_text(" ")) for cell in cells]
            break
    if not sample:
        return {}

    mapping: dict[int, str] = {}
    for index, value in enumerate(sample):
        if "designated_on" not in mapping.values() and _DATE_RE.search(value):
            mapping[index] = "designated_on"
    if "designated_on" not in mapping.values():
        # 지정일이 없는 표는 관리종목 목록이 아니다(예: 오류 페이지의 안내 표).
        return {}
    remaining = [i for i in range(len(sample)) if i not in mapping]
    if remaining:
        mapping[remaining[0]] = "name"
    rest = [i for i in remaining[1:] if sample[i]]
    if rest:
        # 남은 칸 중 가장 서술적인(긴) 값을 지정사유로 본다.
        mapping[max(rest, key=lambda i: len(sample[i]))] = "reason"
    return mapping


def _column_map(table) -> dict[int, str]:
    """표의 컬럼 매핑을 헤더 → summary → 내용 순서로 시도한다."""
    for builder in (_map_from_headers, _map_from_summary, _map_from_content):
        mapping = builder(table)
        if "name" in mapping.values() and len(set(mapping.values())) >= 2:
            return mapping
    return {}


def _pick_table(soup: BeautifulSoup):
    """관리종목 목록 표와 그 컬럼 매핑을 고른다."""
    best = None
    best_score = 0
    for table in soup.find_all("table"):
        if not (table.find("tbody") or table.find("td")):
            continue
        mapping = _column_map(table)
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
    name_index = next((i for i, f in mapping.items() if f == "name"), 0)

    rows: list[ManagedStock] = []
    for tr in body.find_all("tr"):
        cells = tr.find_all("td")
        if not cells:
            continue  # 헤더 행
        values = {"name": "", "reason": "", "designated_on": "", "code": "", "market": ""}
        for index, cell in enumerate(cells):
            field_name = mapping.get(index)
            if field_name is not None:
                values[field_name] = _clean(cell.get_text(" "))

        if not values["name"]:
            continue

        name_cell = cells[name_index] if name_index < len(cells) else cells[0]
        if not values["code"]:
            # KIND 관리종목 표에는 종목코드가 없지만, 다른 화면을 파싱할 때를 위해 남겨 둔다.
            values["code"] = _extract_code(name_cell)
        if not values["market"]:
            values["market"] = _market_from_cell(name_cell)

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
    match = _TOTAL_EM_RE.search(html)
    if match:
        return int(match.group(1).replace(",", ""))
    match = re.search(r"[총전][체]?\s*<?[^>]*>?\s*([\d,]+)\s*건", html)
    if match:
        return int(match.group(1).replace(",", ""))
    return None


class KindClient:
    """KIND 관리종목 조회 클라이언트."""

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: int = 30,
        page_size: int = 500,
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

    def fetch_page(self, page_index: int) -> tuple[list[ManagedStock], int | None]:
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
        }
        html = self._post(payload)
        return parse_rows(html), parse_total_count(html)

    def fetch_managed_stocks(self, market: str = "") -> KindResult:
        """관리종목 전체 목록을 모은다.

        currentPageSize 를 크게 주면 KIND 가 전체를 한 번에 돌려주므로 보통 1회 요청으로 끝나고,
        페이지 순회는 안전망으로만 동작한다.
        """
        if market not in MARKET_CHOICES:
            raise KindError(
                f"지원하지 않는 시장 구분입니다: {market!r} (가능: {sorted(MARKET_CHOICES)})"
            )

        result = KindResult()
        seen: set[tuple[str, str, str]] = set()

        for page_index in range(1, self.max_pages + 1):
            rows, total = self.fetch_page(page_index)
            result.pages_fetched = page_index
            if total is not None:
                result.total_count = total

            new_rows = 0
            for row in rows:
                key = (row.name, row.reason, row.designated_on)
                if key in seen:
                    continue
                seen.add(key)
                result.rows.append(row)
                new_rows += 1

            log.info(
                "KIND %d페이지: 수신 %d건 / 신규 %d건 (누적 %d건 / 전체 %s건)",
                page_index,
                len(rows),
                new_rows,
                len(result.rows),
                result.total_count if result.total_count is not None else "?",
            )

            # KIND 는 마지막 페이지를 넘어선 요청에도 같은 내용을 돌려주므로
            # 신규 행이 없으면 중단한다.
            if not rows or new_rows == 0 or len(rows) < self.page_size:
                break
            if result.total_count is not None and len(result.rows) >= result.total_count:
                break
        else:
            log.warning("최대 페이지 수(%d)에 도달해 조회를 중단했습니다.", self.max_pages)

        self._validate(result)

        if market:
            label = MARKET_CHOICES[market]
            before = len(result.rows)
            result.rows = [row for row in result.rows if row.market == label]
            log.info("시장 구분 %s 로 한정: %d건 → %d건", label, before, len(result.rows))

        return result

    @staticmethod
    def _validate(result: KindResult) -> None:
        """오류 페이지를 목록으로 착각해 발송하는 일이 없도록 결과를 검증한다."""
        if not result.rows:
            raise KindError(
                "관리종목을 한 건도 파싱하지 못했습니다. "
                "KIND 페이지 구조가 변경되었거나 접근이 차단되었을 수 있습니다."
            )

        dated = sum(1 for row in result.rows if _DATE_RE.fullmatch(row.designated_on or ""))
        if dated * 2 < len(result.rows):
            raise KindError(
                f"파싱 결과가 관리종목 목록으로 보이지 않습니다"
                f"(전체 {len(result.rows)}건 중 지정일이 확인된 행 {dated}건). "
                "KIND 가 오류 페이지를 반환했을 수 있습니다."
            )

        if result.total_count is not None and len(result.rows) < result.total_count:
            log.warning(
                "KIND 가 알려준 전체 건수(%d)보다 적게 수집했습니다: %d건",
                result.total_count,
                len(result.rows),
            )
