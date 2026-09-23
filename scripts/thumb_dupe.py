# -*- coding: utf-8 -*-
"""연결 글 카드 썸네일이 이번 글 사진과 같은 사진인지 가려낸다.

파일 해시로는 못 잡는다. 같은 사진이라도 크롭·리사이즈·재압축을 거치면 바이트가
달라지기 때문이다. 실제로 한국철도공사 건에서 대표사진과 카드 썸네일이 같은 사진인데
해시가 달라 "다르다"고 잘못 판정했다.

그래서 dHash(difference hash)를 쓴다. 그림을 9x8 회색조로 줄여 가로로 이웃한 밝기를
비교해 64비트를 만든다. 압축률·크기가 달라도 같은 장면이면 값이 거의 같다.
두 해시의 다른 비트 수(해밍 거리)가 임계값 이하면 같은 사진으로 본다.

**판정은 `scripts/score.py` 의 차단 검사가 한다.** 이 파일은 그 재료를 만드는
공용 함수 모음이고, 사람이 눈으로 확인할 때 쓰라고 단독 실행도 남겨 두었다.

단독 실행:
  uv run python scripts/thumb_dupe.py out/<slug>            이번 글 사진 vs 사이트 전체 글
  uv run python scripts/thumb_dupe.py out/<slug> --json     결과를 JSON 으로
"""
import argparse
import html
import io
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

SITE = "https://daeasy.co.kr"
CASES_URL = f"{SITE}/cases"
UA = {"User-Agent": "Mozilla/5.0 (prpub thumb-dupe)"}

# 같은 사진으로 볼 해밍 거리. 0 은 완전 동일, 10 이하면 크롭·재압축된 같은 장면이다.
SAME_MAX_DISTANCE = 10

# 본문에 적힌 교육후기 링크에서 slug 를 뽑는다.
CASE_LINK = re.compile(r"daeasy\.co\.kr/cases/([^\s)<\"']+)")


# ---------------------------------------------------------------- 공용 함수

def dhash(data: bytes, size: int = 8) -> int | None:
    """그림 한 장을 64비트 지문으로 바꾼다. 못 읽으면 None."""
    try:
        im = Image.open(io.BytesIO(data)).convert("L").resize((size + 1, size), Image.LANCZOS)
    except Exception:
        return None
    px = im.tobytes()   # 회색조라 바이트 하나가 화소 하나다
    bits = 0
    for row in range(size):
        base = row * (size + 1)
        for col in range(size):
            bits = (bits << 1) | (1 if px[base + col] > px[base + col + 1] else 0)
    return bits


def distance(a: int, b: int) -> int:
    """두 지문이 몇 비트나 다른가."""
    return bin(a ^ b).count("1")


def fetch(url: str, timeout: int = 20) -> bytes | None:
    """주소에서 내용을 가져온다. 실패하면 None — 빈 값과 구분해야 한다."""
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
    except Exception:
        return None


def linked_slugs(text: str) -> list[str]:
    """글에 걸린 교육후기 링크의 slug 를 나온 순서대로. 중복도 그대로 둔다."""
    return [urllib.parse.unquote(s) for s in CASE_LINK.findall(text)]


def case_image_url(slug: str) -> str | None:
    """교육후기 글의 카드 이미지(og:image) 주소. 못 읽으면 None."""
    page = fetch(f"{SITE}/cases/{urllib.parse.quote(slug)}")
    if page is None:
        return None
    m = re.search(rb'<meta property="og:image" content="([^"]*)"', page)
    return m.group(1).decode() if m else ""


def local_hashes(slug_dir: Path) -> list[tuple[str, int]]:
    """이번 글 사진들의 지문. (파일명, 지문) 목록."""
    out = []
    for f in sorted((slug_dir / "images").glob("*")):
        if not f.is_file():
            continue
        h = dhash(f.read_bytes())
        if h is not None:
            out.append((f.name, h))
    return out


