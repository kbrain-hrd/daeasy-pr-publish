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
from datetime import date
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
# `::맺음 문장::` — 글 끝의 DAEASY 공식 마무리 멘트. 본문과 구분되게 인용구 박스로,
# 위 여백을 더 주고(mt-10) 글씨를 키워(text-lg) 렌더한다. sanitize 가 class 는 허용하고
# mt-10·text-lg 는 사이트 번들에 이미 있는 클래스라 프론트 변경 없이 먹는다.
_CLOSING = re.compile(r"^::맺음\s*(.+?)\s*::$")
_IMG = re.compile(r"^!\[(.*?)\]\((.+?)\)$")
_URL = re.compile(r"^https?://\S+$")
_RULE = re.compile(r"^[─—\-_]{3,}$")
# `→ [결과물 보기](URL)` 산출물 링크 줄. 바로 위 산출물 설명 문단에 붙어야 한다.
_OUTPUT_LINK = re.compile(r"^→\s*\[[^\]]+\]\(https?://\S+\)\s*$")
# `::산출물 제목 | 설명 | 썸네일파일 | URL::` 산출물 카드. 썸네일 이미지를 올려 카드로 렌더한다.
_OUTPUT = re.compile(r"^::산출물\s*(.+?)\s*::$")


def _link(url: str) -> str:
    u = html.escape(url)
    return f'<a href="{u}" target="_blank" rel="noopener">{u}</a>'


def _inline(s: str) -> str:
    """`[텍스트](URL)` 링크와 `**굵게**` 를 처리한다. 나머지는 이스케이프한다.

    산출물 자료 등을 본문에서 눌러 볼 수 있게 마크다운 링크를 <a> 로 바꾼다.
    html.escape 는 []() 를 건드리지 않으므로 escape 뒤에 치환해도 안전하다.
    """
    out = html.escape(s)
    out = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        out,
    )
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)


