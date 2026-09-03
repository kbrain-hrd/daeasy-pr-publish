"""post.md 를 daeasy 사이트 껍데기(헤더·푸터·CSS)에 끼워 넣어 게시된 모습을 미리 본다.

레이아웃은 운영 사이트의 교육후기 상세(/cases/<slug>)와 같은 구조다 —
`← 교육후기` 백링크, `날짜 · 기관` 메타, 본문, 우측 sticky 목차, 하단 교육 문의 CTA.

사용:
  uv run python scripts/preview.py <post.md> <출력이름> --date 2026.09.05 --org 부산시 --cover img/a.jpg --images img/b.png,img/c.jpg
결과: docs/preview/<출력이름>.html  (+ Edge 가 있으면 .png 스크린샷)

껍데기(daeasy.html)와 스타일(daeasy.css)은 없으면 사이트에서 자동으로 받아 온다.
이 둘이 없으면 클래스가 하나도 먹지 않아 화면이 통째로 무너지므로 매번 확인한다.
logo/ 와 fonts/PretendardVariable.woff2 는 처음 한 번 넣어 두면 된다.
"""

import argparse
import html
import io
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREVIEW = ROOT / "docs" / "preview"
EDGE = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


SITE = "https://daeasy.vercel.app"
SHELL_SOURCE = f"{SITE}/cases/2026-ai-champion-hackathon"  # 헤더·푸터·CSS 를 떠 올 실제 글


