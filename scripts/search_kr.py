"""한국 웹 검색.

기본 웹 검색 도구는 해외 색인이라 네이버·정부 보도자료가 거의 잡히지 않는다.
그래서 한국 쪽 경로를 따로 둔다. 세 갈래다.

  korea  정책브리핑 korea.kr    키 불필요   정부·기관 보도자료 통합 검색
  naver  네이버 검색 API        키 필요     뉴스·블로그·카페·웹문서 전체
  kakao  카카오(다음) 검색 API  키 필요     다음 웹·블로그

# 네이버는 키 없이 긁을 수 없다 — 확인한 사실 (2026-09-03)
#
# search.naver.com/robots.txt, blog.naver.com/robots.txt, rss.blog.naver.com/robots.txt
# 셋 다 `User-agent: * / Disallow: /` 전면 차단이고, 아래 문구가 붙어 있다.
#
#   BOT ACCESS FOR THE PURPOSES OF AI TRAINING AND
#   RETRIEVAL-AUGMENTED GENERATION (RAG) IS STRICTLY PROHIBITED.
#   User-agent: ClaudeBot / Claude-SearchBot → Disallow: /
#
# 우리 용도가 정확히 그 RAG 이고 우리 도구가 이름으로 지목돼 있다.
# 검색화면 스크래핑도, 블로그 RSS 도 하지 않는다. 네이버는 API 가 유일한 문이다.
# (전에 RSS 갈래가 있었으나 rss.blog.naver.com 도 전면 차단인 것을 확인하고 걷어냈다.)
#
# 반면 korea.kr 과 mois.go.kr 은 `User-agent: * / Allow: /` 라 문제없다.

키 넣는 법 — 환경변수 또는 프로젝트 루트 .secrets.toml (저장소에 올라가지 않는다)

    naver_client_id = "..."
    naver_client_secret = "..."
    kakao_rest_key = "..."

  카카오 키: developers.kakao.com → 앱 → REST API 키 (무료, 카드 불필요)
  네이버 키: NAVER API HUB (네이버 클라우드 플랫폼). 개발자센터는 2026-07-31 부터
            신규 신청이 막혔다. HUB 로 옮기면 요청 주소와 헤더 이름이 바뀌는데,
            코드를 고칠 필요 없이 .secrets.toml 에 아래를 더 적으면 된다.

    naver_api_base      = "https://..."          # 기본값은 옛 openapi.naver.com
    naver_id_header     = "X-Naver-Client-Id"
    naver_secret_header = "X-Naver-Client-Secret"

사용:
  uv run python scripts/search_kr.py "화성시 AI 챔피언"
  uv run python scripts/search_kr.py "화성시 AI 교육" --only korea
  uv run python scripts/search_kr.py "..." --since 2026-01-01 --json
"""
import argparse
import html
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / ".secrets.toml"

NAVER_WHERE = {"news": "뉴스", "blog": "블로그", "cafearticle": "카페", "webkr": "웹문서"}
DEFAULT_WHERE = "news,blog,cafearticle,webkr"
SOURCES = ("korea", "naver", "kakao")

# HTTP 헤더는 latin-1 만 담을 수 있다. 한글을 넣으면 요청 자체가 터진다.
UA = "daeasy-pr-publish/1.0 (+https://daeasy.vercel.app; data-edu@kbrainc.com)"
_TAG = re.compile(r"<[^>]+>")

KOREA_URL = "https://www.korea.kr/briefing/pressReleaseList.do"
_KOREA_ITEM = re.compile(
    r'<a href="(/briefing/pressReleaseView\.do\?[^"]+)"[^>]*>\s*'
    r'<span class="text">\s*'
    r"<strong>(.*?)</strong>\s*"
    r'<span class="lead">(.*?)</span>\s*'
    r'<span class="source">\s*<span>(.*?)</span>\s*<span>(.*?)</span>',
    re.S,
)


def _toml(p: Path) -> dict:
    return tomllib.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _key(env: str, name: str, default=None):
    return os.environ.get(env) or _toml(SECRETS).get(name, default)


def _clean(s: str) -> str:
    """검색어를 <b>/<span> 으로 감싸 돌려주는 곳이 많다. 태그와 엔티티를 푼다."""
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub("", s or ""))).strip()


