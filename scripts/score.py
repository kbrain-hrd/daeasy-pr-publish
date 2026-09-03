"""홍보글을 루브릭으로 채점한다.

`docs/홍보글-루브릭.md` 의 기준 중 **코드로 셀 수 있는 것만** 여기서 잰다.
대체 불가능성·현장 증거처럼 판단이 필요한 항목은 사람(또는 LLM)이 따로 매긴다.
LLM 에게 "이 글 몇 점?"이라고 묻지 않는 것이 이 설계의 요점이다.

사용:
  uv run python scripts/score.py <out/폴더명>
"""

import io
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CLICHES = [
    "시간을 가졌습니다", "시간이었습니다", "자리였습니다", "뜻깊은",
    "혁신적인", "성공적으로", "함께했습니다", "빛났습니다",
    "한층 더", "더욱더", "발판이 되", "계기가 되", "기대를 모으",
    "높은 관심", "열기를 더", "새로운 도약",
]
HEDGES = ["것으로 보인다", "것으로 보입니다", "듯하다", "듯합니다",
          "라고 할 수 있다", "라고 할 수 있습니다", "아마도", "다소"]

# Herbold et al. (Scientific Reports 2023): AI 글은 사람 글보다 담론 표지가 적고
# 명사화가 많다. 어휘 다양성은 오히려 AI 가 높아서, 낮다고 경고하면 방향이 거꾸로다.
DISCOURSE = ["그런데", "하지만", "그러나", "다만", "물론", "사실", "오히려",
             "그래서", "그러니까", "한편", "게다가", "결국", "즉"]
NOMINAL = re.compile(r"[가-힣]{2,}(?:화|성|적|함|됨|기|것)(?:을|를|이|가|은|는|의|에|으로|로)")

# 태그가 갖춰야 할 다섯 묶음 (루브릭 4단계 해시태그 규칙)
TAG_GROUPS = {
    "브랜드": ["데이지", "DAEASY", "케이브레인컴퍼니", "공공기관AI"],
    "마무리": ["업무혁신", "디지털전환", "DX", "AX"],
}


