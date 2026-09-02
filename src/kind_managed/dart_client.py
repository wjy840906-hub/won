"""DART 오픈API로 종목별 사업자등록번호를 조회한다.

- corpCode.xml : 종목코드(6자리) ↔ DART 고유번호(corp_code) 매핑 (하루 1회 캐시)
- company.json : corp_code 로 기업개황(사업자등록번호 등) 조회
"""

from __future__ import annotations

import io
import logging
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

log = logging.getLogger(__name__)

CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
COMPANY_URL = "https://opendart.fss.or.kr/api/company.json"

# DART 응답 status 코드 중 재시도가 무의미한 것들
_FATAL_STATUS = {
    "010": "등록되지 않은 DART API 키입니다.",
    "011": "사용할 수 없는 DART API 키입니다(오픈API 이용 중지).",
    "012": "접근할 수 없는 IP 입니다.",
    "020": "요청 제한을 초과했습니다(일 20,000건).",
    "021": "조회 가능한 회사 개수가 초과했습니다.",
    "101": "부적절한 접근입니다.",
    "800": "시스템 점검으로 서비스가 중지 중입니다.",
    "900": "정의되지 않은 오류입니다.",
    "901": "사용자 계정의 개인정보가 보관 기간을 경과했습니다.",
}


class DartError(RuntimeError):
    """DART 조회 실패."""


@dataclass
class CompanyInfo:
    """DART 기업개황 중 이 파이프라인에서 쓰는 항목."""

    corp_code: str = ""
    corp_name: str = ""
    biz_no: str = ""
    corp_reg_no: str = ""
    ceo_name: str = ""
    address: str = ""
    established_on: str = ""


def format_biz_no(raw: str) -> str:
    """사업자등록번호를 000-00-00000 형태로 정리한다."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) != 10:
        return (raw or "").strip()
    return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"


def format_corp_reg_no(raw: str) -> str:
    """법인등록번호를 000000-0000000 형태로 정리한다."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) != 13:
        return (raw or "").strip()
    return f"{digits[:6]}-{digits[6:]}"


def _normalize_name(name: str) -> str:
    """상호 비교용 정규화: 공백/괄호/(주) 등을 제거한다."""
    text = re.sub(r"\(\s*주\s*\)|주식회사|㈜", "", name or "")
    text = re.sub(r"[\s\-_.,]", "", text)
    return text.lower()


def parse_corp_code_xml(xml_bytes: bytes) -> tuple[dict[str, str], dict[str, str]]:
    """CORPCODE.xml 을 파싱해 (종목코드→고유번호, 정규화상호→고유번호)를 만든다."""
    by_stock: dict[str, str] = {}
    by_name: dict[str, str] = {}
    root = ET.fromstring(xml_bytes)
    for node in root.iter("list"):
        corp_code = (node.findtext("corp_code") or "").strip()
        corp_name = (node.findtext("corp_name") or "").strip()
        stock_code = (node.findtext("stock_code") or "").strip()
        if not corp_code:
            continue
        if stock_code and stock_code != "":
            by_stock.setdefault(stock_code.zfill(6), corp_code)
        if corp_name:
            # 상장사(종목코드 보유)를 우선 등록해 동명 비상장사에 밀리지 않게 한다.
            key = _normalize_name(corp_name)
            if stock_code or key not in by_name:
                by_name[key] = corp_code
    return by_stock, by_name


