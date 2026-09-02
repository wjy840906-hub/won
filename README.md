# 관리종목 일일 리포트 자동화

한국거래소 상장공시시스템 **KIND**(kind.krx.co.kr)에서 **관리종목**(종목명 · 지정사유 · 지정일)을
매일 수집하고, 각 종목의 **사업자등록번호**를 붙여 **엑셀(.xlsx)** 로 만든 뒤
**wonjiyun@hanafn.com** 으로 메일 발송합니다.

기본 수집 범위는 **지정일 2026-08-01 이후**입니다(`FROM_DATE`).
KIND 관리종목 목록에는 2023년 지정분까지 남아 있어, 범위를 두지 않으면 전체가 담깁니다.

```
KIND 관리종목 조회 ──▶ DART 기업개황(사업자등록번호) 결합 ──▶ 엑셀 생성 ──▶ 메일 발송
```

## 엑셀 컬럼

| 번호 | 시장구분 | 종목코드 | 종목명 | 사업자등록번호 | 법인등록번호 | 대표자 | 지정사유 | 지정일 | 비고 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

- 종목코드 · 사업자등록번호 · 법인등록번호는 앞자리 `0` 이 사라지지 않도록 텍스트 서식으로 저장합니다.
- KIND 관리종목 표에는 종목코드가 없어, **종목코드도 DART 조회 결과에서 채웁니다.**
- 조회에 실패한 종목은 값을 비우고 **비고**에 사유(`DART 고유번호 미매칭` 등)를 남깁니다.
  일부 종목이 실패해도 나머지는 정상적으로 발송됩니다.

## 사업자등록번호는 어디서 오나

KIND 관리종목 화면에는 사업자등록번호가 없고, **종목코드도 없습니다**(종목명 · 지정일 · 지정사유 3개 컬럼뿐).
그래서 **상호명**으로 금융감독원 **DART 오픈API** 고유번호를 찾은 뒤,
기업개황(`company.json`)에서 `bizr_no`(사업자등록번호), `jurir_no`(법인등록번호),
`ceo_nm`(대표자), `stock_code`(종목코드)를 가져와 결합합니다.

- 상호 ↔ DART 고유번호 매핑(`corpCode.xml`)은 하루 1회만 내려받아 `.cache/` 에 보관합니다.
  20MB 규모라 첫 다운로드에 수 분이 걸리므로, Actions 에서는 하루 단위로 캐시합니다.
- 상호 비교 시 `(주)`·`주식회사`·공백·구두점을 무시하고, 상장사를 우선 매칭합니다.
- 매칭에 실패한 종목은 **비고**에 사유가 남으므로 엑셀에서 바로 확인할 수 있습니다.
- **DART API 키는 https://opendart.fss.or.kr 에서 무료로 발급**받습니다(일 20,000건).
- 키가 없으면 사업자등록번호 없이 나머지 항목만으로 발송됩니다.

## 준비물

1. **DART API 키** — https://opendart.fss.or.kr → 인증키 신청
2. **SMTP 계정** — 사내 메일 서버 또는 Gmail 앱 비밀번호 등

## 로컬 실행

```bash
pip install -r requirements.txt
cp .env.example .env      # 값을 채운 뒤
set -a; source .env; set +a

# 엑셀만 만들어 보기(메일 발송 없음)
PYTHONPATH=src python -m kind_managed --no-email

# 실제 발송
PYTHONPATH=src python -m kind_managed
```

### 주요 옵션

| 옵션 | 설명 |
| --- | --- |
| `--no-email` | 메일을 보내지 않고 엑셀만 생성 |
| `--mail-to a@b.com,c@d.com` | 수신자 지정(기본값은 `MAIL_TO`) |
| `--from-date 2026-08-01` | 이 날짜 이후 지정분만(`2026-08`, `8` 도 가능. 기본: `FROM_DATE`) |
| `--market kosdaqMkt` | 시장 한정(`유가증권`·`코스닥`·`코넥스` 도 가능, 기본 전체) |
| `--probe` | KIND 응답 구조를 진단 출력(파서가 깨졌을 때) |
| `--out-dir out` | 엑셀 저장 폴더 |
| `--html-file <경로>` | KIND 대신 저장해 둔 HTML 을 파싱(오프라인 점검용) |
| `-v` | 상세 로그 |

종료 코드: `0` 성공 / `1` 수집·발송 실패 / `2` 메일 설정 누락

## 매일 자동 실행 (GitHub Actions)

`.github/workflows/daily-managed-stocks.yml` 이 **평일 08:00 KST**(cron `0 23 * * 0-4`, UTC 기준)에
자동 실행됩니다. Actions 탭에서 수동 실행(`Run workflow`)도 가능합니다.