def ensure_shell_files() -> None:
    """껍데기(daeasy.html)와 스타일(daeasy.css)이 없으면 사이트에서 받아 둔다.

    이 둘이 없으면 클래스가 하나도 먹지 않아 화면이 통째로 무너진다.
    실제로 파일이 사라져 썸네일이 원본 크기로 펼쳐진 적이 있어, 매번 확인한다.
    """
    PREVIEW.mkdir(parents=True, exist_ok=True)
    page = PREVIEW / "daeasy.html"
    css = PREVIEW / "daeasy.css"
    if page.exists() and css.exists() and css.stat().st_size > 10_000:
        return

    def get(url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()

    try:
        if not page.exists():
            page.write_bytes(get(SHELL_SOURCE))
            print("껍데기(daeasy.html)를 사이트에서 받아 왔다.")
        if not css.exists() or css.stat().st_size <= 10_000:
            m = re.search(r'/_next/static/chunks/[^"?]+\.css', page.read_text(encoding="utf-8", errors="ignore"))
            if not m:
                raise RuntimeError("daeasy.html 에서 CSS 주소를 못 찾았다")
            css.write_bytes(get(SITE + m.group(0)))
            print("스타일(daeasy.css)을 사이트에서 받아 왔다.")
    except Exception as e:
        raise SystemExit(
            f"프리뷰 껍데기를 준비하지 못했다: {e}\n"
            f"{SHELL_SOURCE} 을 docs/preview/daeasy.html 로, 그 안의 CSS 를 daeasy.css 로 직접 받아 둔다."
        )


def shell():
    ensure_shell_files()
    src = io.open(PREVIEW / "daeasy.html", encoding="utf-8").read()
    header = re.search(r"<header.*?</header>", src, re.S).group(0)
    footer = re.search(r"<footer.*?</footer>", src, re.S).group(0)

    def fix(s):
        s = re.sub(r'src="(/[^"?]+)\?[^"]*"', r'src="\1"', s)
        return s.replace('src="/logo/', 'src="logo/').replace('src="/awards/', 'src="logo/')

    return fix(header), fix(footer)


# 본문에는 두되 목차에는 올리지 않는 소제목 (첨부 목록 등)
TOC_SKIP = {"자료", "첨부", "첨부 자료"}


def slugify(text: str) -> str:
    """사이트와 같은 규칙으로 소제목을 앵커 id 로 만든다 — 구두점 제거 후 공백을 - 로."""
    t = re.sub(r"""["'\u201c\u201d\u2018\u2019·,.!?()\[\]]""", "", text).strip()
    return re.sub(r"\s+", "-", t)


def stat_card(cells: list[str]) -> str:
    """`::수치 32명|참여 인원 · 29명|인증 통과::` → 수치 카드 한 줄.

    사진 대신 쓰는 그래픽이라 사진처럼 보이지 않게 사이트 색·서체만으로 그린다.
    """
    cols = []
    for cell in cells:
        num, _, label = cell.strip().partition("·")
        cols.append(
            '<div style="flex:1;padding:24px 20px;text-align:center;border-left:1px solid #f4f4f5">'
            f'<p style="margin:0;font-size:30px;font-weight:800;line-height:1;color:#18181b">{html.escape(num.strip())}</p>'
            f'<p style="margin:8px 0 0;font-size:12.5px;color:#71717a">{html.escape(label.strip())}</p>'
            "</div>"
        )
    return (
        '<div style="margin:40px 0;display:flex;overflow:hidden;border-radius:16px;background:#fafafa;border:1px solid #f4f4f5">'
        + "".join(cols)
        + "</div>"
    )


def quote_card(parts: list[str]) -> str:
    """`::인용 이건 내일 바로 써먹겠다|부산시 AI챔피언 그린 참여자::` → 인용문 카드."""
    text = parts[0].strip()
    who = parts[1].strip() if len(parts) > 1 else ""
    src = f'<p style="margin:20px 0 0;font-size:13px;color:#71717a">— {html.escape(who)}</p>' if who else ""
    return (
        '<figure style="margin:40px 0;border-radius:16px;background:#fafafa;border:1px solid #f4f4f5;padding:40px 32px">'
        '<p style="margin:0;font-size:26px;font-weight:800;line-height:1.45;color:#18181b">'
        f'&ldquo;{html.escape(text)}&rdquo;</p>{src}</figure>'
    )


def stage_image(path: str) -> str:
    """사진을 docs/preview/img/ 로 복사하고 상대 경로를 돌려준다.

    이미 img/ 안을 가리키거나 파일이 없으면 그대로 둔다.
    """
    if not path:
        return path
    src = Path(path)
    if not src.is_absolute():
        src = ROOT / path
    if not src.is_file():
        return path
    dst_dir = PREVIEW / "img"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
        shutil.copy2(src, dst)
    return f"img/{src.name}"


_OG_CACHE: dict[str, dict] = {}


def fetch_og(url: str) -> dict:
    """링크 카드에 쓸 og 정보를 읽어온다. 실패하면 도메인만 돌려준다.

    글별 og:image 를 안 주는 사이트가 많다 — 그런 곳은 기관 로고가 온다.
    네이버·카카오 공유 카드도 같은 값을 쓰므로 그대로 둔다.
    """
    if url in _OG_CACHE:
        return _OG_CACHE[url]
    host = re.sub(r"^www\.", "", urllib.parse.urlparse(url).netloc)
    info = {"title": url, "desc": "", "image": "", "host": host}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            page = r.read().decode("utf-8", "replace")
    except Exception:
        _OG_CACHE[url] = info
        return info

    def meta(prop: str) -> str:
        for pat in (
            r'<meta[^>]+(?:property|name)="' + prop + r'"[^>]+content="([^"]*)"',
            r'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="' + prop + r'"',
        ):
            m = re.search(pat, page, re.I)
            if m:
                return html.unescape(m.group(1)).strip()
        return ""

    title = meta("og:title")
    if not title:
        m = re.search(r"<title>(.*?)</title>", page, re.S | re.I)
        title = html.unescape(re.sub(r"\s+", " ", m.group(1))).strip() if m else url
    info["title"] = re.split(r"\s*\|\s*", title)[0]
    info["desc"] = meta("og:description")
    # og:image 는 사이트 공용 로고인 경우가 많다. 그 글에 실제로 쓰인 첫 사진을 먼저 찾는다.
    img = first_content_image(page, url) or meta("og:image")
    if img:
        info["image"] = urllib.parse.urljoin(url, img)
    _OG_CACHE[url] = info
    return info


# 본문 사진이 아닌 것들 — 로고·상장·아이콘·공용 og 이미지
_NOT_CONTENT = re.compile(r"(logo|favicon|opengraph-image|/awards/|sprite|icon)", re.I)


def first_content_image(page: str, base: str) -> str:
    """그 글에 실제로 쓰인 첫 번째 사진 주소를 찾는다. 없으면 빈 문자열.

    Next.js 는 본문을 RSC 페이로드에 담아 보내므로 <img> 태그만 봐서는 안 된다.
    이스케이프를 푼 뒤 이미지 확장자로 끝나는 주소를 순서대로 훑는다.
    """
    t = page.replace("\\u002F", "/").replace("\\/", "/").replace('\\"', '"')
    for m in re.finditer(r'["\'(](https?://[^"\'()\s]+?|/[^"\'()\s]+?)\.(jpe?g|png|webp)\b', t):
        u = m.group(1) + "." + m.group(2)
        if _NOT_CONTENT.search(u):
            continue
        return urllib.parse.urljoin(base, u)
    return ""


def stage_remote(url: str, name: str) -> str:
    """썸네일을 내려받아 docs/preview/img/ 에 두고 상대 경로를 돌려준다."""
    if not url:
        return ""
    ext = Path(urllib.parse.urlparse(url).path).suffix or ".jpg"
    dst = PREVIEW / "img" / f"{name}{ext}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                dst.write_bytes(r.read())
        except Exception:
            return ""
    return f"img/{dst.name}"


def link_card(url: str, n: int) -> str:
    """다른 교육후기로 넘어가는 작은 카드. 썸네일 + 제목 한 줄.

    본문 사진만큼 커지면 글의 흐름을 끊는다. 목록처럼 작게 둔다.
    """
    og = fetch_og(url)
    thumb = stage_remote(og["image"], f"ogcard-{n}")
    # daeasy.css 는 운영 사이트에서 컴파일된 Tailwind 빌드다. 사이트가 안 쓰는 유틸리티
    # 클래스(w-36·aspect-square·line-clamp 등)는 들어 있지 않아 적용되지 않는다.
    # 그래서 카드는 인라인 style 로 그린다 — 어떤 CSS 빌드가 깔려도 같게 나온다.
    fit = "contain" if _NOT_CONTENT.search(og["image"]) else "cover"
    box = (
        "width:150px;height:150px;flex:0 0 150px;overflow:hidden;"
        "border-radius:10px;background:#fafafa"
    )
    left = (
        f'<span style="{box};display:block">'
        f'<img src="{thumb}" alt="" style="width:100%;height:100%;object-fit:{fit};display:block"></span>'
        if thumb
        else f'<span style="{box};display:block"></span>'
    )
    return (
        f'<a href="{html.escape(url)}" target="_blank" rel="noopener" '
        'style="display:flex;align-items:center;gap:14px;padding:10px;border-radius:14px;'
        'border:1px solid #e4e4e7;text-decoration:none;color:inherit">'
        f"{left}"
        '<span style="min-width:0;flex:1 1 auto">'
        '<span style="display:block;font-size:15px;font-weight:700;line-height:1.4;color:#18181b">'
        f'{html.escape(og["title"])}</span>'
        '<span style="display:block;margin-top:8px;font-size:12px;color:#a1a1aa">'
        f'{html.escape(og["host"])}</span>'
        "</span></a>"
    )


# 본문은 인라인 style 로 그린다.
#
# `daeasy.css` 는 운영 사이트에서 컴파일된 Tailwind 빌드라 **사이트가 쓰지 않는 클래스는
# 아예 들어 있지 않다.** 확인해 보면 `my-4`·`leading-[1.85]`·`aspect-square` 가 없다.
# 그 클래스를 붙여봐야 아무 스타일도 안 먹어서 문단이 여백 없이 붙어 나온다 — 실제로 그랬다.
# 그래서 우리가 만들어 넣는 요소는 CSS 빌드에 기대지 않고 style 로 직접 그린다.
BODY_P = "margin:22px 0;font-size:16px;line-height:1.85;color:#3f3f46"
BODY_H2 = "margin:52px 0 14px;font-size:22px;font-weight:800;letter-spacing:-0.01em;color:#18181b;scroll-margin-top:96px"


def _bold(s: str) -> str:
    """**굵게** 를 <strong> 으로. 이스케이프 먼저 하고 치환한다."""
    return re.sub(
        r"\*\*(.+?)\*\*",
        r'<strong style="font-weight:700;color:#18181b">\1</strong>',
        html.escape(s),
    )


# 한국어는 조사가 앞말에 붙는다. `**…**` 뒤에 공백을 두고 조사를 쓰면
# 화면에서 조사가 떨어져 나와 어색해진다 (`'…사업' 을 추진하고`).
# 원고에 공백이 있어도 붙여서 내보낸다.
_JOSA = ("은", "는", "이", "가", "을", "를", "의", "에", "에서", "에게", "으로", "로",
         "와", "과", "도", "만", "까지", "부터", "라고", "이라고", "이었", "였", "입니다", "이라는", "라는")


def emphasize(text: str) -> str:
    """`**…**` 를 <strong> 으로 바꾸고, 뒤따르는 조사의 군더더기 공백을 없앤다."""
    out = re.sub(r"\*\*(.+?)\*\*", lambda m: f'<strong class="text-ink">{m.group(1)}</strong>', text)
    return re.sub(
        r"</strong>\s+(" + "|".join(_JOSA) + r")(?=[\s.,·)\]]|$)",
        lambda m: "</strong>" + m.group(1),
        out,
    )


def body_html(md: str, images: list[str]) -> tuple[str, list[str], list[tuple[str, str]]]:
    """post.md → (제목, 본문 HTML 조각들, 목차 [(id, 소제목)])"""
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    lines = md.strip().split("\n")
    title = lines[0].lstrip("# ").strip()
    out, toc, img_i = [], [], 0
    table_open = [False]  # 표가 열려 있는지 (여러 줄에 걸쳐 만든다)
    card_i = [0]   # 링크 카드 썸네일 파일 이름용 번호
    card_open = [False]  # 링크 카드 판이 열려 있는지
    quote_re = re.compile(r'^"(.+)"$')
    for ln in lines[1:]:
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("!["):
            if img_i < len(images):
                cap = re.match(r"!\[(.*?)\]", ln).group(1)
                out.append(
                    '<figure style="margin:40px 0">'
                    f'<img src="{images[img_i]}" alt="{html.escape(cap)}" '
                    'style="width:100%;display:block;border-radius:16px">'
                    '<figcaption style="margin-top:12px;font-size:13px;line-height:1.7;color:#71717a">'
                    f"{html.escape(cap)}</figcaption></figure>"
                )
                img_i += 1
            continue
        if ln.startswith("> "):
            # 인용 문단. 강조 카드(::인용 …::)와 달리 본문 흐름 안에 둔다.
            out.append(
                '<blockquote style="margin:24px 0;padding-left:20px;border-left:2px solid #d4d4d8;'
                'font-size:17px;line-height:1.8;color:#3f3f46">'
                + _bold(ln[2:].strip())
                + "</blockquote>"
            )
            continue
        if ln.startswith("## "):
            h = ln[3:].strip()
            if h in TOC_SKIP:
                out.append(
                    '<h2 style="margin:48px 0 12px;font-size:16px;font-weight:700;color:#18181b">'
                    f"{html.escape(h)}</h2>"
                )
                continue
            sid = slugify(h)
            toc.append((sid, h))
            out.append(f'<h2 id="{sid}" style="{BODY_H2}">{html.escape(h)}</h2>')
            continue
        if ln.startswith("|") and ln.endswith("|"):
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):  # |---|---| 구분줄
                continue
            head = not table_open[0]
            if head:
                out.append(
                    '<div style="margin:40px 0;overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:15px">'
                )
                table_open[0] = True
            tag = "th" if head else "td"
            cls = (
                'style="border-bottom:1px solid #e4e4e7;padding:10px 12px;text-align:left;font-weight:600;font-size:13px;color:#71717a"'
                if head
                else 'style="border-bottom:1px solid #f4f4f5;padding:10px 12px;text-align:left;color:#3f3f46"'
            )
            row = "".join(
                f"<{tag} {cls}>" + re.sub(r"\*\*(.+?)\*\*", r'<strong class="text-ink">\1</strong>', html.escape(c)) + f"</{tag}>"
                for c in cells
            )
            out.append(f"<tr>{row}</tr>")
            continue
        if card_open[0] and not ln.startswith("- "):
            out.append("</div>")
            card_open[0] = False
        if table_open[0]:
            out.append("</table></div>")
            table_open[0] = False
        if ln.startswith("::수치 "):
            out.append(stat_card(ln[len("::수치 "):].rstrip(":").split("|")))
            continue
        if ln.startswith("::인용 "):
            out.append(quote_card(ln[len("::인용 "):].rstrip(":").split("|")))
            continue
        if ln.startswith("- "):
            m = re.match(r"- \[(.+?)\]\((https?://\S+?)\)", ln) or re.match(r"- (https?://\S+)", ln)
            if m:
                # 링크 줄이 이어지면 한 판에 모아 2열로 깐다
                if not card_open[0]:
                    out.append('<div style="margin-top:20px;display:grid;grid-template-columns:1fr 1fr;gap:12px">')
                    card_open[0] = True
                card_i[0] += 1
                out.append(link_card(m.group(2) if m.lastindex == 2 else m.group(1), card_i[0]))
                continue
            m = re.match(r"- \[(.+?)\]\((.+?)\)", ln)
            out.append(
                f'<p class="mt-3 text-[15px] text-zinc-700">📎 <a class="font-semibold text-accent underline-offset-4 hover:underline" href="#">{html.escape(m.group(1) if m else ln[2:])}</a></p>'
            )
            continue
        if ln.startswith("📎"):
            out.append(f'<p style="margin:28px 0 0;font-size:15px;line-height:1.8;color:#3f3f46">{html.escape(ln)}</p>')
            continue
        if ln.startswith("관련 링크:"):
            out.append(f'<p style="margin:28px 0 0;font-size:14px;color:#71717a">{html.escape(ln)}</p>')
            continue
        if quote_re.match(ln):
            out.append(
                f'<blockquote style="margin:32px 0;padding-left:24px;border-left:4px solid #2563eb;font-size:22px;font-weight:700;line-height:1.5;color:#18181b">{html.escape(ln)}</blockquote>'
            )
            continue
        if ln.startswith("**") and ln.endswith("**"):
            out.append(f'<h3 style="margin:36px 0 10px;font-size:18px;font-weight:700;color:#18181b">{html.escape(ln.strip("*"))}</h3>')
            continue
        t = re.sub(r"\*\*(.+?)\*\*", r'<strong class="text-ink">\1</strong>', html.escape(ln))
        out.append(f'<p style="{BODY_P}">{t}</p>')
    if card_open[0]:
        out.append("</div>")
    if table_open[0]:
        out.append("</table></div>")
    return title, out, toc


