"""post.md 를 daeasy 사이트 껍데기(헤더·푸터·CSS)에 끼워 넣어 게시된 모습을 미리 본다.

레이아웃은 운영 사이트의 교육후기 상세(/cases/<slug>)와 같은 구조다 —
`← 교육후기` 백링크, `날짜 · 기관` 메타, 본문, 우측 sticky 목차, 하단 교육 문의 CTA.

사용:
  uv run python scripts/preview.py <post.md> <출력이름> --date 2026.09.05 --org 부산시 --cover img/a.jpg --images img/b.png,img/c.jpg
결과: docs/preview/<출력이름>.html  (+ Edge 가 있으면 .png 스크린샷)

사전 준비(최초 1회): docs/preview/ 에 daeasy.css, logo/, fonts/PretendardVariable.woff2, 그리고 헤더·푸터 원본 daeasy.html
"""

import argparse
import html
import io
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREVIEW = ROOT / "docs" / "preview"
EDGE = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def shell():
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
            '<div class="flex-1 px-5 py-6 text-center">'
            f'<p class="text-[30px] font-extrabold leading-none tracking-[-0.02em] text-ink">{html.escape(num.strip())}</p>'
            f'<p class="mt-2 text-[12.5px] text-zinc-500">{html.escape(label.strip())}</p>'
            "</div>"
        )
    return (
        '<div class="mt-10 flex divide-x divide-zinc-100 overflow-hidden rounded-2xl bg-zinc-50/70 ring-1 ring-zinc-100">'
        + "".join(cols)
        + "</div>"
    )


def quote_card(parts: list[str]) -> str:
    """`::인용 이건 내일 바로 써먹겠다|부산시 AI챔피언 그린 참여자::` → 인용문 카드."""
    text = parts[0].strip()
    who = parts[1].strip() if len(parts) > 1 else ""
    src = f'<p class="mt-5 text-[13px] text-zinc-500">— {html.escape(who)}</p>' if who else ""
    return (
        '<figure class="mt-10 rounded-2xl bg-zinc-50/70 px-8 py-10 ring-1 ring-zinc-100">'
        '<p class="text-[26px] font-extrabold leading-[1.45] tracking-[-0.015em] text-ink">'
        f'&ldquo;{html.escape(text)}&rdquo;</p>{src}</figure>'
    )


def body_html(md: str, images: list[str]) -> tuple[str, list[str], list[tuple[str, str]]]:
    """post.md → (제목, 본문 HTML 조각들, 목차 [(id, 소제목)])"""
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    lines = md.strip().split("\n")
    title = lines[0].lstrip("# ").strip()
    out, toc, img_i = [], [], 0
    quote_re = re.compile(r'^"(.+)"$')
    for ln in lines[1:]:
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("!["):
            if img_i < len(images):
                cap = re.match(r"!\[(.*?)\]", ln).group(1)
                out.append(
                    f'<figure class="mt-10"><img src="{images[img_i]}" alt="{html.escape(cap)}" class="w-full rounded-2xl ring-1 ring-zinc-100">'
                    f'<figcaption class="mt-3 text-[13px] text-zinc-500">{html.escape(cap)}</figcaption></figure>'
                )
                img_i += 1
            continue
        if ln.startswith("## "):
            h = ln[3:].strip()
            if h in TOC_SKIP:
                out.append(f'<h2 class="mt-12 text-[16px] font-bold text-ink">{html.escape(h)}</h2>')
                continue
            sid = slugify(h)
            toc.append((sid, h))
            out.append(
                f'<h2 id="{sid}" class="scroll-mt-24 mt-12 text-[22px] font-extrabold tracking-[-0.01em] text-ink">{html.escape(h)}</h2>'
            )
            continue
        if ln.startswith("::수치 "):
            out.append(stat_card(ln[len("::수치 "):].rstrip(":").split("|")))
            continue
        if ln.startswith("::인용 "):
            out.append(quote_card(ln[len("::인용 "):].rstrip(":").split("|")))
            continue
        if ln.startswith("- "):
            m = re.match(r"- \[(.+?)\]\((.+?)\)", ln)
            out.append(
                f'<p class="mt-3 text-[15px] text-zinc-700">📎 <a class="font-semibold text-accent underline-offset-4 hover:underline" href="#">{html.escape(m.group(1) if m else ln[2:])}</a></p>'
            )
            continue
        if ln.startswith("📎"):
            out.append(f'<p class="mt-8 text-[15px] text-zinc-700">{html.escape(ln)}</p>')
            continue
        if ln.startswith("관련 링크:"):
            out.append(f'<p class="mt-8 text-[14px] text-zinc-500">{html.escape(ln)}</p>')
            continue
        if quote_re.match(ln):
            out.append(
                f'<blockquote class="my-8 pl-6 text-[22px] font-bold leading-[1.5] tracking-[-0.01em] text-ink" style="border-left:4px solid #2563eb">{html.escape(ln)}</blockquote>'
            )
            continue
        if ln.startswith("**") and ln.endswith("**"):
            out.append(f'<h3 class="mt-10 text-[18px] font-bold text-ink">{html.escape(ln.strip("*"))}</h3>')
            continue
        t = re.sub(r"\*\*(.+?)\*\*", r'<strong class="text-ink">\1</strong>', html.escape(ln))
        out.append(f'<p class="mt-6 text-[17px] leading-[1.9] text-zinc-700">{t}</p>')
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
    title, body, toc = body_html(io.open(md_path, encoding="utf-8").read(), images)

    meta = f'<span class="ml-2 text-zinc-400">·</span><span class="ml-2 text-zinc-700">{html.escape(org)}</span>' if org else ""
    # 대표 사진이 없으면 커버 자리를 비워 둔다 (빈 회색 판을 깔지 않는다)
    cover_html = (
        f'<div class="mt-10 overflow-hidden rounded-2xl bg-zinc-100"><img src="{cover}" alt="" class="aspect-[16/9] w-full object-cover"></div>'
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
    out = render(Path(a.post), a.name, a.date, a.cover, imgs, a.section, a.org)
    print("html:", out)
    png = screenshot(out)
    print("png:", png)
