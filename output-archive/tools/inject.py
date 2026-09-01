"""내려받은 각 화면 HTML 에 오프라인 보정 스크립트를 끼워 넣는다.

두 가지를 넣는다.
  - offline/serverfn.js  서버함수 응답에 x-tss-serialized 헤더를 붙인다 (모든 사이트)
  - offline/gmaps.js     구글 지도 → Leaflet 어댑터 (sites.json 에 map 이 있는 사이트만)

둘 다 앱 번들이 `window.fetch` / `window.google?.maps` 를 쓰기 전에 올라와야 하므로
일반 <script> 로 </head> 앞에 넣는다. 모듈 스크립트로 바꾸면 defer 라 늦게 실행돼 죽는다.

여러 번 실행해도 안전하다 — 이전에 넣은 블록을 지우고 다시 넣는다.

사용:  uv run python tools/inject.py ydp-insight-hub
"""
import glob
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = json.load(io.open(os.path.join(HERE, '..', 'sites.json'), encoding='utf-8'))

BEGIN = '<!--offline-->'
END = '<!--/offline-->'


def build_tag(has_map):
    parts = ['<script src="/offline/serverfn.js"></script>']
    if has_map:
        parts += [
            '<link rel="stylesheet" href="/offline/leaflet.css">',
            '<script src="/offline/leaflet.js"></script>',
            '<script src="/offline/gmaps.js"></script>',
        ]
    return BEGIN + ''.join(parts) + END


def main(slug):
    site = CONFIG[slug]
    root = os.path.join(HERE, '..', 'sites', slug)
    tag = build_tag('map' in site)

    targets = sorted(glob.glob(os.path.join(root, 'index.html')) +
                     glob.glob(os.path.join(root, '*', 'index.html')))
    if not targets:
        raise SystemExit('index.html 을 찾지 못했습니다: ' + root)

    for path in targets:
        html = io.open(path, encoding='utf-8', errors='ignore').read()
        rel = os.path.relpath(path, root).replace(os.sep, '/')

        html = re.sub(re.escape(BEGIN) + '.*?' + re.escape(END), '', html, flags=re.S)

        if '</head>' not in html:
            print('!! </head> 없음:', rel)
            continue

        io.open(path, 'w', encoding='utf-8').write(html.replace('</head>', tag + '</head>', 1))
        print('적용:', rel)


if __name__ == '__main__':
    main(sys.argv[1])
