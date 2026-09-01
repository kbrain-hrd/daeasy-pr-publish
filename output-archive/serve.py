"""보관본을 로컬에서 확인한다.

정적 파일만 돌려주지만 두 가지를 맞춰줘야 앱이 산다.
  - /_serverFn/<id> 는 `x-tss-serialized: true` 헤더를 붙여야 한다.
    이게 없으면 화면이 `data is undefined` 로 죽는다.
  - 확장자 없는 경로는 해당 폴더의 index.html 로 보낸다.

배포할 때도 같은 헤더가 필요하다 (vercel.json 참고).

사용:  uv run python serve.py ydp-insight-hub [포트]
"""
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

SLUG = sys.argv[1] if len(sys.argv) > 1 else 'ydp-insight-hub'
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8800
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sites', SLUG)

if not os.path.isdir(ROOT):
    raise SystemExit('그런 보관본이 없습니다: ' + ROOT)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def do_GET(self):
        path = self.path.split('?')[0]

        if path.startswith('/_serverFn/'):
            f = os.path.join(ROOT, path.lstrip('/'))
            if not os.path.isfile(f):
                self.send_error(404)
                return
            body = open(f, 'rb').read()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('x-tss-serialized', 'true')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if not os.path.splitext(path)[1]:
            f = os.path.join(ROOT, path.strip('/'), 'index.html')
            if os.path.isfile(f):
                self.path = '/' + (path.strip('/') + '/index.html').lstrip('/')

        return super().do_GET()

    def log_message(self, *a):
        pass


print('%s  →  http://127.0.0.1:%d/' % (SLUG, PORT))
ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