TOC_LINK = (
    '<a href="#{sid}" data-toc="{sid}" class="block border-l-2 py-0.5 leading-snug transition-colors '
    'pl-3 text-[13px] border-transparent text-zinc-500 hover:text-ink">{label}</a>'
)

# 사이트 TableOfContents 가 쓰는 활성/비활성 클래스
TOC_ON = ["border-ink", "font-semibold", "text-ink"]
TOC_OFF = ["border-transparent", "text-zinc-500"]

HEART_SVG = (
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'class="flex-shrink-0 transition-colors"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 '
    '5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>'
)


def like_widget(wrap_class: str) -> str:
    """사이트의 LikeButton 과 같은 모양 — 우측 목차 아래(데스크톱)와 본문 아래(모바일) 두 곳에 들어간다.

    숫자는 버튼 옆이 아니라 안내 문구 아래에 `N개의 관심을 받았습니다` 로 붙고, 0 일 때는 나오지 않는다.
    """
    return (
        f'<div class="{wrap_class}"><div class="flex flex-col items-center gap-1.5">'
        '<div class="relative" data-hearts>'
        '<button type="button" data-like class="flex items-center gap-2 rounded-xl border px-4 py-2 '
        'transition-colors border-zinc-200 bg-paper hover:border-red-300 hover:bg-red-50">'
        + HEART_SVG
        + '<span class="text-sm font-semibold text-zinc-600">좋아요</span></button></div>'
        '<span class="text-[11px] text-zinc-400">마음에 드는 만큼 눌러주세요</span>'
        '<span data-like-count class="text-[11px] text-zinc-500" hidden></span>'
        "</div></div>"
    )


