"""원본이 살아 있을 때 예시 질문의 답변을 녹화한다.

AI 답변은 미리 만들어둘 수 없다 — 질문이 들어와야 그때 생성된다.
그래서 보관본에서는 자유 질문이 동작하지 않는다. 대신 원본이 살아 있는
동안 대표 질문 몇 개를 실제로 물어보고 그 답을 저장해두면, 보관본에서
그 질문들에는 진짜 답이 나온다 (offline/replay.js 가 되돌려준다).

요청 본문은 질문 텍스트만 담은 단순한 구조라 그대로 재현할 수 있다.
질문 하나가 요청 하나에 대응한다.

sites.json 의 record 항목을 읽는다:
  "record": { "fn": "<서버함수 id>", "questions": ["...", ...] }

사용:  uv run python output-archive/tools/record.py lawfind
"""
import io
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = json.load(io.open(os.path.join(HERE, '..', 'sites.json'), encoding='utf-8'))

UA = 'daeasy-archive/1.0 (educational output preservation; ohjieun25@daeasy.co.kr)'


def build_body(question):
    """앱이 실제로 보내는 요청 본문. 새 대화라 history 는 비어 있다."""
    return json.dumps({
        't': {'t': 10, 'i': 0, 'p': {'k': ['data'], 'v': [
            {'t': 10, 'i': 1, 'p': {'k': ['question', 'history'], 'v': [
                {'t': 1, 's': question},
                {'t': 9, 'i': 2, 'a': [], 'o': 0},
            ]}, 'o': 0},
        ]}, 'o': 0},
        'f': 63,
        'm': [],
    }, ensure_ascii=False)


def ask(origin, fn, question):
    req = urllib.request.Request(
        origin + '/_serverFn/' + fn,
        data=build_body(question).encode('utf-8'),
        method='POST',
        headers={
            'user-agent': UA,
            'x-tsr-serverFn': 'true',
            'content-type': 'application/json',
            'accept': 'application/x-tss-framed, application/x-ndjson, application/json',
            'referer': origin + '/',
        })
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode('utf-8')


def main(slug):
    site = CONFIG[slug]
    rec = site.get('record')
    if not rec:
        raise SystemExit('sites.json 에 record 설정이 없습니다: ' + slug)

    out = os.path.join(HERE, '..', 'sites', slug, 'offline', 'recorded.js')
    table = {}

    for i, q in enumerate(rec['questions'], 1):
        try:
            resp = ask(site['origin'], rec['fn'], q)
        except Exception as err:
            print('%2d. 실패 (%s) — %s' % (i, err, q))
            continue
        table[q] = resp
        print('%2d. %6d bytes  %s' % (i, len(resp), q))

    payload = {rec['fn']: table}
    io.open(out, 'w', encoding='utf-8').write(
        '/* 원본에서 녹화한 예시 질문 답변. tools/record.py 가 만든다. 손으로 고치지 않는다. */\n'
        'window.__RECORDED=' + json.dumps(payload, ensure_ascii=False) + ';\n')

    print('\n%d개 중 %d개 녹화 -> offline/recorded.js (%.0fKB)'
          % (len(rec['questions']), len(table), os.path.getsize(out) / 1024))


    print('화면의 추천 질문 목록도 바꾸려면: '
          'uv run python output-archive/tools/patch_examples.py %s' % slug)


if __name__ == '__main__':
    main(sys.argv[1])