class DartClient:
    """DART 오픈API 클라이언트."""

    def __init__(
        self,
        api_key: str,
        session: requests.Session | None = None,
        timeout: int = 30,
        cache_dir: str | Path = ".cache",
        request_interval: float = 0.05,
    ) -> None:
        if not api_key:
            raise DartError("DART_API_KEY 가 설정되지 않았습니다.")
        self.api_key = api_key
        self.session = session or requests.Session()
        self.timeout = timeout
        self.cache_dir = Path(cache_dir)
        self.request_interval = request_interval
        self._by_stock: dict[str, str] | None = None
        self._by_name: dict[str, str] | None = None
        self._company_cache: dict[str, CompanyInfo] = {}

    # ------------------------------------------------------------------ 고유번호

    def _corp_code_cache_path(self) -> Path:
        return self.cache_dir / f"corpcode-{date.today().isoformat()}.xml"

    def _download_corp_code(self) -> bytes:
        try:
            response = self.session.get(
                CORP_CODE_URL, params={"crtfc_key": self.api_key}, timeout=self.timeout
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise DartError(f"corpCode.xml 다운로드 실패: {exc}") from exc

        content = response.content
        if not content[:2] == b"PK":
            # 오류일 때는 zip 대신 XML 에러 메시지가 온다.
            text = content.decode("utf-8", errors="replace")
            status = re.search(r"<status>(\d+)</status>", text)
            message = re.search(r"<message>(.*?)</message>", text)
            code = status.group(1) if status else "?"
            detail = _FATAL_STATUS.get(code) or (message.group(1) if message else text[:200])
            raise DartError(f"corpCode.xml 응답 오류(status={code}): {detail}")

        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".xml")]
            if not names:
                raise DartError("corpCode zip 안에 XML 파일이 없습니다.")
            return archive.read(names[0])

    def _load_corp_codes(self) -> None:
        if self._by_stock is not None:
            return
        cache_path = self._corp_code_cache_path()
        if cache_path.exists():
            log.info("corpCode 캐시 사용: %s", cache_path)
            xml_bytes = cache_path.read_bytes()
        else:
            log.info("corpCode.xml 다운로드 중...")
            xml_bytes = self._download_corp_code()
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(xml_bytes)
        self._by_stock, self._by_name = parse_corp_code_xml(xml_bytes)
        log.info("corpCode 로드 완료: 상장 %d건", len(self._by_stock))

    def find_corp_code(self, stock_code: str = "", name: str = "") -> str:
        """종목코드 우선, 없으면 상호로 DART 고유번호를 찾는다."""
        self._load_corp_codes()
        assert self._by_stock is not None and self._by_name is not None
        if stock_code:
            found = self._by_stock.get(stock_code.zfill(6))
            if found:
                return found
        if name:
            return self._by_name.get(_normalize_name(name), "")
        return ""

    # ------------------------------------------------------------------ 기업개황

    def fetch_company(self, corp_code: str) -> CompanyInfo:
        """corp_code 로 기업개황을 조회한다(프로세스 내 캐시)."""
        if corp_code in self._company_cache:
            return self._company_cache[corp_code]

        if self.request_interval:
            time.sleep(self.request_interval)
        try:
            response = self.session.get(
                COMPANY_URL,
                params={"crtfc_key": self.api_key, "corp_code": corp_code},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise DartError(f"company.json 조회 실패(corp_code={corp_code}): {exc}") from exc

        status = str(payload.get("status", ""))
        if status != "000":
            detail = _FATAL_STATUS.get(status, payload.get("message", ""))
            raise DartError(f"company.json 응답 오류(status={status}): {detail}")

        info = CompanyInfo(
            corp_code=corp_code,
            corp_name=(payload.get("corp_name") or "").strip(),
            biz_no=format_biz_no(payload.get("bizr_no", "")),
            corp_reg_no=format_corp_reg_no(payload.get("jurir_no", "")),
            ceo_name=(payload.get("ceo_nm") or "").strip(),
            address=(payload.get("adres") or "").strip(),
            established_on=(payload.get("est_dt") or "").strip(),
        )
        self._company_cache[corp_code] = info
        return info

    def lookup(self, stock_code: str = "", name: str = "") -> tuple[CompanyInfo | None, str]:
        """종목코드/상호로 기업개황을 조회한다.

        Returns:
            (기업개황 또는 None, 실패 사유 메시지)
        """
        corp_code = self.find_corp_code(stock_code=stock_code, name=name)
        if not corp_code:
            return None, "DART 고유번호 미매칭"
        try:
            info = self.fetch_company(corp_code)
        except DartError as exc:
            # 단건 실패로 전체 파이프라인을 멈추지 않는다.
            log.warning("기업개황 조회 실패 (%s / %s): %s", stock_code, name, exc)
            return None, str(exc)
        if not info.biz_no:
            return info, "DART에 사업자등록번호 없음"
        return info, ""