리포지터리 **Settings → Secrets and variables → Actions** 에 아래를 등록하세요.

**Secrets**

| 이름 | 값 |
| --- | --- |
| `DART_API_KEY` | DART 오픈API 인증키 |
| `SMTP_HOST` | 예: `smtp.gmail.com` |
| `SMTP_PORT` | 예: `587` |
| `SMTP_USER` | SMTP 계정 |
| `SMTP_PASSWORD` | SMTP 비밀번호 / 앱 비밀번호 |
| `MAIL_FROM` | 발신 주소(미설정 시 `SMTP_USER`) |

**Variables** (선택)

| 이름 | 기본값 |
| --- | --- |
| `MAIL_TO` | `wonjiyun@hanafn.com` |
| `MAIL_CC` | (없음) |
| `FROM_DATE` | `2026-08-01` — 이 날짜 이후 지정분만 수집 |
| `SMTP_USE_SSL` / `SMTP_USE_STARTTLS` | `false` / `true` (465 포트면 반대로) |

> 사내 SMTP 가 외부에서 접근되지 않으면 GitHub Actions 대신 사내 서버의 `cron` 으로
> 같은 명령(`python -m kind_managed`)을 돌리면 됩니다.
> 예: `0 8 * * 1-5 cd /srv/won && PYTHONPATH=src /usr/bin/python3 -m kind_managed >> log 2>&1`

## 테스트

```bash
pip install pytest
python -m pytest
```

네트워크 없이 도는 69개 테스트가 HTML 파싱(실제 KIND 응답 픽스처 포함), DART 매칭,
엑셀 서식, 메일 조립, 기간 필터, 전체 파이프라인을 검증합니다.

## 구조

```
src/kind_managed/
  kind_client.py   KIND 관리종목 조회·HTML 파싱(헤더 이름 기반 → 표 변경에 내성)
  dart_client.py   DART 고유번호 매핑 + 기업개황(사업자등록번호) 조회
  excel_writer.py  서식 적용 엑셀 생성
  mailer.py        첨부 메일 조립 및 SMTP 발송
  pipeline.py      전체 흐름 + 기간 필터 + 메일 본문 작성
  config.py        환경변수 설정
  probe.py         KIND 응답 구조 진단(--probe)
  __main__.py      CLI
```

## KIND 응답에 대해 확인된 사실

실제 응답을 확인해 반영한 내용입니다(파서를 고칠 때 참고).

- 엔드포인트는 `POST /investwarn/adminissue.do` + `method=searchAdminIssueSub`.
- **`<thead>` 가 비어 있습니다.** 헤더는 JS(`fn_InitTitle`)가 채우므로, 컬럼 순서는
  `<table summary="종목명, 지정일, 지정사유">` 속성에서 읽습니다.
- 컬럼 순서는 **종목명 | 지정일 | 지정사유** 이며, 종목코드는 없습니다.
- 시장 구분은 아이콘 `alt`(`유가증권`/`코스닥`)로만 알 수 있습니다.
  같은 셀의 `관리종목`·`투자주의환기종목` 배지와 혼동하지 않아야 합니다.
- **`marketType` 파라미터는 동작하지 않습니다.** 전체를 받은 뒤 걸러냅니다.
- 전체 건수는 페이징 영역의 `전체 <em>172</em>건` 에 있습니다.
- `currentPageSize` 를 크게 주면 전체가 한 번에 옵니다(기본 500). 마지막 페이지를
  넘어선 `pageIndex` 에도 같은 내용을 돌려주므로, 중복 제거로 순회를 멈춥니다.

구조가 또 바뀌면 `--probe` 로 응답을 덤프해 확인하세요
(Actions 의 `KIND 응답 구조 진단` 워크플로가 같은 일을 합니다).
파싱 결과가 비었거나 지정일이 확인된 행이 절반에 못 미치면 오류로 종료하므로,
**오류 페이지나 빈 엑셀이 발송되는 일은 없습니다.**

## 실행 실적 (2026-09-02 기준)

| 항목 | 값 |
| --- | --- |
| KIND 관리종목 전체 | 172종목 (지정일 2023-03-23 ~ 2026-09-02) |
| `FROM_DATE=2026-08-01` 적용 후 | 75종목 |
| 사업자등록번호 확인 | 72/75종목 |

매칭되지 않은 종목은 엑셀 **비고**와 실행 로그에 함께 남습니다.

## 참고

- 관리종목 지정/해제는 거래소 공시 시점에 반영되므로, 발송 시각을 장 시작 전으로 두면
  전 영업일까지의 지정 내역이 담깁니다.
