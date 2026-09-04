"""daeasy 사이트(교육후기) 발행.

교육후기는 저장소 안의 파일이 아니라 **Supabase `cases` 테이블의 레코드**다.
그래서 저장소에 커밋하는 방식이 아니라 어드민 API 두 개를 쓴다.

    POST /api/admin/upload   multipart  → 이미지 한 장을 올리고 공개 URL 을 받는다
    POST /api/admin/cases    json       → 글 한 편을 만든다

둘 다 어드민 로그인 쿠키를 요구한다(`getCurrentUser`). 그래서 네이버와 같은 방식으로
사람이 한 번 로그인하고, 그 세션을 재사용한다. 비밀번호는 코드에도 설정에도 두지 않는다.

**사이트 저장소(SSEUNGSSEUNGWOO/daeasy)에는 아무것도 쓰지 않는다.** 구조를 읽어 맞춘 것뿐이다.
"""

import html
import json
import mimetypes
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / ".daeasy-profile"
SESSION = ROOT / ".daeasy-session.json"  # 로그인 쿠키. 자격증명이므로 저장소에 올리지 않는다.

SITE = "https://daeasy.co.kr"
ADMIN_URL = f"{SITE}/admin/cases"
UPLOAD_API = f"{SITE}/api/admin/upload"
CASES_API = f"{SITE}/api/admin/cases"

# 사이트는 description 을 sanitize-html 로 걸러 렌더한다(frontend/src/lib/sanitize.ts).
# 허용 속성이 class/title/data-* 뿐이라 **style 은 통째로 지워진다.**
# 그래서 여기서는 인라인 스타일을 쓰지 않는다 — 간격·글자 크기는 사이트의 prose 가 준다.
# (프리뷰 HTML 은 사이트 CSS 가 없으니 style 을 박지만, 그건 확인용이고 이쪽이 본물이다.)
ALLOWED = {"h2", "h3", "p", "br", "hr", "ul", "ol", "li", "strong", "em",
           "blockquote", "a", "img", "figure", "figcaption"}


def _browser(p, headless: bool):
    PROFILE.mkdir(exist_ok=True)
    return p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE),
        headless=headless,
        viewport={"width": 1440, "height": 900},
    )


def login(timeout_min: int = 10) -> bool:
    """어드민 로그인 창을 띄우고, 사람이 로그인하는 동안 세션을 저장한다."""
    with sync_playwright() as p:
        ctx = _browser(p, headless=False)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto(ADMIN_URL)
        print(f"브라우저에서 daeasy 어드민에 로그인해 주세요. (최대 {timeout_min}분)")
        print("로그인이 끝나면 창을 닫지 말고 그대로 두시면 됩니다.")
        for _ in range(timeout_min * 12):
            pg.wait_for_timeout(5000)
            try:
                ctx.storage_state(path=str(SESSION))
            except Exception:
                pass
        ctx.close()
    return SESSION.exists()


# ---------------------------------------------------------------- 본문 변환

_QUOTE = re.compile(r"^::인용\s*(.+?)\s*::$")
_STATS = re.compile(r"^::수치\s*(.+?)\s*::$")
_IMG = re.compile(r"^!\[(.*?)\]\((.+?)\)$")
_URL = re.compile(r"^https?://\S+$")
_RULE = re.compile(r"^[─—\-_]{3,}$")


def _link(url: str) -> str:
    u = html.escape(url)
    return f'<a href="{u}" target="_blank" rel="noopener">{u}</a>'


def _inline(s: str) -> str:
    """굵게만 처리한다. 나머지는 그대로 이스케이프한다."""
    out = html.escape(s)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)


def to_html(md: str, upload) -> tuple[str, str | None]:
    """post.md 를 사이트용 HTML 로 옮긴다. (본문, 대표이미지 URL)

    `upload(경로) -> URL` 을 받아 이미지를 올린다. 본문 첫 이미지가 대표 사진이 된다 —
    사이트가 대표 사진을 상단에 따로 보여주므로 그 이미지는 본문에서 뺀다 (중복 노출 방지).
    """
    body: list[str] = []
    thumb: str | None = None
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)

    for block in md.split("\n\n"):
        s = block.strip()
        if not s or s.startswith("# "):
            continue

        if s.startswith("## "):
            body.append(f"<h2>{_inline(s[3:].strip())}</h2>")
            continue

        m = _IMG.match(s)
        if m:
            cap, path = m.group(1), m.group(2)
            url = upload(path)
            if not url:
                continue
            if thumb is None:
                thumb = url
                continue
            fig = f'<figure><img src="{html.escape(url)}" alt="{html.escape(cap)}">'
            if cap:
                fig += f"<figcaption>{_inline(cap)}</figcaption>"
            body.append(fig + "</figure>")
            continue

        m = _QUOTE.match(s)
        if m:
            parts = [x.strip() for x in m.group(1).split("|")]
            q = f"<blockquote><p>{_inline(parts[0])}</p>"
            if len(parts) > 1:
                q += f"<p><em>{_inline(parts[1])}</em></p>"
            body.append(q + "</blockquote>")
            continue

        m = _STATS.match(s)
        if m:
            items = "".join(
                f"<li>{_inline(x.strip())}</li>" for x in m.group(1).split("|") if x.strip()
            )
            body.append(f"<ul>{items}</ul>")
            continue

        if _RULE.match(s):
            body.append("<hr>")
            continue

        # 관련 글 목록 — `- https://…` 줄만 모여 있는 블록
        lines = [ln.strip() for ln in s.split("\n") if ln.strip()]
        if lines and all(ln.startswith("- ") and _URL.match(ln[2:]) for ln in lines):
            body.append("<ul>" + "".join(f"<li>{_link(ln[2:])}</li>" for ln in lines) + "</ul>")
            continue

        # URL 만 있는 문단(줄마다 URL) — 글 쪽이 `- ` 없이 쓰는 경우도 링크로
        if lines and all(_URL.match(ln) for ln in lines):
            body.append("<p>" + "<br>".join(_link(ln) for ln in lines) + "</p>")
            continue

        body.append("<p>" + "<br>".join(_inline(ln) for ln in lines) + "</p>")

    return "".join(body), thumb