def toc_html(toc: list[tuple[str, str]]) -> str:
    items = [TOC_LINK.format(sid="top", label="제목")]
    items += [TOC_LINK.format(sid=sid, label=html.escape(h)) for sid, h in toc]
    items.append(TOC_LINK.format(sid="contact-cta", label="교육 문의"))
    return (
        '<aside class="hidden lg:block"><div class="sticky top-24 space-y-1">'
        '<p class="mb-3 text-[10px] font-bold uppercase tracking-[0.18em] text-zinc-500">목차</p>'
        + "".join(items)
        + like_widget("flex justify-center pt-6")
        + "</div></aside>"
    )


BEHAVIOR_JS = (
    """
<style>
@keyframes floatHeart {
  0%   { opacity: 1; transform: translateY(0) scale(1); }
  80%  { opacity: 0.6; }
  100% { opacity: 0; transform: translateY(-60px) scale(0.5); }
}
</style>
<script>
(function () {
  // ── 목차: 지금 읽고 있는 대목을 표시한다 (사이트 TableOfContents 와 같은 관찰 범위)
  var links = Array.prototype.slice.call(document.querySelectorAll("[data-toc]"));
  var ON = """
    + repr(TOC_ON)
    + """;
  var OFF = """
    + repr(TOC_OFF)
    + """;

  function activate(id) {
    links.forEach(function (a) {
      var on = a.dataset.toc === id;
      a.classList.remove.apply(a.classList, on ? OFF : ON);
      a.classList.add.apply(a.classList, on ? ON : OFF);
    });
  }

  // 사이트와 같은 관찰 범위 — 뷰포트 상단 20~30% 띠에 걸린 항목을 활성으로 삼는다
  var io = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (e) { if (e.isIntersecting) activate(e.target.id); });
    },
    { rootMargin: "-20% 0% -70% 0%" }
  );
  links.forEach(function (a) {
    var el = document.getElementById(a.dataset.toc);
    if (el) io.observe(el);
  });
  activate("top");

  // 목차 클릭은 사이트와 같이 부드럽게, 머리 위 여백 96px 을 두고 이동한다
  links.forEach(function (a) {
    a.addEventListener("click", function (ev) {
      ev.preventDefault();
      var el = document.getElementById(a.dataset.toc);
      if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 96, behavior: "smooth" });
    });
  });

  // ── 좋아요: 누른 만큼 올라가고 하트 다섯 개가 흩어져 떠오른다
  var HEART_PATH =
    "M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z";
  var likes = 0;

  function paint() {
    var head = document.getElementById("like-count");
    if (head) head.textContent = String(likes);
    document.querySelectorAll("[data-like-count]").forEach(function (el) {
      el.textContent = likes + "개의 관심을 받았습니다";
      el.hidden = likes === 0;
    });
  }

  function burst(box) {
    for (var i = 0; i < 5; i++) {
      (function () {
        var size = 10 + Math.random() * 10;
        var span = document.createElement("span");
        span.className = "pointer-events-none absolute bottom-full";
        span.style.left = "calc(50% + " + (Math.random() * 70 - 35) + "px)";
        span.style.opacity = "0";
        span.style.animation =
          "floatHeart " + (700 + Math.random() * 500) + "ms ease-out " + Math.random() * 200 + "ms forwards";
        span.innerHTML =
          '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="#ef4444">' +
          '<path d="' + HEART_PATH + '"></path></svg>';
        box.appendChild(span);
        setTimeout(function () { span.remove(); }, 1200);
      })();
    }
  }

  document.querySelectorAll("[data-like]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      likes += 1;
      paint();
      burst(btn.closest("[data-hearts]"));

      // 한 번이라도 누르면 모든 좋아요 버튼이 누른 상태가 된다 (사이트는 sessionStorage 로 기억)
      document.querySelectorAll("[data-like]").forEach(function (b) {
        b.classList.remove("border-zinc-200", "bg-paper", "hover:border-red-300", "hover:bg-red-50");
        b.classList.add("border-red-300", "bg-red-50", "hover:bg-red-100");
        var svg = b.querySelector("svg");
        svg.setAttribute("fill", "#ef4444");
        svg.setAttribute("stroke", "#ef4444");
        var label = b.querySelector("span");
        label.classList.remove("text-zinc-600");
        label.classList.add("text-red-500");
      });
    });
  });
})();
</script>"""
)


