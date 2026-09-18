# 소설 쓰기 매크로

소재 한 줄을 주면 **기획**(제목 · 줄거리 · 인물 · 장별 구성)을 짠 뒤,
**장별로 이어서 본문을 써서** 원고 파일(`원고.md` · `원고.txt`)로 저장합니다.

```
소재 한 줄 ──▶ 기획(JSON) ──▶ 1장 집필 ──▶ 메모 ──▶ 2장 집필 ──▶ … ──▶ 원고 파일 (──▶ 메일)
```

한 번에 통째로 쓰게 하면 뒤로 갈수록 이름·설정이 흔들리므로,
**장을 쓸 때마다 요약 메모를 만들어 다음 장 프롬프트에 넣습니다.**
직전 장의 마지막 대목도 함께 넘겨 문체와 호흡이 끊기지 않게 합니다.

## 준비물

**Anthropic API 키** 하나면 됩니다 — https://console.anthropic.com → API Keys.
(관리종목 매크로의 DART 키 · SMTP 는 이 매크로에 필요 없습니다. 메일로 받을 때만 SMTP 가 필요합니다.)

```bash
pip install -r requirements.txt
cp .env.example .env      # ANTHROPIC_API_KEY 를 채운 뒤
set -a; source .env; set +a
```

## 실행

```bash
# 가장 간단한 사용법 — 10장, 장당 3천 자
PYTHONPATH=src python -m novel_writer "퇴근길 지하철에서 어제로 돌아가는 남자"

# 조건을 붙여서
PYTHONPATH=src python -m novel_writer "낡은 등대를 지키는 소년" \
  --genre 미스터리 --tone "담백하고 건조한 문체" --pov "1인칭 주인공" \
  --chapters 12 --chars 4000

# 기획만 먼저 보고 마음에 들면 이어서 쓰기
PYTHONPATH=src python -m novel_writer "낡은 등대를 지키는 소년" --plan-only
PYTHONPATH=src python -m novel_writer --resume "out/novel/2026-09-18-등대의-계절"

# 하루 두 장씩 연재하듯 나눠 쓰기
PYTHONPATH=src python -m novel_writer --resume "out/novel/2026-09-18-등대의-계절" --batch 2

# 다 쓴 원고를 메일로 받기 (SMTP 설정 필요 — 관리종목 매크로와 같은 값을 씁니다)
PYTHONPATH=src python -m novel_writer "낡은 등대를 지키는 소년" --email --mail-to 나@회사.com
```

### 옵션

| 옵션 | 설명 |
| --- | --- |
| `--title` | 희망 제목(비우면 모델이 짓습니다) |
| `--genre` | 장르 (예: 미스터리, 로맨스, SF) |
| `--tone` | 분위기·문체 (예: 담백하고 건조한 문체) |
| `--pov` | 시점 (예: 1인칭 주인공, 3인칭 관찰자) |
| `--audience` | 독자층 (예: 성인 일반, 청소년) |
| `--notes` | 그 밖의 요구 (예: 결말은 열린 결말로) |
| `--chapters N` | 장 수 (기본 10, `NOVEL_CHAPTERS`) |
| `--chars N` | 장당 목표 글자수 (기본 3000, `NOVEL_CHAPTER_CHARS`) |
| `--plan-only` | 기획만 만들고 멈춤 |
| `--resume <폴더>` | 저장된 작업 폴더를 이어서 씀 |
| `--batch N` | 이번 실행에서 N장만 씀 |
| `--model` / `--effort` | 모델(기본 `claude-opus-5`) / 공들이는 정도(`low`~`max`, 기본 `high`) |
| `--out-dir` | 작업 폴더 상위 경로 (기본 `out/novel`) |
| `--email` / `--mail-to` | 원고를 첨부해 메일 발송 |
| `-v` | 상세 로그 |

종료 코드: `0` 성공 / `1` 집필·발송 실패 / `2` 설정 누락

## 작업 폴더

작품 하나가 폴더 하나입니다. **중간에 끊겨도 쓴 장까지는 남습니다**(`Ctrl+C` 포함).

```
out/novel/2026-09-18-등대의-계절/
  plan.json        기획(제목·줄거리·인물·장별 구성) — 직접 고쳐도 됩니다
  progress.json    어디까지 썼는지 + 장별 메모
  chapters/01.md   장별 본문
  원고.md          전체 원고(마크다운)
  원고.txt         전체 원고(한글·워드에 붙여 넣기용)
```

`plan.json` 의 장 제목이나 개요를 고친 뒤 `--resume` 하면 **고친 기획대로 나머지를 씁니다.**
이미 쓴 장을 다시 쓰고 싶으면 `chapters/03.md` 를 지우고 `progress.json` 의 해당 항목을 지운 뒤 `--resume` 하세요.

## 비용

실행이 끝나면 실제 사용량이 출력됩니다(`사용량: 호출 21회 / 입력 … / 출력 … / 약 $…`).
`claude-opus-5` 기준 10장 × 3천 자면 대략 **$2~5** 선입니다.
싸게 시험해 보려면 `--model claude-sonnet-5 --effort medium --chapters 3` 처럼 줄여서 먼저 돌려 보세요.

## 더 잘 쓰게 하려면

- `--tone` 에 원하는 문체를 구체적으로 적을수록 결과가 크게 달라집니다.
  ("짧은 문장, 감정 설명 없이 행동만", "1980년대 시골 말투" 등)
- 장당 글자수를 너무 크게 잡으면(8천 자 이상) 뒤가 늘어집니다. 장을 늘리는 편이 낫습니다.
- 기획이 마음에 들 때까지 `--plan-only` 로 다시 뽑는 편이, 다 쓴 뒤 고치는 것보다 쌉니다.
- 초고입니다. 사람 손으로 다듬는 것을 전제로 쓰세요.

## GitHub Actions 로 돌리기

`.github/workflows/novel.yml` 을 Actions 탭에서 **수동 실행**(`Run workflow`)하면
소재·장 수·분량을 입력해 원고를 만들고, 결과를 **아티팩트**로 내려받을 수 있습니다.
`ANTHROPIC_API_KEY` 를 **Settings → Secrets and variables → Actions** 에 등록해 두세요.

Actions 러너는 실행이 끝나면 사라지므로 `--resume` 이어쓰기는 로컬에서 하는 편이 낫습니다.

## 구조

```
src/novel_writer/
  claude_client.py  Claude 호출(장문은 스트리밍, 기획은 JSON 스키마) · 사용량 집계
  prompts.py        기획·집필·요약 프롬프트
  planner.py        기획 생성 + 장 번호 정리
  writer.py         장별 집필 + 다음 장용 메모 작성
  state.py          작업 폴더(기획·본문·진행 상태) 읽기/쓰기
  exporter.py       원고.md · 원고.txt 생성
  pipeline.py       전체 흐름(+ 메일 발송)
  config.py         환경변수·입력값 설정
  __main__.py       CLI
```

메일 발송은 관리종목 매크로의 `kind_managed.mailer` 를 그대로 씁니다(SMTP 설정도 같습니다).

## 알아 둘 점

- 결과물은 **초고**입니다. 사실관계·표현은 사람이 확인해야 합니다.
- 모델이 소재를 거절하면 그 이유가 메시지로 나옵니다. 소재나 요구사항을 바꿔 다시 실행하세요.
- 기존 작품을 그대로 옮기지 않도록 프롬프트에 못을 박아 두었지만, 발표 전에는 직접 확인하세요.
