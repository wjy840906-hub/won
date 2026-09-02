# 관리종목 일일 리포트 자동화

한국거래소 상장공시시스템 **KIND**(kind.krx.co.kr)에서 **관리종목**(종목명 · 지정사유 · 지정일)을
매일 수집하고, 각 종목의 **사업자등록번호**를 붙여 **엑셀(.xlsx)** 로 만든 뒤
**wonjiyun@hanafn.com** 으로 메일 발송합니다.

```
KIND 관리종목 조회 ──▶ DART 기업개황(사업자등록번호) 결합 ──▶ 엑셀 생성 ──▶ 메일 발송
```

## 엑셀 컬럼

| 번호 | 시장구분 | 종목코드 | 종목명 | 사업자등록번호 | 법인등록번호 | 대표자 | 지정사유 | 지정일 | 비고 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

- 종목코드 · 사업자등록번호 · 법인등록번호는 앞자리 `0` 이 사라지지 않도록 텍스트 서식으로 저장합니다.
- 조회에 실패한 종목은 값을 비우고 **비고**에 사유(`DART 고유번호 미매칭` 등)를 남깁니다.
  일부 종목이 실패해도 나머지는 정상적으로 발송됩니다.

## 사업자등록번호는 어디서 오나

KIND 관리종목 화면에는 사업자등록번호가 없습니다. 그래서 종목코드를 키로
금융감독원 **DART 오픈API**의 기업개황(`company.json`)에서 `bizr_no`(사업자등록번호),
`jurir_no`(법인등록번호), `ceo_nm`(대표자)를 가져와 결합합니다.

- 종목코드 ↔ DART 고유번호 매핑(`corpCode.xml`)은 하루 1회만 내려받아 `.cache/` 에 보관합니다.
- 종목코드로 못 찾으면 상호명(`(주)`·공백 무시)으로 한 번 더 찾습니다.
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
| `--market kosdaqMkt` | 시장 한정(`stockMkt`·`kosdaqMkt`·`konexMkt`, 기본 전체) |
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
| `SMTP_USE_SSL` / `SMTP_USE_STARTTLS` | `false` / `true` (465 포트면 반대로) |

> 사내 SMTP 가 외부에서 접근되지 않으면 GitHub Actions 대신 사내 서버의 `cron` 으로
> 같은 명령(`python -m kind_managed`)을 돌리면 됩니다.
> 예: `0 8 * * 1-5 cd /srv/won && PYTHONPATH=src /usr/bin/python3 -m kind_managed >> log 2>&1`

## 테스트

```bash
pip install pytest
python -m pytest
```

네트워크 없이 도는 43개 테스트가 HTML 파싱, DART 매칭, 엑셀 서식, 메일 조립,
전체 파이프라인을 검증합니다.

## 구조

```
src/kind_managed/
  kind_client.py   KIND 관리종목 조회·HTML 파싱(헤더 이름 기반 → 표 변경에 내성)
  dart_client.py   DART 고유번호 매핑 + 기업개황(사업자등록번호) 조회
  excel_writer.py  서식 적용 엑셀 생성
  mailer.py        첨부 메일 조립 및 SMTP 발송
  pipeline.py      전체 흐름 + 메일 본문 작성
  config.py        환경변수 설정
  __main__.py      CLI
```

## 참고

- KIND 표 구조가 바뀌면 `kind_client.py` 의 `_HEADER_ALIASES` 에 새 헤더 이름을 추가하면 됩니다.
  한 건도 파싱되지 않으면 오류로 종료해, 빈 엑셀이 발송되는 일은 없습니다.
- 관리종목 지정/해제는 거래소 공시 시점에 반영되므로, 발송 시각을 장 시작 전으로 두면
  전 영업일까지의 지정 내역이 담깁니다.