def split_front(raw: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not m:
        return {}, raw
    meta = {}
    for line in m.group(1).split("\n"):
        k, _, v = line.partition(":")
        if v:
            meta[k.strip()] = v.strip()
    return meta, m.group(2)


def body_text(body: str) -> str:
    t = re.sub(r"^\[.*?\]$", " ", body, flags=re.M)   # [대표사진] 등
    t = re.sub(r"─+", " ", t)
    t = re.sub(r"#\S+", " ", t)
    return t


def sentences(t: str) -> list[str]:
    parts = re.split(r"(?<=다)\.\s*|(?<=[.!?])\s+", t)
    return [s.strip() for s in parts if len(s.strip()) > 8]


def search_score(meta: dict, body: str, org: str, course: str) -> tuple[float, list[str]]:
    """루브릭 5절 채점표. 7개 항목, 합 5.0"""
    got, notes = 0.0, []
    title = meta.get("제목", "")
    text = body_text(body)
    plain = re.sub(r"\s+", "", text)
    keys = [k for k in (org, course) if k]

    # 1. 제목 앞 절반에 검색어 (1.0)
    half = title[: max(1, len(title) // 2)]
    if any(k and k.replace(" ", "") in half.replace(" ", "") for k in keys):
        got += 1.0
    else:
        notes.append("제목 앞쪽에 기관·과정명이 없다")

    # 2. 첫 문단에 기관·과정·행위 (1.0)
    first = next((p for p in text.split("\n") if len(p.strip()) > 30), "")
    hit = sum(1 for k in keys if k.replace(" ", "") in first.replace(" ", ""))
    if hit >= len(keys) and re.search(r"(진행|운영|열렸|개최|했다|합니다)", first):
        got += 1.0
    else:
        notes.append("첫 문단에 기관·과정·행위가 다 들어가지 않았다")

    # 3. 소제목이 검색어를 품음 (0.5)
    heads = [ln for ln in body.split("\n") if 0 < len(ln.strip()) <= 40 and ln.startswith("## ")]
    heads += [ln.strip() for ln in body.split("\n") if 0 < len(ln.strip()) <= 40 and not ln.startswith(("#", "[", "-", "운영사", "브랜드", "이메일", "홈페이지", "SNS"))]
    if any(any(k and k.replace(" ", "") in h.replace(" ", "") for k in keys) for h in heads):
        got += 0.5
    else:
        notes.append("소제목에 검색어가 하나도 없다")

    # 4. 태그 12~16개 + 다섯 묶음 (1.0)
    tags = [t.strip() for t in meta.get("태그", "").split(",") if t.strip()]
    joined = " ".join(tags)
    groups_ok = all(any(w in joined for w in ws) for ws in TAG_GROUPS.values())
    # 기관명이 "공모 선발 (공공기관)" 처럼 기관이 아닌 경우가 있어 통째로 대조하지 않는다.
    # 이름에서 뽑은 낱말 하나라도 태그에 있으면 인정한다.
    org_words = [w for w in re.findall(r"[가-힣A-Za-z]{2,}", org) if w not in ("선발", "공모", "기관")]
    org_ok = (not org_words) or any(w in joined for w in org_words)
    if 12 <= len(tags) <= 16 and groups_ok and org_ok:
        got += 1.0
    else:
        notes.append(f"태그 {len(tags)}개 (12~16 권장) 또는 묶음 누락")

    # 5. 본문 1,500자 이상 (0.5)
    n = len(plain)
    if n >= 1500:
        got += 0.5
    else:
        notes.append(f"본문 {n}자 (1,500자 이상 권장)")

    # 6. 사진 2장 이상 (0.5)
    photos = len(re.findall(r"^\[(?:대표)?사진\]$", body, flags=re.M)) + len(re.findall(r"!\[", body))
    if photos >= 2:
        got += 0.5
    else:
        notes.append(f"사진 {photos}장 (2장 이상 권장)")

    # 7. 사이트 링크 (0.5)
    if "daeasy.vercel.app" in body:
        got += 0.5
    else:
        notes.append("사이트로 가는 링크가 없다")

    return got, notes


def style_score(body: str) -> tuple[dict, list[str]]:
    t = body_text(body)
    ss = sentences(t)
    lens = [len(s) for s in ss]
    ws = re.findall(r"[가-힣]{2,}", t)
    sample = ws[:400]
    ttr = len(set(sample)) / len(sample) if sample else 0
    cl = sum(t.count(c) for c in CLICHES)
    hg = sum(t.count(h) for h in HEDGES)

    # 담론 표지 밀도 — 100문장당 몇 개인가. AI 글은 이게 적다
    disc = sum(t.count(d) for d in DISCOURSE)
    disc_per100 = round(disc / len(ss) * 100, 1) if ss else 0
    # 명사화 밀도 — AI 글은 이게 많다
    nom_per100 = round(len(NOMINAL.findall(t)) / len(ss) * 100, 1) if ss else 0

    # 경고를 내는 것은 기준선이 확인된 지표뿐이다.
    # 담론 표지·명사화·길이 편차는 아직 기준선이 없다 — 사람이 쓴 기존 글은
    # HTML 에서 뽑아 문장 경계가 부정확했다. 값만 보여주고 판정하지 않는다.
    # 근거 없이 임계값을 정하면 그 자체가 평가 오류다 (Gehrmann et al., JAIR 2023).
    notes = []
    if cl:
        notes.append(f"상투어 {cl}회")
    if hg:
        notes.append(f"헤징 {hg}회 — 사실을 흐린다")

    return {
        "문장": len(ss),
        "평균길이": round(statistics.mean(lens), 1) if lens else 0,
        "길이편차": round(statistics.pstdev(lens), 1) if len(lens) > 1 else 0,
        "어휘다양성": round(ttr, 3),
        "담론표지": disc_per100,
        "명사화": nom_per100,
        "상투어": cl,
        "헤징": hg,
    }, notes


def duplicates(body: str) -> list[str]:
    """글자 그대로 되풀이된 문단을 찾는다.

    AI 글의 대표 결함이 언어 중복이라는 것이 문헌에서 확인됐다 (Ma 외 2023).
    사람이 눈으로 훑으면 멀리 떨어진 두 문단이 같다는 것을 놓치기 쉽다.
    루브릭 3절 6번(군더더기 없음)을 매길 때 이 결과를 먼저 본다.
    """
    paras = []
    for p in body_text(body).split("\n"):
        t = re.sub(r"\s+", " ", p).strip()
        if len(t) >= 25:  # 짧은 줄은 맺음 블록·라벨이라 뺀다
            paras.append(t)

    found, seen = [], {}
    for i, p in enumerate(paras, start=1):
        key = re.sub(r"[^가-힣A-Za-z0-9]", "", p)
        if key in seen:
            found.append(f"{seen[key]}번째와 {i}번째 문단이 같다: \"{p[:34]}…\"")
        else:
            seen[key] = i
    return found


def blocking(slug_dir: Path, meta: dict, body: str) -> list[str]:
    """루브릭 2절 차단 검사. 걸리면 발행하지 않는다."""
    fails = []

    if not (slug_dir / "insight.md").exists():
        fails.append("insight.md 없음 — 이 회차의 발견 한 줄을 먼저 쓴다")

    brief = (slug_dir / "brief.md")
    src = brief.read_text(encoding="utf-8") if brief.exists() else ""
    res = (slug_dir / "research.md")
    if res.exists():
        src += res.read_text(encoding="utf-8")

    if src:
        # 본문의 숫자가 원자료에 있는가.
        # 날짜는 표기가 갈려(2026-07-21 / 7월 21일 / 07.21) 그대로 대조하면 오탐이라 뺀다.
        t = body_text(body)
        t = re.sub(r"\d{1,2}\s*[.\-/월]\s*\d{1,2}\s*일?", " ", t)
        t = re.sub(r"20\d\d\s*[.\-년]?", " ", t)
        nums = set(re.findall(r"\d+(?:\.\d+)?", t))
        src_nums = set(re.findall(r"\d+(?:\.\d+)?", src))
        missing = sorted(n for n in nums - src_nums if len(n) > 1)
        if missing:
            fails.append(f"원자료에 없는 숫자: {', '.join(missing[:6])}")

        # 인용문이 원자료에 그대로 있는가
        for q in re.findall(r'"([^"]{6,60})"', body):
            if q not in src:
                fails.append(f"원자료에 없는 인용: \"{q[:24]}…\"")

    imgs = slug_dir / "images"
    have = len(list(imgs.glob("*"))) if imgs.exists() else 0
    used = len(re.findall(r"^\[(?:대표)?사진\]$", body, flags=re.M)) + len(re.findall(r"!\[", body))
    if used > have:
        fails.append(f"사진 자리 {used}개인데 파일은 {have}장")

    title = meta.get("제목", "")
    if title and len(title) > 60:
        fails.append(f"제목 {len(title)}자 — 60자 이하")

    return fails


def report(slug_dir: Path) -> None:
    meta_json = slug_dir / "meta.json"
    m = json.loads(meta_json.read_text(encoding="utf-8")) if meta_json.exists() else {}
    org = m.get("org") or m.get("교육기관") or ""
    course = m.get("course") or m.get("교육과정") or ""

    for name in ("naver.md", "post.md"):
        f = slug_dir / name
        if not f.exists():
            continue
        raw = io.open(f, encoding="utf-8").read()
        meta, body = split_front(raw)

        print(f"\n=== {name} ===")
        fails = blocking(slug_dir, meta, body)
        print("차단 검사:", "통과" if not fails else "차단")
        for x in fails:
            print("  X", x)

        if name == "naver.md":
            s, notes = search_score(meta, body, org, course)
            print(f"검색 노출: {s:.1f} / 5.0")
            for x in notes:
                print("  -", x)

        dups = duplicates(body)
        print("중복 문단:", "없음" if not dups else f"{len(dups)}건")
        for x in dups:
            print("  -", x)

        st, snotes = style_score(body)
        print("문체 지표:", " · ".join(f"{k} {v}" for k, v in st.items()))
        for x in snotes:
            print("  -", x)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    d = Path(sys.argv[1])
    if not d.is_absolute():
        d = ROOT / d
    report(d)
