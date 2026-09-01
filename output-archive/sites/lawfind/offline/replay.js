/*
 * 녹화한 예시 질문 답변을 되돌려준다.
 *
 * AI 답변은 미리 만들어둘 수 없어서 보관본에는 AI 가 없다. 대신 원본이
 * 살아 있을 때 녹화해둔 질문(offline/recorded.js)에는 진짜 답변이 나온다.
 * 그 밖의 질문에는 앱의 답변 말풍선으로 "예시 질문만 답한다"고 알린다 —
 * 그냥 두면 방문자에게 개발자 에러가 그대로 보인다.
 *
 * recorded.js 다음, 앱 번들보다 먼저 실행돼야 한다 (inject.py 가 넣는다).
 */
(function () {
  'use strict';

  var TABLE = window.__RECORDED || {};
  var original = window.fetch;
  if (typeof original !== 'function') return;

  /* 질문 텍스트를 요청 본문에서 꺼낸다. 앱이 보내는 모양:
     {t:{...p:{k:["data"],v:[{...p:{k:["question","history"],v:[{t:1,s:"질문"},...]}}]}}} */
  function questionOf(body) {
    try {
      var node = JSON.parse(body).t.p.v[0].p.v[0];
      return typeof node.s === 'string' ? node.s : null;
    } catch (e) {
      return null;
    }
  }

  function normalize(s) {
    return String(s).replace(/\s+/g, ' ').trim();
  }

  function tssString(s) { return { t: 1, s: s }; }
  function tssArray(i) { return { t: 9, i: i, a: [], o: 0 }; }

  /* 녹화에 없는 질문에 대한 답변. 앱의 정상 답변 자리에 그대로 렌더된다. */
  function fallback(question) {
    var lines = [
      '이 화면은 교육산출물 **보관본**입니다.',
      '',
      'AI 답변은 질문이 들어와야 그때 만들어지는 것이라 보관본에 담아둘 수 없습니다. ' +
      '대신 원본이 살아 있을 때 아래 예시 질문의 답변을 미리 녹화해 두었습니다. ' +
      '왼쪽 위 새 대화(+)를 눌러 예시 질문을 선택해 주세요.',
      ''
    ];
    Object.keys(TABLE).forEach(function (fid) {
      Object.keys(TABLE[fid]).forEach(function (q) {
        lines.push('* ' + q);
      });
    });

    return JSON.stringify({
      t: 10, i: 0,
      p: {
        k: ['result', 'error', 'context'],
        v: [
          {
            t: 10, i: 1,
            p: {
              k: ['answer', 'references', 'keywords', 'apiErrors'],
              v: [tssString(lines.join('\n')), tssArray(2), tssArray(3), tssArray(4)]
            },
            o: 0
          },
          { t: 2, s: 1 },
          { t: 11, i: 5, p: { k: [], v: [] }, o: 0 }
        ]
      },
      o: 0
    });
  }

  function reply(text) {
    return new Response(text, {
      status: 200,
      headers: {
        'content-type': 'application/json',
        'x-tss-serialized': 'true'
      }
    });
  }

  window.fetch = function (input, init) {
    var url = typeof input === 'string' ? input : (input && input.url) || '';
    var marker = url.indexOf('/_serverFn/');

    if (marker === -1 || !init || String(init.method).toUpperCase() !== 'POST') {
      return original.apply(this, arguments);
    }

    var fid = url.slice(marker + '/_serverFn/'.length).split('?')[0];
    var question = questionOf(init.body);

    var answers = TABLE[fid];
    if (answers && question) {
      var wanted = normalize(question);
      var hit = Object.keys(answers).filter(function (q) {
        return normalize(q) === wanted;
      })[0];
      if (hit) return Promise.resolve(reply(answers[hit]));
    }

    return Promise.resolve(reply(fallback(question)));
  };
})();
