# -*- coding: utf-8 -*-
"""네이버 모바일 검색 저장본 파서 — 사람이 Chrome 에서 저장한 HTML → 정규화 JSON.

네이버에 자동 요청을 보내지 않는다. robots(전 경로 차단 + AI/RAG 봇 금지 명문,
2026-09-29 실측)와 2026-09-07 개정 약관 때문에 자동 수집은 금지이고, 이 스크립트는
**사람이 브라우저로 열어 Ctrl+S 로 저장한 파일**만 입력으로 받는 로컬 파서다.
그래서 이 파일에는 네트워크 모듈(urllib 등)이 없다 — 추가하지 말 것.

입력 규약: 접수 건 폴더의 `자료/네이버검색/*.html`
  (통합검색 저장본은 웹문서형, 뉴스 탭 저장본은 뉴스형으로 자동 판별)

selector 는 2026-09-29 실측 DOM 기준 (docs/최종테스트… 조사 기록 참고):
  통합(웹문서)  아이템 div.fds-web-doc-root · 출처 span.…text-type-body2(첫 링크)
               · 제목 = 원문 href a(내부 text-type 스팬 없음) · 요약 span.…text-type-body1
               · 날짜 없음(실측) — 빈 값 유지, 저장일로 대체하지 않는다
  뉴스         리스트 div.fds-news-item-list-tab 직계 아이템(난독 클래스에 의존 안 함)
               · 제목 span.…text-type-headline1 · 링크 n.news.naver.com(그대로 보존)
               · 날짜 span.…profile-info-subtext(상대시각 그대로) · 요약 body1
               · 언론사 span.…profile-info-title-text

검색어는 저장본 <title> ("<검색어> : 네이버 통합검색/뉴스검색")에서 뽑는다 —
파일명 추론보다 명시적이다. 못 뽑으면 빈 값.

사용:
  uv run python scripts/search_naver_mobile.py <파일|폴더> [...]   # JSON 출력
"""
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path


# ── 순서 보존 DOM 트리 ───────────────────────────────────────────────────
# 텍스트와 자식 요소의 원래 순서를 보존한다. 순서를 잃으면 <mark> 강조가 섞인
# 제목의 어순이 깨진다 ("AI 챔피언 인증교육" → "챔피언 인증교육AI", 실측 사례).


class Node:
    __slots__ = ("tag", "attrs", "cls", "parent", "content")

    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = dict(attrs)
        self.cls = self.attrs.get("class", "")
        self.parent = parent
        self.content = []  # str(텍스트) 또는 Node — DOM 순서 그대로

    def children(self):
        return [c for c in self.content if isinstance(c, Node)]

    def walk(self):
        yield self
        for c in self.children():
            yield from c.walk()

    def text(self):
        out = []
        for c in self.content:
            out.append(c if isinstance(c, str) else c.text())
        return "".join(out)


class TreeBuilder(HTMLParser):
    VOID = {"br", "img", "meta", "link", "input", "hr", "source", "area",
            "base", "col", "embed", "track", "wbr"}

    def __init__(self):
        super().__init__()
        self.root = Node("root", [], None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.cur)
        self.cur.content.append(n)
        if tag not in self.VOID:
            self.cur = n

    def handle_endtag(self, tag):
        c = self.cur
        while c is not self.root and c.tag != tag:
            c = c.parent
        if c is not self.root:
            self.cur = c.parent

    def handle_data(self, data):
        self.cur.content.append(data)


def parse_tree(path: Path) -> Node:
    tb = TreeBuilder()
    tb.feed(path.read_text(encoding="utf-8", errors="replace"))
    return tb.root


# ── 추출 ────────────────────────────────────────────────────────────────

