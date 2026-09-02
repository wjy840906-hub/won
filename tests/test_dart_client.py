import io
import zipfile

import pytest

from kind_managed.dart_client import (
    CompanyInfo,
    DartClient,
    DartError,
    format_biz_no,
    format_corp_reg_no,
    parse_corp_code_xml,
)

CORP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<result>
  <list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name><stock_code>005930</stock_code><modify_date>20260101</modify_date></list>
  <list><corp_code>00111111</corp_code><corp_name>(주)에이제이네트웍스</corp_name><stock_code>095570</stock_code><modify_date>20260101</modify_date></list>
  <list><corp_code>00222222</corp_code><corp_name>비상장회사</corp_name><stock_code></stock_code><modify_date>20260101</modify_date></list>
</result>
""".encode("utf-8")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1234567890", "123-45-67890"),
        ("123-45-67890", "123-45-67890"),
        ("", ""),
        ("123", "123"),
    ],
)
def test_format_biz_no(raw, expected):
    assert format_biz_no(raw) == expected


def test_format_corp_reg_no():
    assert format_corp_reg_no("1101110012345") == "110111-0012345"
    assert format_corp_reg_no("bad") == "bad"


def test_parse_corp_code_xml_builds_both_indexes():
    by_stock, by_name = parse_corp_code_xml(CORP_XML)
    assert by_stock["005930"] == "00126380"
    assert by_stock["095570"] == "00111111"
    assert "" not in by_stock
    # (주) 와 공백을 무시하고 상호로도 찾을 수 있어야 한다
    assert by_name["에이제이네트웍스"] == "00111111"
    assert by_name["비상장회사"] == "00222222"


class _Response:
    def __init__(self, content=b"", payload=None, status=200):
        self.content = content
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeSession:
    """corpCode.xml(zip) 과 company.json 을 흉내내는 세션."""

    def __init__(self, company_payload=None):
        self.company_payload = company_payload or {
            "status": "000",
            "message": "정상",
            "corp_name": "에이제이네트웍스",
            "bizr_no": "1048118820",
            "jurir_no": "1101110012345",
            "ceo_nm": "홍길동",
            "adres": "서울특별시 중구",
            "est_dt": "19900101",
        }
        self.company_calls = []

    def get(self, url, params=None, timeout=None):
        if url.endswith("corpCode.xml"):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr("CORPCODE.xml", CORP_XML)
            return _Response(content=buffer.getvalue())
        self.company_calls.append(params["corp_code"])
        return _Response(payload=self.company_payload)


def _client(tmp_path, session):
    return DartClient(api_key="dummy", session=session, cache_dir=tmp_path, request_interval=0)


def test_lookup_by_stock_code(tmp_path):
    session = _FakeSession()
    client = _client(tmp_path, session)

    info, problem = client.lookup(stock_code="095570", name="에이제이네트웍스")

    assert problem == ""
    assert isinstance(info, CompanyInfo)
    assert info.biz_no == "104-81-18820"
    assert info.corp_reg_no == "110111-0012345"
    assert info.ceo_name == "홍길동"
    assert session.company_calls == ["00111111"]


def test_lookup_falls_back_to_company_name(tmp_path):
    session = _FakeSession()
    client = _client(tmp_path, session)

    info, problem = client.lookup(stock_code="", name="(주) 에이제이네트웍스")

    assert problem == ""
    assert info.corp_code == "00111111"


def test_lookup_reports_unmatched(tmp_path):
    session = _FakeSession()
    client = _client(tmp_path, session)

    info, problem = client.lookup(stock_code="999999", name="없는회사")

    assert info is None
    assert problem == "DART 고유번호 미매칭"


def test_lookup_reports_missing_biz_no(tmp_path):
    session = _FakeSession(company_payload={"status": "000", "corp_name": "삼성전자", "bizr_no": ""})
    client = _client(tmp_path, session)

    info, problem = client.lookup(stock_code="005930")

    assert info is not None
    assert problem == "DART에 사업자등록번호 없음"


def test_company_result_is_cached(tmp_path):
    session = _FakeSession()
    client = _client(tmp_path, session)

    client.lookup(stock_code="095570")
    client.lookup(stock_code="095570")

    assert session.company_calls == ["00111111"]  # 두 번째는 캐시 사용


def test_corp_code_xml_is_cached_on_disk(tmp_path):
    session = _FakeSession()
    _client(tmp_path, session).lookup(stock_code="095570")

    cached = list(tmp_path.glob("corpcode-*.xml"))
    assert len(cached) == 1
    assert b"00126380" in cached[0].read_bytes()


def test_bad_api_key_raises(tmp_path):
    class _ErrorSession(_FakeSession):
        def get(self, url, params=None, timeout=None):
            return _Response(
                content=b"<result><status>010</status><message>\xeb\x93\xb1\xeb\xa1\x9d</message></result>"
            )

    client = _client(tmp_path, _ErrorSession())
    with pytest.raises(DartError, match="status=010"):
        client.lookup(stock_code="005930")


def test_missing_api_key_raises(tmp_path):
    with pytest.raises(DartError, match="DART_API_KEY"):
        DartClient(api_key="", cache_dir=tmp_path)


def test_api_error_status_on_company(tmp_path):
    session = _FakeSession(company_payload={"status": "020", "message": "요청 제한 초과"})
    client = _client(tmp_path, session)

    info, problem = client.lookup(stock_code="005930")

    assert info is None
    assert "status=020" in problem