def _title_of(md: str) -> str:
    for ln in md.splitlines():
        if ln.startswith("# "):
            return ln[2:].strip()
    return ""


def _summary_of(md: str, limit: int = 200) -> str:
    """목록 카드·메타 설명용 요약 — 본문 첫 글 문단(제목·사진·소제목·요약박스·URL 제외).

    어드민에서 손으로 쓴 글은 사람이 요약을 넣지만, 파이프라인 글은 meta.json 에 요약이
    없어 카드가 비었다. 글 첫 문단이 "언제·어디서·누가·무엇을" 이라 그대로 쓴다.
    """
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    for block in md.split("\n\n"):
        s = block.strip()
        if not s or s.startswith("#") or s.startswith("::") or s.startswith("!["):
            continue
        lines = [ln.strip() for ln in s.split("\n") if ln.strip()]
        if _RULE.match(s) or all(_URL.match(ln.lstrip("- ")) for ln in lines):
            continue
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", " ".join(lines))
        if len(text) <= limit:
            return text
        cut = text.rfind(". ", 0, limit)
        return text[: cut + 1] if cut > 0 else text[: limit - 1] + "…"
    return ""


# ---------------------------------------------------------------- 발행


def publish(slug_dir: Path, live: bool = False) -> None:
    """out/<slug>/post.md 를 사이트 교육후기로 만든다.

    기본은 status=draft — 어드민에서 눈으로 확인한 뒤 공개한다.
    `live=True` 면 곧바로 published 로 넣는다.
    """
    if not SESSION.exists():
        raise SystemExit("로그인 세션이 없습니다. 먼저 `uv run prpub site-login` 을 실행하세요.")

    md = (slug_dir / "post.md").read_text(encoding="utf-8")
    meta = json.loads((slug_dir / "meta.json").read_text(encoding="utf-8"))
    title = _title_of(md)
    if not title:
        raise SystemExit("post.md 맨 위에 `# 제목` 이 없습니다.")

    with sync_playwright() as p:
        ctx = _browser(p, headless=True)
        req = ctx.request
        uploaded: dict[str, str] = {}

        def upload(rel: str) -> str | None:
            if rel in uploaded:
                return uploaded[rel]
            f = (slug_dir / rel).resolve()
            if not f.exists():
                print(f"  건너뜀 — 파일 없음: {rel}")
                return None
            mime = mimetypes.guess_type(f.name)[0] or "image/jpeg"
            r = req.post(UPLOAD_API, multipart={
                "file": {"name": f.name, "mimeType": mime, "buffer": f.read_bytes()}
            })
            if not r.ok:
                raise SystemExit(f"이미지 업로드 실패 ({r.status}): {r.text()[:200]}")
            url = r.json()["url"]
            uploaded[rel] = url
            print(f"  올림: {rel}")
            return url

        body, thumb = to_html(md, upload)

        payload = {
            "slug": meta.get("site_slug") or slug_dir.name,
            "title": title,
            "summary": meta.get("summary") or _summary_of(md),
            "description": body,
            "client_name": meta.get("org") or None,
            "conducted_at": meta.get("date") or None,
            "thumbnail_url": thumb,
            "status": "published" if live else "draft",
        }
        r = req.post(CASES_API, data=payload)
        if r.status == 401:
            raise SystemExit("로그인이 만료됐습니다. `uv run prpub site-login` 을 다시 실행하세요.")
        if r.status == 409:
            raise SystemExit(f"같은 slug 의 글이 이미 있습니다: {payload['slug']}")
        if not r.ok:
            raise SystemExit(f"발행 실패 ({r.status}): {r.text()[:300]}")

        ctx.close()

    state = "공개" if live else "임시저장(draft)"
    print(f"사이트에 올렸습니다 — {state}")
    print(f"  제목: {title}")
    print(f"  확인: {ADMIN_URL}")
    if not live:
        print("  공개하려면 어드민에서 상태를 바꾸거나 --live 로 다시 실행하세요.")
