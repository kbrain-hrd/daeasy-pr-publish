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
# `::표 머리1|머리2;;행1-1|행1-2;;행2-1|행2-2::` — 표. 행 구분 `;;`, 열 구분 `|`, 첫 행이 머리.
# sanitize 가 table/thead/tbody/tr/th/td 를 허용하고 prose 가 표를 꾸며 프론트 변경 없이 먹는다.
_TABLE = re.compile(r"^::표\s*(.+?)\s*::$")
# `::카드 제목1|설명1;;제목2|설명2::` — 카드 그리드(2열, 홀수면 마지막 카드 전체폭 → 대칭).
# `::카드B …::` 는 B 시안(흰 카드+상단 액센트). globals.css 의 .edu-cards / .edu-cards-b 로 꾸민다.
_CARDS = re.compile(r"^::카드(B)?\s*(.+?)\s*::$")
# `::단계 제목1|설명1;;제목2|설명2::` — 단계 플로우(번호 배지+제목+설명 카드를 화살표로 연결).
# globals.css 의 .edu-flow 로 꾸민다. 과정 흐름·프로세스 표현용.
# `::단계B …::` 는 B 시안(번호 점을 선으로 잇는 가로 진행 바, 모바일 세로). 제목의 `앞말 · 뒷말` 은
# 앞말을 작은 라벨(예: 1일차)로, 뒷말을 제목으로 나눈다. globals.css 의 .edu-steps 로 꾸민다.
_FLOW = re.compile(r"^::단계(B)?\s*(.+?)\s*::$")
# `::단계C 라벨 · 제목|항목1, 항목2;;…::` — 단계 목록(줄마다 큰 번호 | 라벨·제목 | 항목 태그).
# globals.css 의 .edu-rows 로 꾸민다. 항목은 `, ` 로 나눠 태그(span)로 낸다.
_ROWS = re.compile(r"^::단계C\s*(.+?)\s*::$")
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
            # 맺음(공식 마무리 멘트) — 박스/인용구 없이, 가운데 정렬 큰 굵은 글씨로 강조한다.
            # 상단에 액센트 라벨(kicker)을 얹어 눈에 띄게. 본문에 ` // ` 를 넣은 자리에서 줄바꿈(<br>).
            # blockquote 는 prose 가 italic·따옴표를 강제하므로 안 쓰고, 이미 빌드된 유틸 클래스만
            # 쓴다 (sanitize 가 class·<br> 는 보존).
            inner = "<br>".join(_inline(p.strip()) for p in m.group(1).split("//"))
            body.append(
                f'<div class="closing-note mt-10 text-center max-w-2xl mx-auto">'
                f'<div class="text-accent text-sm font-semibold uppercase tracking-wide">— DAEASY 제안 —</div>'
                f'<p class="mt-3 text-lg font-bold leading-snug">{inner}</p>'
                f'</div>'
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

        m = _TABLE.match(s)
        if m:
            rows = [r for r in (r.strip() for r in m.group(1).split(";;")) if r]
            cells = [[c.strip() for c in r.split("|")] for r in rows]
            if cells:
                head, rest = cells[0], cells[1:]
                out = "<table><thead><tr>" + "".join(
                    f"<th>{_inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
                for r in rest:
                    out += "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>"
                body.append(out + "</tbody></table>")
            continue

        m = _CARDS.match(s)
        if m:
            cls = "edu-cards-b" if m.group(1) else "edu-cards"
            lis = ""
            for it in (x.strip() for x in m.group(2).split(";;")):
                if not it:
                    continue
                parts = [p.strip() for p in it.split("|")]
                title = parts[0] if parts else ""
                desc = parts[1] if len(parts) > 1 else ""
                lis += (f"<li><h3>{_inline(title)}</h3>"
                        + (f"<p>{_inline(desc)}</p>" if desc else "")
                        + "</li>")
            body.append(f'<ol class="{cls}">{lis}</ol>')
            continue

        m = _ROWS.match(s)
        if m:
            lis = ""
            for it in (x.strip() for x in m.group(1).split(";;")):
                if not it:
                    continue
                parts = [p.strip() for p in it.split("|")]
                label, _, title = parts[0].rpartition(" · ")
                tags = [t.strip() for t in (parts[1] if len(parts) > 1 else "").split(", ") if t.strip()]
                lis += ("<li><h3>" + (f'<span class="st-label">{_inline(label)}</span>' if label else "")
                        + f"{_inline(title)}</h3>"
                        + ("<p>" + "".join(f"<span>{_inline(t)}</span>" for t in tags) + "</p>" if tags else "")
                        + "</li>")
            body.append(f'<ol class="edu-rows">{lis}</ol>')
            continue

        m = _FLOW.match(s)
        if m:
            lis = ""
            for it in (x.strip() for x in m.group(2).split(";;")):
                if not it:
                    continue
                parts = [p.strip() for p in it.split("|")]
                title = parts[0] if parts else ""
                desc = parts[1] if len(parts) > 1 else ""
                label = ""
                if m.group(1) and " · " in title:
                    label, title = (x.strip() for x in title.split(" · ", 1))
                lis += ("<li>" + (f'<span class="st-label">{_inline(label)}</span>' if label else "")
                        + f"<h3>{_inline(title)}</h3>"
                        + (f"<p>{_inline(desc)}</p>" if desc else "")
                        + "</li>")
            cls = "edu-steps" if m.group(1) else "edu-flow"
            body.append(f'<ol class="{cls}">{lis}</ol>')
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


def _case_for_slug(ctx, slug: str) -> dict | None:
    """어드민 목록 페이지에서 slug 에 해당하는 case 의 id 와 상태 배지 글자를 찾는다(갱신용).

    사이트에는 slug→id HTTP 조회 API 가 없다(어드민 목록은 서버에서 Supabase 직접 조회).
    그래서 로그인 세션으로 /admin/cases 를 열어, 행의 slug 텍스트와 편집 링크
    (/admin/cases/<id>/edit)를 짝지어 id 를 꺼낸다. 상태는 같은 행의 배지('공개'/'임시저장')."""
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
                        const b = tr.querySelector('span.rounded-full');
                        return {id: m ? m[1] : null, status: b ? b.textContent.trim() : null};
                    }
                }
                return null;
            }""",
            slug,
        )
    finally:
        page.close()


def _case_id_for_slug(ctx, slug: str) -> str | None:
    return (_case_for_slug(ctx, slug) or {}).get("id")


# 어드민 목록의 상태 배지 글자 (사이트 frontend/src/lib/admin-content.ts CONTENT_STATUS_LABEL)
STATUS_LABEL = {"임시저장": "draft", "공개": "published"}


def _update_refusal(status: str | None, live: bool, update: bool) -> str | None:
    """기존 글을 덮어쓰면 안 되는 사유. 없으면 None.

    임시저장 글 갱신(draft→live 공개 포함)은 그대로 둔다. 공개 글은 `--live --update` 로만 갱신한다 —
    사이트 수정 API 가 보낸 값으로 통째로 바꿔서, --live 가 없으면 임시저장으로 내려가고
    있어도 게시일이 오늘로·교육과정 연결이 비워진다. 상태를 모르면 덮어쓰지 않는다."""
    if status == "draft":
        return None
    if status == "published":
        if not live:
            return "공개 중인 글입니다 — --live 없이 덮어쓰면 임시저장으로 내려갑니다."
        if not update:
            return ("공개 중인 글입니다 — 공개 글 갱신은 --update 를 함께 붙여야 합니다 "
                    "(게시일이 오늘로 바뀌고 교육과정 연결이 비워집니다).")
        return None
    return f"기존 글의 공개 상태를 확인하지 못했습니다(상태: {status or '읽지 못함'}) — 덮어쓰지 않습니다."


def publish(slug_dir: Path, live: bool = False, update: bool = False) -> None:
    """out/<slug>/post.md 를 사이트 교육후기로 만든다.

    기본은 status=draft — 어드민에서 눈으로 확인한 뒤 공개한다.
    `live=True` 면 곧바로 published 로 넣는다.
    같은 slug 의 글이 이미 있으면 새로 만드는 대신 그 글을 갱신(덮어쓰기)한다 —
    같은 접수 건을 다시 발행할 때 어드민에서 지우지 않아도 되게 한다.
    단 공개 중인 글은 `live=True, update=True` 일 때만 갱신한다 (_update_refusal)."""
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
            row = _case_for_slug(ctx, payload["slug"]) or {}
            cid = row.get("id")
            if not cid:
                raise SystemExit(
                    f"같은 slug 글({payload['slug']})이 있으나 id 를 찾지 못해 갱신하지 못했습니다. "
                    f"어드민에서 확인하세요.")
            refusal = _update_refusal(STATUS_LABEL.get(row.get("status") or ""), live, update)
            if refusal:
                raise SystemExit(f"기존 글({payload['slug']})을 갱신하지 않았습니다: {refusal} 어드민에서 확인하세요.")
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
            try:
                body_json = r.json()
                cid = body_json.get("id") or (body_json.get("data") or {}).get("id")
            except Exception:
                cid = None
            if not cid:
                cid = _case_id_for_slug(ctx, payload["slug"])

        ctx.close()

    state = ("공개" if live else "임시저장(draft)") + (" · 기존 글 갱신" if updated else " · 신규")
    print(f"사이트에 올렸습니다 — {state}")
    print(f"  제목: {title}")
    print(f"  확인: {ADMIN_URL}")
    if cid:
        # draft 도 볼 수 있는 사이트 미리보기 주소 — 팀 공유용
        print(f"  미리보기: {SITE}/cases/preview/{cid}")
    if not live:
        print("  공개하려면 어드민에서 상태를 바꾸거나 --live 로 다시 실행하세요.")
