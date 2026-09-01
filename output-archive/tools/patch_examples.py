"""화면의 추천 질문 목록을 녹화한 질문으로 바꾼다.

바꾸지 않으면 방문자에게 원래 예시 3개만 보이고, 나머지 녹화분은
직접 타이핑하지 않는 한 눌러볼 방법이 없다.

번들(assets/*.js)과 서버가 그려둔 HTML **양쪽 다** 바꿔야 한다.
한쪽만 바꾸면 React 가 하이드레이션 불일치 오류를 낸다.

사용:  uv run python output-archive/tools/patch_examples.py lawfind
"""
import glob
import html as html_mod
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = json.load(io.open(os.path.join(HERE, '..', 'sites.json'), encoding='utf-8'))

BUNDLE_RE = re.compile(r'examples:\[(?:`[^`]*`,?)+\]')
CHIP_RE = re.compile(r'<button class="text-left text-sm px-4 py-3[^"]*">[^<]*</button>')


def patch_bundle(root, questions):
    for path in glob.glob(os.path.join(root, 'assets', '*.js')):
        src = io.open(path, encoding='utf-8', errors='ignore').read()
        if not BUNDLE_RE.search(src):
            continue
        new = 'examples:[' + ','.join('`' + q + '`' for q in questions) + ']'
        io.open(path, 'w', encoding='utf-8').write(BUNDLE_RE.sub(new, src, count=1))
        return os.path.basename(path)
    return None


def patch_html(root, questions):
    done = []
    for path in glob.glob(os.path.join(root, 'index.html')) + \
                glob.glob(os.path.join(root, '*', 'index.html')):
        src = io.open(path, encoding='utf-8', errors='ignore').read()
        chips = CHIP_RE.findall(src)
        if not chips:
            continue
        # 첫 칩의 class 를 그대로 재사용해 원래 모양을 유지한다
        cls = re.search(r'class="([^"]*)"', chips[0]).group(1)
        rendered = ''.join(
            '<button class="%s">%s</button>' % (cls, html_mod.escape(q, quote=False))
            for q in questions)
        src = src.replace(''.join(chips), rendered, 1)
        io.open(path, 'w', encoding='utf-8').write(src)
        done.append(os.path.relpath(path, root).replace(os.sep, '/'))
    return done


def main(slug):
    site = CONFIG[slug]
    questions = site['record']['questions']
    root = os.path.join(HERE, '..', 'sites', slug)

    bundle = patch_bundle(root, questions)
    print('번들 %s' % (bundle or '— 목록을 찾지 못함'))
    for name in patch_html(root, questions):
        print('화면 %s' % name)
    print('추천 질문 %d개로 교체' % len(questions))


if __name__ == '__main__':
    main(sys.argv[1])