CTA = """<div id="contact-cta" class="mt-16 scroll-mt-24 rounded-2xl bg-zinc-50/70 p-8 ring-1 ring-zinc-100">
  <p class="text-[13px] font-bold uppercase tracking-[0.18em] text-accent">교육 문의</p>
  <h2 class="mt-3 text-[22px] font-extrabold tracking-[-0.01em] text-ink">비슷한 교육이 필요하신가요?</h2>
  <p class="mt-3 text-[15px] leading-[1.8] text-zinc-700">조직 규모와 학습 목표를 알려주시면 가장 가까운 커리큘럼을 제안드립니다.</p>
  <a class="mt-6 inline-flex items-center gap-2 rounded-md bg-ink px-5 py-3 text-[14px] font-bold text-white transition hover:bg-ink-hover" href="/contact">교육 문의하기 →</a>
</div>"""


def render(
    md_path: Path,
    name: str,
    date: str,
    cover: str,
    images: list[str],
    section: str = "교육후기",
    org: str = "",
) -> Path:
    header, footer = shell()
    # 사진은 어디에 있든 docs/preview/img/ 로 복사해 상대 경로로 건다.
    # 그대로 두면 html 이 docs/preview/ 에 있어 패키지 폴더 경로가 깨진다.
    cover = stage_image(cover)
    images = [stage_image(p) for p in images]
    title, body, toc = body_html(io.open(md_path, encoding="utf-8").read(), images)

    meta = f'<span class="ml-2 text-zinc-400">·</span><span class="ml-2 text-zinc-700">{html.escape(org)}</span>' if org else ""
    # 대표 사진이 없으면 커버 자리를 비워 둔다 (빈 회색 판을 깔지 않는다)
    cover_html = (
        f'<div style="margin:40px 0;overflow:hidden;border-radius:16px;background:#f4f4f5"><img src="{cover}" alt="" style="width:100%;aspect-ratio:16/9;object-fit:cover;display:block"></div>'
        if cover
        else ""
    )

    page = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><title>{html.escape(title)} | DAEASY(데이지)</title>
