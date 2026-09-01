"""보관본에 남은 lovable 흔적을 걷어낸다.

정식 게시용이므로 원본 제작 도구의 배지·추적 스크립트는 남기지 않는다.
바깥으로 나가는 요청을 없앤다는 보관 취지에도 맞다.

지우는 것:
  1. <aside id="lovable-badge"> 와 그 전용 <style> 블록 — 화면 오른쪽 아래 "Edit with Lovable"
  2. /~flock.js 스크립트 — lovable 분석용. 보관본에서는 404 가 날 뿐이다
  3. og:image / twitter:image 가 가리키는 lovable 이미지 서버 — 내려받아 함께 보관한다

사용:  uv run python output-archive/tools/strip_lovable.py singoai
"""
import glob
import io
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = json.load(io.open(os.path.join(HERE, '..', 'sites.json'), encoding='utf-8'))

UA = 'daeasy-archive/1.0 (educational output preservation; ohjieun25@daeasy.co.kr)'

FLOCK_RE = re.compile(r'<script[^>]*src="/~flock\.js"[^>]*>\s*</script>')
STYLE_RE = re.compile(r'<style[^>]*>(?:(?!</style>).)*?#lovable-badge(?:(?!</style>).)*?</style>', re.S)
# 배지를 숨기거나 클릭을 붙이는 인라인 스크립트
BADGE_JS_RE = re.compile(r'<script(?![^>]*\ssrc=)[^>]*>(?:(?!</script>).)*?lovable-badge(?:(?!</script>).)*?</script>', re.S)
PREVIEW_RE = re.compile(r'(content=")(https?://[^"]*(?:lovable|r2\.dev)[^"]*\.(?:png|jpg|jpeg|webp))(")', re.I)


"""여는 태그가 여러 줄에 걸쳐 있다 — <aside\n\tid="lovable-badge" ... 형태다."""
BADGE_OPEN_RE = re.compile(r'<aside\s[^>]*id="lovable-badge"[^>]*>', re.S)


def drop_badge(html):
    """<aside id="lovable-badge"> 요소를 통째로 지운다."""
    m = BADGE_OPEN_RE.search(html)
    if not m:
        return html, False
    end = html.find('</aside>', m.end())
    if end == -1:
        return html, False
    return html[:m.start()] + html[end + len('</aside>'):], True


def fetch_preview(url, dest):
    req = urllib.request.Request(url, headers={'user-agent': UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    open(dest, 'wb').write(body)
    return len(body)


def main(slug):
    root = os.path.join(HERE, '..', 'sites', slug)
    preview_path = os.path.join(root, 'offline', 'preview.png')
    counts = {'badge': 0, 'badge_js': 0, 'flock': 0, 'style': 0, 'preview': 0}
    grabbed = os.path.exists(preview_path)

    targets = sorted(glob.glob(os.path.join(root, 'index.html')) +
                     glob.glob(os.path.join(root, '*', 'index.html')))

    for path in targets:
        html = io.open(path, encoding='utf-8', errors='ignore').read()
        before = html

        html, hit = drop_badge(html)
        counts['badge'] += 1 if hit else 0

        html, n = FLOCK_RE.subn('', html)
        counts['flock'] += n

        html, n = STYLE_RE.subn('', html)
        counts['style'] += n

        html, n = BADGE_JS_RE.subn('', html)
        counts['badge_js'] += n

        for m in set(PREVIEW_RE.findall(html)):
            url = m[1]
            if not grabbed:
                try:
                    size = fetch_preview(url, preview_path)
                    print('미리보기 이미지 내려받음 (%d bytes)' % size)
                except Exception as err:
                    print('!! 미리보기 이미지 실패:', err)
                    break
                grabbed = True
            html = html.replace(url, '/offline/preview.png')
            counts['preview'] += 1

        if html != before:
            io.open(path, 'w', encoding='utf-8').write(html)

    print('%s — 배지 %d · 배지스크립트 %d · 추적스크립트 %d · 배지스타일 %d · 미리보기링크 %d 처리'
          % (slug, counts['badge'], counts['badge_js'], counts['flock'],
             counts['style'], counts['preview']))


if __name__ == '__main__':
    main(sys.argv[1])
