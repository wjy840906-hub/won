"""브라우저 콘솔에 붙여 넣을 진단 스니펫을 만든다.

사이트가 해외 IP 를 막으면 GitHub Actions 에서 화면을 열 수 없다(도봉구 예약이
그렇다). 그럴 때는 국내에 있는 내 브라우저에서 직접 뜯어보는 수밖에 없는데,
파이썬을 깔게 하는 대신 콘솔에 한 번 붙여 넣으면 되도록 했다.

추출하는 내용은 --probe 와 똑같다. probe.EXTRACT_JS 를 그대로 끼워 넣어
만들기 때문에 둘이 어긋날 수 없다.

    python tools/build_snippet.py          # tools/probe-snippet.js 를 다시 만든다
    python tools/build_snippet.py --check  # 최신 상태인지 확인만 한다
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from booking_macro.probe import EXTRACT_JS  # noqa: E402

OUTPUT = ROOT / "tools" / "probe-snippet.js"

TEMPLATE = """// 예약 사이트 화면 진단 — 브라우저 콘솔용
//
// 쓰는 법
//   1) 예약 사이트에서 알고 싶은 화면을 연다 (로그인 화면, 코트 표 화면 등)
//   2) F12 → Console 탭
//   3) 이 파일 전체를 붙여 넣고 Enter
//   4) 결과가 클립보드에 복사된다. 그대로 붙여 넣어 전달하면 된다.
//
// 읽기만 하고 아무것도 누르지 않는다. 비밀번호 칸의 값은 담지 않는다.
// 이 파일은 tools/build_snippet.py 가 만든다 — 직접 고치지 말 것.

(() => {{
  const 뜯어보기 = {extract};

  const 결과 = 뜯어보기();
  const 글 = JSON.stringify(결과, null, 1);

  console.log(
    "%c화면 진단 완료",
    "font-size:14px;font-weight:bold",
    `\\n  입력칸 ${{결과.inputs.length}}개` +
    `\\n  선택상자 ${{결과.selects.length}}개` +
    `\\n  버튼·링크 ${{결과.buttons.length}}개` +
    `\\n  표 ${{결과.tables.length}}개` +
    `\\n  iframe ${{결과.iframes.length}}개` +
    `\\n  (${{글.length}}자)`
  );

  try {{
    copy(글);
    console.log("클립보드에 복사했습니다. 그대로 붙여 넣어 전달하세요.");
  }} catch (e) {{
    console.log("클립보드 복사가 안 되면 아래 내용을 직접 복사하세요:");
    console.log(글);
  }}
  return 결과;
}})();
"""


def build() -> str:
    return TEMPLATE.format(extract=EXTRACT_JS.strip())


def main(argv: list[str]) -> int:
    새로 = build()
    if "--check" in argv:
        현재 = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if 현재 != 새로:
            print(f"{OUTPUT} 가 최신이 아닙니다. python tools/build_snippet.py 를 실행하세요.",
                  file=sys.stderr)
            return 1
        print(f"{OUTPUT} 최신 상태입니다.")
        return 0
    OUTPUT.write_text(새로, encoding="utf-8")
    print(f"{OUTPUT} 를 다시 만들었습니다 ({len(새로)}자).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