<link rel="stylesheet" href="daeasy.css">
<style>@font-face{{font-family:"pretendard";src:url("fonts/PretendardVariable.woff2") format("woff2");font-weight:45 920}}
body{{font-family:"pretendard","Pretendard","Malgun Gothic",sans-serif}}
.anim-page-fade-up,.anim-cover-scale-fade{{opacity:1;transform:none;animation:none}}
figure img{{max-width:100%;display:block}}</style>
</head><body class="min-h-full flex flex-col">{header}
<main class="flex-1">
<article class="mx-auto max-w-6xl px-6 py-16 lg:py-20 anim-page-fade-up">
  <a class="text-[13px] font-bold uppercase tracking-[0.18em] text-zinc-500 transition hover:text-zinc-900" href="/cases">← {section}</a>
  <div class="mt-8 grid grid-cols-1 gap-12 lg:grid-cols-[1fr_200px]">
    <div class="min-w-0">
      <header id="top" class="scroll-mt-24">
        <p class="text-[12.5px] font-semibold tracking-[0.04em] text-zinc-500">{date}{meta}</p>
        <h1 class="mt-4 text-[32px] font-extrabold leading-[1.18] tracking-[-0.02em] text-ink sm:text-[40px]">{html.escape(title)}</h1>
        <p class="mt-3 text-[12px] text-zinc-500">조회 0회<span class="ml-2">· 좋아요 <span id="like-count">0</span></span></p>
      </header>
      {cover_html}
      <div class="mt-12">{''.join(body)}</div>
      {CTA}
      {like_widget("mt-10 flex justify-center lg:hidden")}
    </div>
    {toc_html(toc)}
  </div>
