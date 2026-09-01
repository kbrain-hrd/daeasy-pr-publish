"""배경 지도 타일을 미리 받아둔다.

앱이 쓰던 구글 지도는 키가 원래 도메인에 묶여 있어 옮기면 빈칸이 된다.
대신 OpenStreetMap 타일을 대상 지역 범위만큼만 받아 함께 보관한다.
범위 밖은 어차피 볼 일이 없으므로 받지 않는다.

받은 타일을 재배포하는 셈이므로 화면에 출처를 표기한다(gmaps-shim.js 참고).

사용:  uv run python tools/tiles.py ydp-insight-hub
"""
import json
import math
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

CONFIG = json.load(open(os.path.join(os.path.dirname(__file__), '..', 'sites.json'), encoding='utf-8'))

UA = 'daeasy-archive/1.0 (educational output preservation; ohjieun25@daeasy.co.kr)'


def tile_xy(lat, lon, z):
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def main(slug):
    site = CONFIG[slug]
    if 'map' not in site:
        print('지도를 쓰지 않는 사이트입니다:', slug)
        return

    m = site['map']
    w, s, e, n = m['bounds']          # [서, 남, 동, 북]
    zmin, zmax = m['zoom']
    root = os.path.join(os.path.dirname(__file__), '..', 'sites', slug, 'offline-map', 'tiles')

    todo = []
    for z in range(zmin, zmax + 1):
        x0, y0 = tile_xy(n, w, z)
        x1, y1 = tile_xy(s, e, z)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                dest = os.path.join(root, str(z), str(x), '%d.png' % y)
                if not (os.path.exists(dest) and os.path.getsize(dest) > 100):
                    todo.append((z, x, y, dest))

    print('받을 타일: %d장' % len(todo))

    def fetch(job):
        z, x, y, dest = job
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        url = 'https://tile.openstreetmap.org/%d/%d/%d.png' % (z, x, y)
        req = urllib.request.Request(url, headers={'user-agent': UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            open(dest, 'wb').write(r.read())

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(fetch, todo))

    total = sum(len(files) for _, _, files in os.walk(root))
    size = sum(os.path.getsize(os.path.join(d, f))
               for d, _, files in os.walk(root) for f in files)
    print('보관 중인 타일: %d장 (%.1fMB)' % (total, size / 1024 / 1024))


if __name__ == '__main__':
    main(sys.argv[1])