def compare_to_local(mine: list[tuple[str, int]], image_url: str) -> dict:
    """카드 이미지 하나를 이번 글 사진들과 견준다.

    돌려주는 status 는 세 가지다.
      same     — 같은 사진. 연결 글로 쓰면 안 된다
      ok       — 확인했고 겹치지 않는다
      unknown  — 확인하지 못했다. "겹치지 않는다"가 아니다
    """
    if not image_url:
        return {"status": "unknown", "why": "카드 이미지 주소를 찾지 못함"}
    data = fetch(image_url)
    if data is None:
        return {"status": "unknown", "why": "카드 이미지를 받지 못함"}
    h = dhash(data)
    if h is None:
        return {"status": "unknown", "why": "카드 이미지를 읽지 못함"}
    if not mine:
        return {"status": "unknown", "why": "이번 글 사진을 읽지 못함"}
    d, name = min((distance(h, mh), n) for n, mh in mine)
    return {"status": "same" if d <= SAME_MAX_DISTANCE else "ok",
            "distance": d, "closest_photo": name}


def check_links(slug_dir: Path, text: str) -> list[dict]:
    """글에 걸린 연결 글마다 썸네일 중복 여부를 판정한다."""
    mine = local_hashes(slug_dir)
    rows = []
    for slug in dict.fromkeys(linked_slugs(text)):   # 같은 slug 는 한 번만 조회
        url = case_image_url(slug)
        if url is None:
            rows.append({"slug": slug, "status": "unknown", "why": "글 페이지를 열지 못함"})
            continue
        rows.append({"slug": slug, **compare_to_local(mine, url)})
    return rows


# ---------------------------------------------------------------- 단독 실행

def site_cases() -> list[dict]:
    """사이트에 게시된 교육후기 목록과 각 글의 카드 이미지 주소를 모은다."""
    page = fetch(CASES_URL, timeout=25)
    if not page:
        return []
    body = page.decode("utf-8", "ignore")
    out, seen = [], set()
    for seg in re.findall(r"<li>(.*?)</li>", body, re.S):
        m = re.search(r'href="/cases/([^"]+)"', seg)
        t = re.search(r"<h3[^>]*>(.*?)</h3>", seg, re.S)
        if not m or not t or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        out.append({"slug": m.group(1),
                    "title": html.unescape(re.sub(r"<[^>]+>", "", t.group(1))).strip()})
    for c in out:
        c["image"] = case_image_url(c["slug"]) or ""
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug_dir")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    d = Path(args.slug_dir)
    mine = local_hashes(d)
    if not mine:
        print("이번 글 사진을 읽지 못했습니다.", file=sys.stderr)
        return 1

    rows = []
    for c in site_cases():
        r = compare_to_local(mine, c["image"])
        rows.append({"slug": c["slug"], "title": c["title"], **r})
    rows.sort(key=lambda r: r.get("distance", 999))

    naver_md = d / "naver.md"
    linked = linked_slugs(naver_md.read_text(encoding="utf-8")) if naver_md.exists() else []
    verdict = check_links(d, naver_md.read_text(encoding="utf-8")) if naver_md.exists() else []
    bad = [v["slug"] for v in verdict if v["status"] == "same"]
    unknown = [v["slug"] for v in verdict if v["status"] == "unknown"]

    if args.json:
        print(json.dumps({"candidates": rows, "linked": linked, "verdict": verdict},
                         ensure_ascii=False, indent=2))
        return 1 if (bad or unknown) else 0

    print(f"이번 글 사진 {len(mine)}장 기준. 거리 {SAME_MAX_DISTANCE} 이하는 같은 사진으로 본다.\n")
    for r in rows:
        mark = {"same": "✗ 같은 사진", "ok": "○", "unknown": "? 확인 불가"}[r["status"]]
        tag = " ← 원고에 걸림" if r["slug"] in linked else ""
        dist = f"거리 {r['distance']:>2}" if "distance" in r else r.get("why", "")
        print(f"  {mark}  {dist:<18} {r['slug'][:34]:36} {r['title'][:28]}{tag}")

    print("\n원고에 걸린 연결 글:", ", ".join(linked) if linked else "없음")
    if bad:
        print("판정: 실패 — 같은 사진의 글을 걸고 있다:", ", ".join(bad))
        return 1
    if unknown:
        print("판정: 실패 — 확인하지 못한 글이 있다:", ", ".join(unknown))
        return 1
    print("판정: 통과 — 대표사진과 카드 썸네일이 겹치지 않는다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