def to_html(md: str, upload) -> tuple[str, str | None]:
    """post.md 를 사이트용 HTML 로 옮긴다. (본문, 대표이미지 URL)

    `upload(경로) -> URL` 을 받아 이미지를 올린다. 본문 첫 이미지가 대표 사진이 된다 —
    사이트가 대표 사진을 상단에 따로 보여주므로 그 이미지는 본문에서 뺀다 (중복 노출 방지).
    """
    body: list[str] = []
    thumb: str | None = None
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)

    # 마커 줄(::인용·::수치·소제목·이미지)이 앞 문장에 빈 줄 없이 붙어 있으면,
    # \n\n 분리에서 한 덩어리로 묶여 변환 규칙(^::인용…::$ 등)에 안 걸려 글자로 샌다.
    # 분리 전에 마커 줄 앞뒤로 빈 줄을 보장한다 (writer 가 빈 줄을 빠뜨려도 안전).
    _norm: list[str] = []
    for ln in md.split("\n"):
        st = ln.strip()
        if st.startswith("::") or st.startswith("![") or st.startswith("## "):
            if _norm and _norm[-1].strip():
                _norm.append("")
            _norm.append(ln)
            _norm.append("")
        else:
            # 산출물 링크 줄은 바로 위 설명 문단에 붙인다 — 사이 빈 줄을 지워 한 <p> 안에
            # <br> 로 묶는다. 그러면 설명 바로 아래 링크(좁은 간격)·그룹 사이 <p> 여백(넓은
            # 간격)으로 갈려, 이전 산출물이 다음 과제에 붙어 보이던 문제가 사라진다.
            if _OUTPUT_LINK.match(st) and len(_norm) >= 2 \
                    and _norm[-1].strip() == "" and _norm[-2].strip():
                _norm.pop()
            _norm.append(ln)
    md = "\n".join(_norm)

    for block in md.split("\n\n"):
        s = block.strip()
        if not s or s.startswith("# "):
            continue

        if s.startswith("## "):
            body.append(f"<h2>{_inline(s[3:].strip())}</h2>")
            continue

        m = _IMG.match(s)
        if m:
            # 원고 캡션에 HTML 엔티티(&#39; 등)가 섞여 있으면 아래 escape와 겹쳐 깨진다 — 먼저 푼다
            cap, path = html.unescape(m.group(1)), m.group(2)
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

        m = _CLOSING.match(s)
        if m:
            # 맺음(공식 마무리 멘트) — 인용구 박스로, 위 여백 더(mt-10)·글씨 키워(text-lg).
            body.append(
                f'<blockquote class="mt-10"><p class="text-lg">{_inline(m.group(1))}</p></blockquote>'
            )
            continue

        m = _QUOTE.match(s)
        if m:
            parts = [x.strip() for x in m.group(1).split("|")]
            # 사이트 prose 가 blockquote 의 첫/마지막 '문단(p)' 에 여는/닫는 따옴표를 붙인다.
            # 출처(누가)를 <p> 로 두면 닫는 따옴표가 출처까지 감싼다("…했습니다. 수강생").
            # 출처는 <p> 가 아닌 <div> 로 둬서, 닫는 따옴표는 인용문 p 에서 끝나고
            # 출처는 인용 블록 안에 같은 형식(기울임)으로 따옴표 밖에 남는다.
            out = f"<blockquote><p>{_inline(parts[0])}</p>"
            if len(parts) > 1 and parts[1]:
                out += f"<div><em>{_inline(parts[1])}</em></div>"
            body.append(out + "</blockquote>")
            continue

        m = _STATS.match(s)
        if m:
            items = "".join(
                f"<li>{_inline(x.strip())}</li>" for x in m.group(1).split("|") if x.strip()
            )
            body.append(f"<ul>{items}</ul>")
            continue

        m = _OUTPUT.match(s)
        if m:
            # 산출물 = 산출물명(소제목) → 소개글(본문) → 카드(썸네일+결과물 보기). 순서가 핵심:
            # 설명은 카드 밖 본문 문단으로 두고, 카드는 썸네일 이미지와 '결과물 보기' 링크만
            # 담는다. 제목 | 설명 | 썸네일파일 | URL. sanitize-html 이 style·div 를 지우므로
            # 허용 태그(h3/p/figure/a/img/figcaption)와 class 로만 짠다.
            parts = [x.strip() for x in m.group(1).split("|")]
            title = parts[0] if len(parts) > 0 else ""
            desc = parts[1] if len(parts) > 1 else ""
            thumb_src = parts[2] if len(parts) > 2 else ""
            url = parts[3] if len(parts) > 3 else ""
            img_url = upload(thumb_src) if thumb_src else None
            out = f'<h3 class="output-subject">{_inline(title)}</h3>' if title else ""
            if desc:
                out += f"<p>{_inline(desc)}</p>"
            card = '<figure class="output-card">'
            if img_url:
                img = f'<img src="{html.escape(img_url)}" alt="{html.escape(title)}">'
                card += (f'<a class="output-card-media" href="{html.escape(url)}" target="_blank" '
                         f'rel="noopener">{img}</a>') if url else img
            if url:
                card += (f'<figcaption class="output-card-cta"><a href="{html.escape(url)}" '
                         f'target="_blank" rel="noopener">결과물 보기 →</a></figcaption>')
            body.append(out + card + "</figure>")
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


def _edu_info_block(meta: dict) -> str:
    """본문 맨 앞에 고정으로 넣는 교육 개요 블록 — 제목·대표사진 바로 아래 규격.

    값은 meta.json(양식 파싱 결과)에서 오므로 글마다 형식이 흔들리지 않는다.
    sanitize-html 허용 태그(ul/li/strong)만 쓴다 — style 은 어차피 지워진다.
    """
    rows = [
        ("교육명", meta.get("course_name", "")),
        ("교육기관", meta.get("org", "")),
        ("교육 일자", meta.get("dates", "")),
        ("교육 대상·인원", meta.get("participants", "")),
    ]
    items = "".join(
        f"<li><strong>{html.escape(label)}</strong> {html.escape(' '.join(value.split()))}</li>"
        for label, value in rows
        if value.strip()
    )
    if not items:
        return ""
    return f'<ul class="edu-info">{items}</ul><hr>'


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


