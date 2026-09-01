"""post.md 를 daeasy 사이트 껍데기(헤더·푸터·CSS)에 끼워 넣어 게시된 모습을 미리 본다.

사용:
  uv run python scripts/preview.py <post.md> <출력이름> --date 2026.09.05 --cover img/a.jpg --images img/b.png,img/c.jpg
결과: docs/preview/<출력이름>.html  (+ Edge 가 있으면 .png 스크린샷)

사전 준비(최초 1회): docs/preview/ 에 daeasy.css, logo/, fonts/PretendardVariable.woff2, 그리고 헤더·푸터 원본 daeasy.html
"""

import argparse
import html
import io
import re
import shutil
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


def body_html(md: str, images: list[str]) -> tuple[str, list[str]]:
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    lines = md.strip().split("\n")
    title = lines[0].lstrip("# ").strip()
    out, img_i = [], 0
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
            out.append(f'<h2 class="mt-12 text-[22px] font-extrabold tracking-[-0.01em] text-ink">{html.escape(ln[3:])}</h2>')
            continue
        if ln.startswith("- "):
            m = re.match(r"- \[(.+?)\]\((.+?)\)", ln)
            out.append(f'<p class="mt-3 text-[15px] text-zinc-700">📎 <a class="font-semibold text-accent underline-offset-4 hover:underline" href="#">{html.escape(m.group(1) if m else ln[2:])}</a></p>')
            continue
        if ln.startswith("📎"):
            out.append(f'<p class="mt-8 text-[15px] text-zinc-700">{html.escape(ln)}</p>')
            continue
        if ln.startswith("관련 링크:"):
            out.append(f'<p class="mt-8 text-[14px] text-zinc-500">{html.escape(ln)}</p>')
            continue
        if quote_re.match(ln):
            out.append(f'<blockquote class="my-8 pl-6 text-[22px] font-bold leading-[1.5] tracking-[-0.01em] text-ink" style="border-left:4px solid #2563eb">{html.escape(ln)}</blockquote>')
            continue
        if ln.startswith("**") and ln.endswith("**"):
            out.append(f'<h3 class="mt-10 text-[18px] font-bold text-ink">{html.escape(ln.strip("*"))}</h3>')
            continue
        t = re.sub(r"\*\*(.+?)\*\*", r'<strong class="text-ink">\1</strong>', html.escape(ln))
        out.append(f'<p class="mt-6 text-[17px] leading-[1.9] text-zinc-700">{t}</p>')
    return title, out


def render(md_path: Path, name: str, date: str, cover: str, images: list[str], section: str = "교육후기") -> Path:
    header, footer = shell()
    title, body = body_html(io.open(md_path, encoding="utf-8").read(), images)
    cover_html = (
        f'<div class="aspect-[16/9] w-full overflow-hidden rounded-2xl bg-zinc-100 ring-1 ring-zinc-100"><img src="{cover}" alt="" class="h-full w-full object-cover"></div>'
        if cover
        else '<div class="aspect-[16/9] w-full rounded-2xl bg-zinc-200"></div>'
    )
    page = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><title>{html.escape(title)} | daeasy</title>
<link rel="stylesheet" href="daeasy.css">
<style>@font-face{{font-family:"pretendard";src:url("fonts/PretendardVariable.woff2") format("woff2");font-weight:45 920}}
body{{font-family:"pretendard","Pretendard","Malgun Gothic",sans-serif}} .anim-page-fade-up{{opacity:1;transform:none;animation:none}}
figure img{{max-width:100%;display:block}}</style>
</head><body class="min-h-full flex flex-col">{header}
<main class="flex-1">
<section class="bg-white"><div class="mx-auto max-w-[1280px] px-6 pb-10 pt-20 lg:px-10 lg:pb-14 lg:pt-24 anim-page-fade-up">
  <p class="text-[13px] font-bold uppercase tracking-[0.18em] text-zinc-500">{section}</p>
  <h1 class="mt-5 max-w-4xl text-[36px] font-extrabold leading-[1.15] tracking-[-0.025em] text-ink sm:text-[44px] lg:text-[52px]">{html.escape(title)}</h1>
  <p class="mt-6 text-[12.5px] font-semibold tracking-[0.04em] text-zinc-500">{date}</p>
</div></section>
<section class="border-t border-zinc-100 bg-zinc-50/70"><div class="mx-auto max-w-[1280px] px-6 py-14 lg:px-10 lg:py-16">
  <div class="mx-auto max-w-3xl">{cover_html}<div class="mt-10">{''.join(body)}</div></div>
</div></section>
</main>{footer}</body></html>"""
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
    ap.add_argument("--cover", default="")
    ap.add_argument("--images", default="")
    ap.add_argument("--section", default="교육후기")
    a = ap.parse_args()
    imgs = [s for s in a.images.split(",") if s]
    out = render(Path(a.post), a.name, a.date, a.cover, imgs, a.section)
    print("html:", out)
    png = screenshot(out)
    print("png:", png)
