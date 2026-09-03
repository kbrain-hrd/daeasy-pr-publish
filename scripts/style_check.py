"""글의 문체 지표를 잰다.

AI 가 쓴 글은 사람 글보다 어휘가 덜 다양하고, 문장 길이가 고르고, 같은 표현이
반복된다는 것이 문헌에서 반복 확인된 특징이다. 그것을 숫자로 뽑아 사람이 쓴
기존 글과 견줘 본다.

사용:
  uv run python scripts/style_check.py <파일...>
"""

import re
import statistics
import sys
from pathlib import Path

# 우리 글에서 실제로 반복됐거나, 한국어 AI 글에 흔한 상투어
CLICHES = [
    "시간을 가졌습니다", "시간이었습니다", "자리였습니다", "뜻깊은",
    "혁신적인", "다양한", "성공적으로", "함께했습니다", "빛났습니다",
    "한층 더", "더욱더", "발판이 되", "계기가 되", "기대를 모으",
    "높은 관심", "열기를 더", "의미를 더", "새로운 도약",
]

# 완곡·유보 표현 (헤징). 사실을 흐린다
HEDGES = ["것으로 보인다", "것으로 보입니다", "듯하다", "듯합니다",
          "라고 할 수 있다", "라고 할 수 있습니다", "may", "아마도", "다소"]


def sentences(text: str) -> list[str]:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)      # 이미지
    text = re.sub(r"^---.*?^---", " ", text, flags=re.S | re.M)  # 앞머리
    text = re.sub(r"[#>*`\[\]()|]", " ", text)
    text = re.sub(r"─+", " ", text)
    text = re.sub(r"#\S+", " ", text)                        # 해시태그
    parts = re.split(r"(?<=[.!?])\s+|(?<=다)\.\s*", text)
    return [s.strip() for s in parts if len(s.strip()) > 8]


def words(text: str) -> list[str]:
    return re.findall(r"[가-힣]{2,}", text)


def measure(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    ss = sentences(raw)
    ws = words(raw)
    lens = [len(s) for s in ss]

    # 어휘 다양성 — 같은 길이에서 비교하려고 앞 400 단어로 자른다
    sample = ws[:400]
    ttr = len(set(sample)) / len(sample) if sample else 0

    cl = sum(raw.count(c) for c in CLICHES)
    hg = sum(raw.count(h) for h in HEDGES)

    # 같은 어미로 끝나는 문장이 몰리면 단조롭다
    endings = [s[-6:] for s in ss]
    top_end = max((endings.count(e) for e in set(endings)), default=0)

    return {
        "파일": path.name,
        "문장": len(ss),
        "평균길이": round(statistics.mean(lens), 1) if lens else 0,
        "길이편차": round(statistics.pstdev(lens), 1) if len(lens) > 1 else 0,
        "어휘다양성": round(ttr, 3),
        "상투어": cl,
        "헤징": hg,
        "같은어미최다": top_end,
    }


def main(paths: list[str]) -> None:
    rows = [measure(Path(p)) for p in paths if Path(p).exists()]
    if not rows:
        print("잴 파일이 없습니다.")
        return
    cols = ["파일", "문장", "평균길이", "길이편차", "어휘다양성", "상투어", "헤징", "같은어미최다"]
    w = {c: max(len(c), max(len(str(r[c])) for r in rows)) for c in cols}
    print(" | ".join(c.ljust(w[c]) for c in cols))
    print("-+-".join("-" * w[c] for c in cols))
    for r in rows:
        print(" | ".join(str(r[c]).ljust(w[c]) for c in cols))


if __name__ == "__main__":
    main(sys.argv[1:])