def _case_id_for_slug(ctx, slug: str) -> str | None:
    """어드민 목록 페이지에서 slug 에 해당하는 case id 를 찾는다(갱신용).

    사이트에는 slug→id HTTP 조회 API 가 없다(어드민 목록은 서버에서 Supabase 직접 조회).
    그래서 로그인 세션으로 /admin/cases 를 열어, 행의 slug 텍스트와 편집 링크
    (/admin/cases/<id>/edit)를 짝지어 id 를 꺼낸다."""
    page = ctx.new_page()
    try:
        page.goto(f"{ADMIN_URL}?status=all", wait_until="networkidle")
        return page.evaluate(
            """(slug) => {
                for (const tr of document.querySelectorAll('tr')) {
                    const s = tr.querySelector('.font-mono');
                    if (s && s.textContent.trim() === slug) {
                        const a = tr.querySelector('a[href*="/admin/cases/"][href*="/edit"]');
                        const m = a && a.getAttribute('href').match(/\\/admin\\/cases\\/([^/]+)\\/edit/);
                        return m ? m[1] : null;
                    }
                }
                return null;
            }""",
            slug,
        )
    finally:
        page.close()


def publish(slug_dir: Path, live: bool = False) -> None:
    """out/<slug>/post.md 를 사이트 교육후기로 만든다.

    기본은 status=draft — 어드민에서 눈으로 확인한 뒤 공개한다.
    `live=True` 면 곧바로 published 로 넣는다.
    같은 slug 의 글이 이미 있으면 새로 만드는 대신 그 글을 갱신(덮어쓰기)한다 —
    같은 접수 건을 다시 발행할 때 어드민에서 지우지 않아도 되게 한다."""
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
        body = _edu_info_block(meta) + body  # 제목·대표사진 아래 고정 규격 (교육명·기관·일자·대상)

        payload = {
            "slug": meta.get("site_slug") or slug_dir.name,
            "title": title,
            "summary": meta.get("summary") or _summary_of(md),
            "description": body,
            "client_name": meta.get("org") or None,
            # 카드·목록 날짜는 교육일이 아니라 게시일 — 교육 일자는 본문에 적혀 있다
            "conducted_at": date.today().isoformat(),
            "thumbnail_url": thumb,
            "status": "published" if live else "draft",
        }
        r = req.post(CASES_API, data=payload)
        if r.status == 401:
            raise SystemExit("로그인이 만료됐습니다. `uv run prpub site-login` 을 다시 실행하세요.")
        if r.status == 409:
            # 같은 slug 글이 이미 있으면 삭제 없이 그 글을 갱신한다.
            cid = _case_id_for_slug(ctx, payload["slug"])
            if not cid:
                raise SystemExit(
                    f"같은 slug 글({payload['slug']})이 있으나 id 를 찾지 못해 갱신하지 못했습니다. "
                    f"어드민에서 확인하세요.")
            ru = req.fetch(f"{CASES_API}/{cid}", method="PATCH", data=payload)
            if ru.status == 401:
                raise SystemExit("로그인이 만료됐습니다. `uv run prpub site-login` 을 다시 실행하세요.")
            if not ru.ok:
                raise SystemExit(f"갱신 실패 ({ru.status}): {ru.text()[:300]}")
            updated = True
        elif not r.ok:
            raise SystemExit(f"발행 실패 ({r.status}): {r.text()[:300]}")
        else:
            updated = False

        ctx.close()

    state = ("공개" if live else "임시저장(draft)") + (" · 기존 글 갱신" if updated else " · 신규")
    print(f"사이트에 올렸습니다 — {state}")
    print(f"  제목: {title}")
    print(f"  확인: {ADMIN_URL}")
    if not live:
        print("  공개하려면 어드민에서 상태를 바꾸거나 --live 로 다시 실행하세요.")