def _fetch(url: str, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()


def _row(src, title, lead, url, when="", media=""):
    return {"출처": src, "제목": title, "요약": lead, "주소": url, "날짜": when, "매체": media}


# ── 2. 정책브리핑 korea.kr — 키 불필요 ──────────────────────────────────


def korea(query: str, n: int, since: str) -> list[dict]:
    qs = urllib.parse.urlencode(
        {
            "srchWord": query,
            "startDate": since,
            "endDate": date.today().isoformat(),
            "pageIndex": 1,
        }
    )
    try:
        page = _fetch(f"{KOREA_URL}?{qs}").decode("utf-8", "replace")
    except urllib.error.URLError as e:
        return [{"_error": f"정책브리핑 — {e}"}]

    out = []
    for href, title, lead, when, org in _KOREA_ITEM.findall(page)[:n]:
        out.append(
            _row(
                "정책브리핑",
                _clean(title),
                _clean(lead),
                "https://www.korea.kr" + html.unescape(href).split("&pageIndex")[0],
                _clean(when),
                _clean(org),
            )
        )
    if not out and 'class="list_type"' not in page:
        return [{"_error": "정책브리핑 — 화면 구조가 바뀐 듯. _KOREA_ITEM 확인 필요"}]
    return out


# ── 3. 네이버 검색 API — 키 필요 ────────────────────────────────────────


def naver(query: str, where: str, n: int) -> list[dict]:
    cid = _key("NAVER_CLIENT_ID", "naver_client_id")
    csec = _key("NAVER_CLIENT_SECRET", "naver_client_secret")
    if not (cid and csec):
        return [{"_error": "네이버 API 키 없음 — 이 갈래는 못 돌림 (NAVER API HUB 에서 발급)"}]

    base = _key("NAVER_API_BASE", "naver_api_base", "https://openapi.naver.com/v1/search")
    h_id = _key("NAVER_ID_HEADER", "naver_id_header", "X-Naver-Client-Id")
    h_sec = _key("NAVER_SECRET_HEADER", "naver_secret_header", "X-Naver-Client-Secret")

    qs = urllib.parse.urlencode({"query": query, "display": min(n, 100), "sort": "sim"})
    try:
        raw = _fetch(f"{base.rstrip('/')}/{where}?{qs}", {h_id: cid, h_sec: csec})
        data = json.loads(raw)
    except urllib.error.HTTPError as e:
        return [{"_error": f"네이버 {where} {e.code} — {e.read().decode('utf-8', 'ignore')[:140]}"}]
    except urllib.error.URLError as e:
        return [{"_error": f"네이버 {where} — {e}"}]

    return [
        _row(
            f"네이버 {NAVER_WHERE.get(where, where)}",
            _clean(it.get("title")),
            _clean(it.get("description")),
            it.get("originallink") or it.get("link"),
            it.get("pubDate") or it.get("postdate") or "",
            _clean(it.get("bloggername") or it.get("cafename") or ""),
        )
        for it in data.get("items", [])
    ]


# ── 4. 카카오(다음) 검색 API — 키 필요 ──────────────────────────────────


def kakao(query: str, n: int) -> list[dict]:
    key = _key("KAKAO_REST_KEY", "kakao_rest_key")
    if not key:
        return [{"_error": "카카오 API 키 없음 — 이 갈래는 못 돌림 (developers.kakao.com, 무료)"}]

    out = []
    for kind, label in (("web", "다음 웹"), ("blog", "다음 블로그")):
        qs = urllib.parse.urlencode({"query": query, "size": min(n, 50)})
        try:
            raw = _fetch(
                f"https://dapi.kakao.com/v2/search/{kind}?{qs}",
                {"Authorization": f"KakaoAK {key}"},
            )
            data = json.loads(raw)
        except urllib.error.HTTPError as e:
            out.append({"_error": f"카카오 {kind} {e.code}"})
            continue
        out += [
            _row(
                label,
                _clean(it.get("title")),
                _clean(it.get("contents")),
                it.get("url"),
                it.get("datetime", "")[:10],
                _clean(it.get("blogname") or ""),
            )
            for it in data.get("documents", [])
        ]
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--only", default=",".join(SOURCES), help=f"쉼표로. {','.join(SOURCES)}")
    ap.add_argument("--where", default=DEFAULT_WHERE, help=f"네이버 API 코퍼스. {DEFAULT_WHERE}")
    ap.add_argument("--n", type=int, default=10, help="갈래별 개수")
    ap.add_argument(
        "--since",
        default=(date.today() - timedelta(days=730)).isoformat(),
        help="정책브리핑 검색 시작일 (기본 2년 전)",
    )
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    want = [s.strip() for s in a.only.split(",") if s.strip()]
    rows, errors, ran = [], [], []

    def take(results):
        for r in results:
            (errors if "_error" in r else rows).append(r.get("_error", r))

    if "korea" in want:
        ran.append("정책브리핑")
        take(korea(a.query, a.n, a.since))
    if "naver" in want:
        ran.append("네이버 API")
        for w in [x.strip() for x in a.where.split(",") if x.strip()]:
            if w not in NAVER_WHERE:
                errors.append(f"모르는 코퍼스: {w}")
            else:
                take(naver(a.query, w, a.n))
    if "kakao" in want:
        ran.append("카카오")
        take(kakao(a.query, a.n))

    if a.json:
        print(
            json.dumps(
                {"검색어": a.query, "돌린갈래": ran, "결과": rows, "오류": errors},
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    print(f"검색어: {a.query}")
    print(f"돌린 갈래: {' · '.join(ran)}   결과 {len(rows)}건")
    for e in errors:
        print(f"  ! {e}")
    for i, r in enumerate(rows, 1):
        media = f" · {r['매체']}" if r["매체"] else ""
        print(f"\n{i:2d}. [{r['출처']}{media}] {r['제목']}")
        if r["날짜"]:
            print(f"    {r['날짜']}")
        print(f"    {r['주소']}")
        if r["요약"]:
            print(f"    {r['요약'][:150]}")


if __name__ == "__main__":
    main()
