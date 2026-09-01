/*
 * 서버함수 응답에 형식 표시 헤더를 붙여준다.
 *
 * 앱은 /_serverFn/<id> 응답의 `x-tss-serialized: true` 헤더를 보고
 * 본문을 해석한다. 헤더가 없으면 `data is undefined` 로 화면이 죽는다.
 *
 * 원래는 서버가 붙여줘야 해서 헤더 설정이 되는 호스팅(Vercel·Netlify)이
 * 필요했다. 여기서 fetch 를 가로채 직접 붙이면 그 제약이 사라진다 —
 * 헤더 설정을 못 하는 GitHub Pages 든, 파일만 올려둔 사내 서버든 동작한다.
 *
 * 앱 번들보다 먼저 실행돼야 한다 (inject.py 가 </head> 앞에 넣는다).
 */
(function () {
  'use strict';

  var original = window.fetch;
  if (typeof original !== 'function') return;

  window.fetch = function (input, init) {
    var url = typeof input === 'string' ? input : (input && input.url) || '';

    if (url.indexOf('/_serverFn/') === -1) {
      return original.apply(this, arguments);
    }

    return original.apply(this, arguments).then(function (res) {
      if (res.headers.get('x-tss-serialized')) return res;   // 서버가 이미 붙여줬다

      return res.arrayBuffer().then(function (body) {
        var headers = new Headers(res.headers);
        headers.set('content-type', 'application/json');
        headers.set('x-tss-serialized', 'true');
        return new Response(body, {
          status: res.status,
          statusText: res.statusText,
          headers: headers
        });
      });
    });
  };
})();
