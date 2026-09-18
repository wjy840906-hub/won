// 예약 사이트 화면 진단 — 브라우저 콘솔용
//
// 쓰는 법
//   1) 예약 사이트에서 알고 싶은 화면을 연다 (로그인 화면, 코트 표 화면 등)
//   2) F12 → Console 탭
//   3) 이 파일 전체를 붙여 넣고 Enter
//   4) 결과가 클립보드에 복사된다. 그대로 붙여 넣어 전달하면 된다.
//
// 읽기만 하고 아무것도 누르지 않는다. 비밀번호 칸의 값은 담지 않는다.
// 이 파일은 tools/build_snippet.py 가 만든다 — 직접 고치지 말 것.

(() => {
  const 뜯어보기 = () => {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim().slice(0, 80);
  const seen = (el) => {
    const r = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return r.width > 0 && r.height > 0 && style.visibility !== 'hidden';
  };
  const base = (el) => ({
    tag: el.tagName.toLowerCase(),
    type: clean(el.getAttribute('type')),
    id: clean(el.id),
    name: clean(el.getAttribute('name')),
    cls: clean(el.getAttribute('class')),
    placeholder: clean(el.getAttribute('placeholder')),
    label: clean(el.getAttribute('aria-label') || el.getAttribute('title')),
    text: clean(el.innerText || el.textContent),
    visible: seen(el),
  });

  const inputs = [...document.querySelectorAll('input, textarea')]
    .filter((el) => !['hidden'].includes((el.getAttribute('type') || '').toLowerCase()))
    .map(base);

  const selects = [...document.querySelectorAll('select')].map((el) => ({
    ...base(el),
    options: [...el.options].slice(0, 15).map((o) => clean(o.textContent)),
    optionCount: el.options.length,
  }));

  const buttons = [...document.querySelectorAll(
    'button, a, input[type=submit], input[type=button], [role=button]'
  )].map(base).filter((el) => el.text || el.id || el.name);

  const forms = [...document.querySelectorAll('form')].map((el) => ({
    id: clean(el.id),
    name: clean(el.getAttribute('name')),
    action: clean(el.getAttribute('action')),
    method: clean(el.getAttribute('method')) || 'get',
    fields: [...el.elements].map((f) => clean(f.getAttribute('name'))).filter(Boolean),
  }));

  const iframes = [...document.querySelectorAll('iframe, frame')].map((el) => ({
    id: clean(el.id),
    name: clean(el.getAttribute('name')),
    src: clean(el.getAttribute('src')),
  }));

  // 예약 표의 뼈대. click_cell 에 쓸 열 이름(colspan 포함)과 행 이름을 본다.
  const tables = [...document.querySelectorAll('table')].slice(0, 6).map((table) => {
    const rows = [...table.rows];
    return {
      id: clean(table.id),
      cls: clean(table.getAttribute('class')),
      rowCount: rows.length,
      header: rows.slice(0, 3).map((line) =>
        [...line.cells].map((cell) => ({ text: clean(cell.innerText), span: cell.colSpan || 1 }))
      ),
      // 행마다 어떤 값들이 있는지(중복 제거). click_cell 의 row 에 뭘 적어야
      // 하는지 바로 보이도록 — 시간표라면 ['×', '06:00~07:00'] 처럼 나온다.
      rowSamples: rows.slice(0, 30).map((line) => {
        const 값 = [...new Set([...line.cells].map((cell) => clean(cell.innerText)))];
        return 값.filter(Boolean).slice(0, 4);
      }).filter((값) => 값.length),
      pressable: table.querySelectorAll(
        'a, button, input:not([type=hidden]), select, [onclick]'
      ).length,
    };
  });

  return {
    title: clean(document.title),
    url: location.href,
    inputs, selects, buttons, forms, iframes, tables,
    textSample: clean(document.body ? document.body.innerText : '').slice(0, 300),
  };
};

  const 결과 = 뜯어보기();
  const 글 = JSON.stringify(결과, null, 1);

  console.log(
    "%c화면 진단 완료",
    "font-size:14px;font-weight:bold",
    `\n  입력칸 ${결과.inputs.length}개` +
    `\n  선택상자 ${결과.selects.length}개` +
    `\n  버튼·링크 ${결과.buttons.length}개` +
    `\n  표 ${결과.tables.length}개` +
    `\n  iframe ${결과.iframes.length}개` +
    `\n  (${글.length}자)`
  );

  try {
    copy(글);
    console.log("클립보드에 복사했습니다. 그대로 붙여 넣어 전달하세요.");
  } catch (e) {
    console.log("클립보드 복사가 안 되면 아래 내용을 직접 복사하세요:");
    console.log(글);
  }
  return 결과;
})();
