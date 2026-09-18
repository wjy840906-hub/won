# 관리종목 일일 리포트 자동화

> 이 저장소에는 두 가지 자동화가 들어 있습니다.
> **① 관리종목 일일 리포트**(아래) · **② [예약 매크로](#예약-매크로)** — 예약 사이트를 대신 눌러 주는 도구.

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
- **우선주**(`깨끗한나라우`, `동양2우B` 등)는 DART 에 따로 등재되지 않아, 접미사를 떼고
  보통주 상호로 다시 찾습니다. 사업자등록번호는 법인 단위라 보통주와 같습니다.
  이때 **비고**에 `우선주 — 보통주(...) 기준` 이라고 남기고, 종목코드는 비워 둡니다
  (보통주 코드를 빌려 쓰면 다른 종목이 됩니다).
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

네트워크 없이 도는 78개 테스트가 HTML 파싱(실제 KIND 응답 픽스처 포함), DART 매칭,
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
| 사업자등록번호 확인 | 72/75종목 → 우선주 보정 후 75/75종목 |
| 메일 발송 | wonjiyun@hanafn.com 발송 확인 |

미확인 3종목은 모두 우선주(`깨끗한나라우`·`동양2우B`·`진흥기업2우B`)였고,
보통주 상호 보정으로 채워집니다. 매칭 상태는 엑셀 **비고**와 실행 로그에 남습니다.

## 참고

- 관리종목 지정/해제는 거래소 공시 시점에 반영되므로, 발송 시각을 장 시작 전으로 두면
  전 영업일까지의 지정 내역이 담깁니다.

---

# 예약 매크로

회의실·체육시설처럼 **본인 계정으로 쓰는 예약 사이트**를, 정해진 시각에 브라우저를 띄워
대신 눌러 줍니다. 사이트마다 다른 부분(주소·버튼·입력칸)은 **시나리오 파일(YAML)** 에만
적으므로, 새 사이트를 붙일 때 파이썬 코드를 고칠 필요가 없습니다.

```
오픈 시각까지 대기 ──▶ 로그인 ──▶ 1순위 후보 시도 ──▶ 마감이면 2순위 … ──▶ 결과 메일
```

## 빠르게 해 보기

```bash
pip install -r requirements-booking.txt
python -m playwright install chromium

cp .env.example .env      # BOOKING_USER / BOOKING_PASSWORD 를 채운 뒤
set -a; source .env; set +a

# 0) 사이트 화면을 열어 입력칸·버튼의 셀렉터를 뽑아 본다 (시나리오를 쓰기 전에)
PYTHONPATH=src python -m booking_macro --probe https://예약사이트-주소

# 1) 시나리오가 올바른지, 어떤 후보를 어떤 순서로 시도할지 먼저 확인
PYTHONPATH=src python -m booking_macro scenarios/example-meeting-room.yaml --list-targets

# 2) 창을 띄워 놓고, 확정 버튼은 누르지 않은 채 끝까지 흘려 보기
PYTHONPATH=src python -m booking_macro scenarios/example-meeting-room.yaml --dry-run --headed --now

# 3) 실제 예약 (open_at 시각까지 기다렸다가 시도)
PYTHONPATH=src python -m booking_macro scenarios/example-meeting-room.yaml --email
```

**처음 쓸 때는 반드시 `--dry-run` 으로 먼저 확인하세요.** `commit: true` 로 표시한
확정 단계만 건너뛰고 나머지는 그대로 진행하므로, 셀렉터가 맞는지 안전하게 점검할 수 있습니다.

## 셀렉터 찾기 — `--probe`

시나리오에서 가장 손이 많이 가는 부분은 "이 버튼을 뭐라고 가리키지?" 입니다.
`--probe` 로 주소를 하나 열어 보면, 화면의 **입력칸 · 선택 상자 · 버튼 · form · iframe** 을
훑어서 **셀렉터 후보와 로그인 단계 초안**까지 뽑아 줍니다. 로그인하지 않고
공개 화면만 열어 보며, 예약을 넣지 않습니다.

```bash
PYTHONPATH=src python -m booking_macro --probe https://예약사이트/login --headed
```

예약 화면이 메뉴 몇 단계 안에 있으면(공공시설 사이트가 대개 그렇습니다)
`--probe-click` 으로 눌러 갈 경로를 적어 주면 됩니다. 순서대로 누른 뒤
**도착한 화면**을 뜯어봅니다.

```bash
PYTHONPATH=src python -m booking_macro \
  --probe https://예약사이트 \
  --probe-click "text=체육시설" --probe-click "text=테니스장"
```

```
============================== 따라간 경로 ==============================
  1. text=체육시설 → https://예약사이트/sports.html
  2. text=테니스장 → https://예약사이트/tennis.html
============================== 선택 상자 2개 ==============================
  #courtNo                           1번 코트 / 2번 코트 / 3번 코트
  #timeSlot                          06:00~08:00 / 08:00~10:00 / 10:00~12:00
```

여기서 나온 코트·시간대 보기를 그대로 시나리오의 `targets` 에 옮겨 적으면 됩니다.
중간에 못 누르면 거기까지 알려 주고, 그 화면이라도 뜯어봅니다.

```
============================== 입력칸 2개 ==============================
  #mbrId                             text       아이디
  #mbrPw                             password   비밀번호
============================== 버튼·링크 1개 ==============================
  #btnLogin                          '로그인'
=============== 로그인 단계 초안 — 시나리오에 붙여 넣고 확인하세요 ===============
  login:
    url: /member/login.do
    steps:
      - fill: "#mbrId"
        value: "{{ env.BOOKING_USER }}"
      - fill: "#mbrPw"
        value: "{{ env.BOOKING_PASSWORD }}"
      - click: "#btnLogin"
```

HTML 원문과 전체 화면 그림도 `out/booking/` 에 남으므로, 나중에 천천히 볼 수 있습니다.
파이썬을 깔지 않고도 **Actions 탭 → `예약 사이트 화면 진단` → Run workflow** 로
같은 진단을 돌릴 수 있습니다(주소만 넣으면 됩니다).

> **iframe 이 있다고 나오면** 예약 화면이 그 안에 들어 있다는 뜻입니다.
> 지금 시나리오 문법은 iframe 안을 다루지 못하므로, 보고서에 찍힌 `src` 주소로
> 직접 접속되는지 먼저 확인하고 그 주소를 `base_url`/`url` 로 쓰세요.

## 시나리오 쓰는 법

`scenarios/example-meeting-room.yaml` 을 복사해서 고치는 것이 가장 빠릅니다.
(`scenarios/dobong-tennis.yaml` 은 도봉구 테니스장용 초안으로, 셀렉터 자리가
`#TODO` 로 비워져 있습니다 — `--probe` 결과를 옮겨 적어 쓰세요.)
`--probe` 로 뽑은 셀렉터를 옮겨 적거나, 브라우저에서
**F12 → 요소 선택 → Copy selector** 로 가져오면 됩니다.

```yaml
name: 사내 회의실 예약
base_url: https://booking.example.com
open_at: "09:00"          # 이 시각까지 기다렸다 시도 (지우면 즉시)
attempts: 3               # 전부 마감이면 몇 번 더 돌지
interval_sec: 10          # 회차 사이 간격
deadline_sec: 600         # 이 시간을 넘기면 중단 (0 = 제한 없음)

login:
  url: /login
  steps:
    - fill: "#userId"
      value: "{{ env.BOOKING_USER }}"
    - fill: "#userPw"
      value: "{{ env.BOOKING_PASSWORD }}"
    - click: "button[type=submit]"
  success_when:
    visible: ".gnb-user"           # 로그인해야 보이는 요소

targets:                           # 위에서부터 우선순위
  - date: "+7d"
    time: ["10:00", "14:00"]       # 목록을 쓰면 조합으로 펼쳐집니다
    room: "대회의실"

reserve:
  url: /rooms?date={{ target.date }}
  steps:
    - click: "text={{ target.room }}"
    - select: "#timeSlot"
      value: "{{ target.time }}"
    - accept_dialog: true          # 뒤이어 뜰 confirm 창을 확인 누름
    - click: "#btnReserve"
      commit: true                 # --dry-run 이면 이 단계만 건너뜁니다
  success_when:
    text_contains: "예약이 완료"
  taken_when:
    text_contains: ["이미 예약된", "마감"]
```

### 단계(steps) 목록

| 액션 | 뜻 | 예 |
| --- | --- | --- |
| `goto` | 주소로 이동 | `- goto: /rooms` |
| `fill` | 입력란 채우기 | `- fill: "#id"` + `value: "..."` |
| `click` | 클릭 | `- click: "#btn"` |
| `select` | 드롭다운 선택 | `- select: "#slot"` + `value: "10:00"` |
| `check` / `uncheck` | 체크박스 | `- check: "#agree"` |
| `press` | 키 입력 | `- press: "#q"` + `value: Enter` |
| `wait_for` | 요소가 나올 때까지 대기 | `- wait_for: ".list"` |
| `wait_ms` | 고정 시간 대기 | `- wait_ms: 500` |
| `accept_dialog` | 다음 confirm/alert 확인 | `- accept_dialog: true` |
| `screenshot` | 화면 저장 | `- screenshot: 목록화면` |
| `expect_text` | 이 문구가 있어야 함 | `- expect_text: "예약 가능"` |

각 단계에 붙일 수 있는 옵션:

- `commit: true` — 되돌릴 수 없는 확정 단계. `--dry-run` 일 때만 건너뜁니다.
- `optional: true` — 실패해도 넘어갑니다(화면마다 있거나 없는 입력칸 등).
- `timeout: 30000` — 이 단계만 다른 대기 시간(밀리초).

### 후보(targets) 에서 쓸 수 있는 값

`date` 는 `2026-10-01` · `20261001` · `+7d` · `+1w` · `내일` · `월요일` 처럼 적을 수 있고,
시나리오 안에서는 사이트 표기에 맞춰 골라 씁니다.

| 자리표시자 | 값 |
| --- | --- |
| `{{ target.date }}` | `2026-10-01` |
| `{{ target.date_compact }}` | `20261001` |
| `{{ target.date_dot }}` | `2026.10.01` |
| `{{ target.year }}` / `.month` / `.day` | `2026` / `10` / `01` |
| `{{ target.weekday }}` | `목` |
| `{{ target.<직접 적은 이름> }}` | `time`, `room` 등 targets 에 적은 값 그대로 |

`{{ env.BOOKING_* }}` 로 환경변수를 참조합니다. **아이디·비밀번호는 시나리오 파일이 아니라
환경변수에 두세요** — 시나리오가 읽을 수 있는 이름은 `BOOKING_` / `RESERVE_` 로
시작하는 것뿐이라, 다른 비밀값이 새어 나가지 않습니다.

### 성공·마감 판정

| 항목 | 쓰임 |
| --- | --- |
| `success_when` | 이게 맞으면 **예약 성공**, 거기서 멈춥니다 |
| `taken_when` | 이게 맞으면 이 후보는 포기하고 **다음 후보**로 |

둘 다 `text_contains`(화면에 있는 문구) · `text_missing` · `visible`(셀렉터) ·
`hidden` 을 쓸 수 있고, 적은 것이 **모두** 맞아야 참입니다.

`success_when` 을 생략하면 **단계를 끝까지 마친 것**을 성공으로 봅니다. 성공 화면에
고정된 문구가 없을 때만 그렇게 두고, 가능하면 적어 주세요 — 적어 두어야 "눌렀지만
예약되지 않은" 경우를 잡아냅니다.

## 주요 옵션

| 옵션 | 설명 |
| --- | --- |
| `--probe URL` | 그 주소의 입력칸·버튼과 셀렉터 후보를 출력(예약하지 않음) |
| `--probe-click 셀렉터` | `--probe` 와 함께: 예약 화면까지 눌러 갈 경로(여러 번 지정 가능) |
| `--dry-run` | `commit` 단계를 누르지 않고 직전까지 진행 |
| `--headed` | 브라우저 창을 띄워 눈으로 확인 |
| `--now` | `open_at` 을 무시하고 즉시 시도 |
| `--list-targets` | 펼쳐진 후보를 순서대로 출력(브라우저 없음) |
| `--check` | 시나리오만 검사(브라우저 없음) |
| `--attempts N` / `--interval S` | 재시도 횟수·간격을 시나리오보다 우선 적용 |
| `--email` / `--mail-to a@b.com` | 결과를 메일로 발송 |
| `--out-dir` | 화면 저장 폴더 (기본 `out/booking`) |
| `-v` | 상세 로그 |

종료 코드: `0` 예약(또는 모의) 성공 / `1` 후보를 못 잡음 / `2` 설정·시나리오 오류 / `3` 실행 중단

## 환경변수

| 이름 | 기본값 | 설명 |
| --- | --- | --- |
| `BOOKING_USER` · `BOOKING_PASSWORD` | (없음) | 시나리오에서 `{{ env.* }}` 로 참조 |
| `BOOKING_HEADLESS` | `true` | `false` 면 창을 띄움 |
| `BOOKING_BROWSER` | `chromium` | `firefox` · `webkit` 도 가능 |
| `BOOKING_DRY_RUN` | `false` | `--dry-run` 의 기본값 |
| `BOOKING_SCREENSHOT` | `change` | `always` · `change` · `never` |
| `BOOKING_STATE_FILE` | (없음) | 로그인 쿠키 저장 경로. 두면 다음 실행에서 로그인 생략 |
| `BOOKING_NAV_TIMEOUT_MS` / `BOOKING_STEP_TIMEOUT_MS` | `20000` / `10000` | 대기 시간 |
| `PLAYWRIGHT_EXECUTABLE_PATH` | (없음) | 브라우저 실행 파일을 직접 지정할 때 |

메일 발송은 관리종목 리포트와 **같은 SMTP 설정**(`SMTP_HOST`, `MAIL_TO` …)을 씁니다.

## 정해진 시각에 자동 실행

`.github/workflows/reserve.yml` 이 Actions 탭에서 **수동 실행**(`Run workflow`)되도록 되어 있고,
시나리오 경로와 `--dry-run` 여부를 고를 수 있습니다. 매일 돌리려면 파일 안의 `schedule`
주석을 풀고 cron(UTC)을 맞추세요. Secrets 에 `BOOKING_USER` · `BOOKING_PASSWORD` 가 필요합니다.

> 사내망 안에서만 열리는 사이트라면 GitHub Actions 에서 접속할 수 없습니다.
> 그럴 때는 사내 PC/서버의 `cron`(또는 작업 스케줄러)에서 같은 명령을 돌리세요.
> 예: `55 8 * * 1-5 cd /srv/won && PYTHONPATH=src /usr/bin/python3 -m booking_macro scenarios/회의실.yaml >> log 2>&1`

## 구조

```
src/booking_macro/
  scenario.py   시나리오(YAML/JSON) 파싱·검증
  template.py   {{ env.* }} · {{ target.* }} 치환
  slots.py      날짜 표기 해석과 후보 펼치기
  scheduler.py  오픈 시각 대기·재시도 간격
  steps.py      단계 실행과 성공/마감 판정
  runner.py     로그인 → 후보 순회 전체 흐름
  probe.py      화면 구조 진단(--probe): 셀렉터 후보·시나리오 초안
  browser.py    Playwright 구동(여기서만 import)
  notify.py     결과 메일
  config.py     환경변수 설정
  __main__.py   CLI
```

## 쓰기 전에 알아 둘 것

- **본인 계정으로 정당하게 쓰는 예약에만** 쓰세요. 사이트 이용약관이 자동화를 금지하는 경우가
  있고, 공연 입장권은 매크로 사용 자체가 **공연법으로 금지**되어 있습니다.
- 재시도 간격은 최소 1초로 제한됩니다(`scheduler.MIN_INTERVAL_SEC`). 간격을 지나치게 좁히면
  서버에 부담을 주고 계정이 차단될 수 있으니, 기본값(10초 안팎)을 권합니다.
- 캡차·휴대폰 인증·공동인증서가 있는 사이트는 자동화할 수 없습니다.
  `--headed` 로 창을 띄워 그 단계만 직접 처리하거나, `BOOKING_STATE_FILE` 로 로그인 세션을
  저장해 두는 방법이 있습니다.
- 사이트 화면이 바뀌면 셀렉터가 깨집니다. 실패 시 `out/booking/` 에 남는 화면을 보고 고치세요.

## 테스트

```bash
python -m pytest
```

예약 매크로 쪽 113개 테스트는 **브라우저 없이** 돕니다. 가짜 페이지(`tests/fake_page.py`)로
로그인 실패·마감 감지·후보 넘어가기·재시도·모의 실행을 검증하고, 시나리오 파싱 오류
메시지와 자격증명이 로그·메일에 남지 않는지도 확인합니다. `--probe` 가 만든 로그인 초안이
그대로 시나리오로 읽히는지도 검사합니다.
