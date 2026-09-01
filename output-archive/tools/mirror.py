"""lovable 앱을 정적 파일로 내려받는다.

떠야 하는 것이 세 가지다.
  1. 각 라우트의 HTML — 서버가 렌더한 결과라 데이터가 여기 박혀 있다
  2. assets/ 의 js·css
  3. /_serverFn/<64자 hex> 응답 — 빠지면 클릭하는 순간 화면이 죽는다

3번은 `x-tsr-serverFn: true` 헤더를 보내야 받아진다. 되돌려줄 때는
응답에 `x-tss-serialized: true` 를 붙여야 한다(serve.py, vercel.json 참고).

사용:  uv run python tools/mirror.py ydp-insight-hub
"""
import json
import os
import re
import sys
import urllib.request

CONFIG = json.load(open(os.path.join(os.path.dirname(__file__), '..', 'sites.json'), encoding='utf-8'))

UA = 'daeasy-archive/1.0 (educational output preservation; ohjieun25@daeasy.co.kr)'


def get(url, headers=None):
    req = urllib.request.Request(url, headers=dict({'user-agent': UA}, **(headers or {})))
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def main(slug):
    site = CONFIG[slug]
    host = site['origin']
    out = os.path.join(os.path.dirname(__file__), '..', 'sites', slug)

    # 1. 라우트별 HTML
    htmls = {}
    for route in [''] + site['routes']:
        path = os.path.join(out, route) if route else out
        os.makedirs(path, exist_ok=True)
        html = get(host + '/' + route).decode('utf-8')
        htmls[route] = html
        open(os.path.join(path, 'index.html'), 'w', encoding='utf-8').write(html)
        print('화면  %-20s %6d bytes' % (route or '/', len(html)))

    joined = '\n'.join(htmls.values())

    # 2. 에셋
    for asset in sorted(set(re.findall(r'/assets/[A-Za-z0-9._-]+\.(?:js|css)', joined))):
        dest = os.path.join(out, asset.lstrip('/'))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        body = get(host + asset)
        open(dest, 'wb').write(body)
        print('에셋  %-28s %6d bytes' % (os.path.basename(asset), len(body)))

    # 3. 서버함수 — 번들에 박힌 64자 hex 가 곧 함수 id 다
    bundles = ''
    for asset in sorted(set(re.findall(r'/assets/[A-Za-z0-9._-]+\.js', joined))):
        bundles += open(os.path.join(out, asset.lstrip('/')), encoding='utf-8', errors='ignore').read()

    fn_dir = os.path.join(out, '_serverFn')
    os.makedirs(fn_dir, exist_ok=True)
    for fid in sorted(set(re.findall(r'\b[a-f0-9]{64}\b', bundles))):
        body = get(host + '/_serverFn/' + fid, {
            'x-tsr-serverFn': 'true',
            'accept': 'application/x-tss-framed, application/x-ndjson, application/json',
            'referer': host + '/',
        })
        open(os.path.join(fn_dir, fid), 'wb').write(body)
        print('서버   %s… %6d bytes' % (fid[:12], len(body)))


if __name__ == '__main__':
    main(sys.argv[1])