NOISE = ("Keep에", "자세히 보기", "관련문서 더보기")
DATE_RE = re.compile(r"^(\d+\s*(분|시간|일|주)\s*전|어제|\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.?)$")
TITLE_TAG_RE = re.compile(r"^\s*(.+?)\s*:\s*네이버\s*\S*검색\s*$")


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def span_types(a: Node) -> set:
    return {m.group(1) for c in a.walk() if c.tag == "span"
            for m in [re.search(r"text-type-(\w+)", c.cls)] if m}


def search_query(root: Node) -> str:
    for n in root.walk():
        if n.tag == "title":
            m = TITLE_TAG_RE.match(clean(n.text()))
            if m:
                return m.group(1)
            break
    return ""


def http_links(item: Node):
    for a in item.walk():
        if a.tag == "a" and a.attrs.get("href", "").startswith("http"):
            t = clean(a.text())
            if t and not any(x in t for x in NOISE):
                yield a, t


def parse_news(root: Node, query: str) -> list[dict]:
    rows = []
    lists = [n for n in root.walk() if "fds-news-item-list-tab" in n.cls]
    if not lists:
        return rows
    for item in lists[0].children():
        title = url = summary = date = publisher = ""
        for a, t in http_links(item):
            types = span_types(a)
            if "headline1" in types and not title:
                title, url = t, a.attrs["href"]
            elif "body1" in types and not summary:
                summary = t
        for n in item.walk():
            if n.tag != "span":
                continue
            txt = clean(n.text())
            if "profile-info-subtext" in n.cls and DATE_RE.match(txt):
                date = txt
            elif "profile-info-title-text" in n.cls and not publisher:
                publisher = txt
        if title and url:
            rows.append({"source": "naver_mobile", "type": "news",
                         "search_query": query, "title": title, "url": url,
                         "date": date, "summary": summary, "publisher": publisher})
    return rows


def parse_web(root: Node, query: str) -> list[dict]:
    rows = []
    for item in (n for n in root.walk() if "fds-web-doc-root" in n.cls):
        title = url = summary = publisher = ""
        for a, t in http_links(item):
            if "naver.com" in a.attrs["href"]:
                continue  # 도움말·더보기 등 네이버 내부 링크
            types = span_types(a)
            if "body2" in types and not publisher:
                publisher = t
            elif "body1" in types and not summary:
                summary = t
            elif not types and not title:
                title, url = t, a.attrs["href"]
        if title and url:
            rows.append({"source": "naver_mobile", "type": "web",
                         "search_query": query, "title": title, "url": url,
                         "date": "", "summary": summary, "publisher": publisher})
    return rows


def parse_file(path: Path) -> list[dict]:
    root = parse_tree(path)
    q = search_query(root)
    rows = parse_news(root, q) + parse_web(root, q)
    for r in rows:
        r["file"] = path.name
    return rows


def dedupe(rows: list[dict]) -> list[dict]:
    """source+url 기준 병합 — 검색어가 다르면 버리지 않고 합친다."""
    seen: dict = {}
    for r in rows:
        key = (r["source"], r["url"])
        if key in seen:
            prev = seen[key]
            if r["search_query"] and r["search_query"] not in prev["search_query"]:
                prev["search_query"] = "; ".join(
                    x for x in (prev["search_query"], r["search_query"]) if x)
        else:
            seen[key] = r
    return list(seen.values())


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:]
    if not args:
        raise SystemExit("사용: search_naver_mobile.py <저장 HTML 파일 또는 폴더> [...]")

    paths: list[Path] = []
    for a in args:
        p = Path(a)
        if p.is_dir():
            paths += sorted(p.glob("*.html")) + sorted(p.glob("*.htm"))
        elif p.is_file():
            paths.append(p)
        else:
            print(f"! 없음: {a}", file=sys.stderr)

    rows: list[dict] = []
    errors: list[str] = []
    for p in paths:
        try:
            rows += parse_file(p)
        except Exception as ex:  # 파일 하나의 실패가 전체를 죽이지 않는다
            errors.append(f"{p.name}: {ex}")

    print(json.dumps({"결과": dedupe(rows), "파일": [p.name for p in paths],
                      "오류": errors}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