</article>
</main>{footer}{BEHAVIOR_JS}</body></html>"""

    out = PREVIEW / f"{name}.html"
    io.open(out, "w", encoding="utf-8").write(page)
    return out


def screenshot(html_path: Path, height: int = 3400) -> Path | None:
    edge = next((e for e in EDGE if Path(e).exists()), None)
    if not edge:
        return None
    png = html_path.with_suffix(".png")
    url = "file:///" + str(html_path).replace("\\", "/")
    subprocess.run(
        [edge, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size=1440,{height}",
         "--virtual-time-budget=4000", f"--screenshot={png}", url],
        capture_output=True, timeout=60,
    )
    return png if png.exists() else None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("post")
    ap.add_argument("name")
    ap.add_argument("--date", default="")
    ap.add_argument("--org", default="")
    ap.add_argument("--cover", default="")
    ap.add_argument("--images", default="")
    ap.add_argument("--section", default="교육후기")
    a = ap.parse_args()
    imgs = [s for s in a.images.split(",") if s]
    # 대표 사진을 본문에 또 깔면 같은 사진이 두 번 나온다
    if a.cover and a.cover in imgs:
        raise SystemExit(
            f"대표 사진을 본문에도 넣었다: {a.cover} / "
            "--images 에서 빼거나 다른 사진을 대표로 고른다."
        )
    out = render(Path(a.post), a.name, a.date, a.cover, imgs, a.section, a.org)
    print("html:", out)
    png = screenshot(out)
    print("png:", png)
