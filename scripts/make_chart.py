"""게시글에 넣을 그래픽을 만든다. 수치를 보고 형태를 알아서 고른다.

왜 고르는가 — 단계별 인원을 그냥 막대로 늘어놓으면 값이 줄어드는 그림이 되어
성과가 손실처럼 읽힌다. 인증률 85%는 "85%를 달성"이지 "15%를 잃음"이 아니다.

고르는 규칙
  달성률이 70% 이상        → 미터(meter). 큰 숫자 + 채움 막대. 달성으로 읽힌다.
  달성률이 70% 미만        → 가로 막대. 단계별 차이를 보여주는 것이 맞다.
  단계가 둘뿐              → 미터. 막대 두 개는 그래프로 칠 것이 없다.

지원 인원은 넣지 않는다. 정원 제한 때문에 줄어든 것이라 성과와 성격이 다르다.
경쟁률은 부제로 적는다.

사용:
  uv run python scripts/make_chart.py --out docs/preview/img/green3.svg \\
      --stages "선발=109,수료=98,인증=93" \\
      --title "인증률" --sub "271명이 지원해 경쟁률 2.7 : 1"
"""
import argparse
from pathlib import Path

INK = "#18181B"
MUTED = "#A1A1AA"
LABEL = "#52525B"
TRACK = "#E4E4E7"
ACCENT = "#2563EB"
FONT = '"Malgun Gothic","맑은 고딕","Apple SD Gothic Neo",system-ui,sans-serif'

METER_THRESHOLD = 0.70


def _style() -> str:
    return f"""  <style>
    .cap {{ font: 600 12.5px {FONT}; fill:{ACCENT}; letter-spacing:.04em; }}
    .hero{{ font: 800 52px {FONT}; fill:{INK}; }}
    .sub {{ font: 400 15px {FONT}; fill:{LABEL}; }}
    .l   {{ font: 600 14px {FONT}; fill:{LABEL}; }}
    .v   {{ font: 700 15px {FONT}; fill:{INK}; }}
    .end {{ font: 600 13px {FONT}; fill:{MUTED}; }}
    .src {{ font: 400 12px {FONT}; fill:{MUTED}; }}
  </style>"""


def meter(stages: list[tuple[str, int]], title: str, sub: str, source: str) -> str:
    (whole_label, whole), (part_label, part) = stages[0], stages[-1]
    pct = round(part / whole * 100)
    filled = round(720 * part / whole)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 190" width="760" height="190" role="img" aria-label="{title} {pct}퍼센트. {whole_label} {whole}명 중 {part_label} {part}명.">
  <title>{title} {pct}% — {sub}</title>
{_style()}
  <rect width="760" height="190" fill="#ffffff"/>
  <text class="cap" x="0" y="16">{title}</text>
  <text class="hero" x="0" y="72">{pct}%</text>
  <text class="sub" x="126" y="70">{whole_label} {whole}명 가운데 {part}명이 {part_label}을 받았습니다</text>
  <rect x="0" y="110" width="720" height="18" rx="9" fill="{TRACK}"/>
  <rect x="0" y="110" width="{filled}" height="18" rx="9" fill="{ACCENT}"/>
  <text class="end" x="724" y="124">{whole}명</text>
  <text class="src" x="0" y="158">{source}</text>
</svg>
"""


def bars(stages: list[tuple[str, int]], title: str, sub: str, source: str) -> str:
    top = max(v for _, v in stages)
    rows, y = [], 72
    for label, value in stages:
        w = round(560 * value / top)
        rows.append(
            f'  <text class="l" x="86" y="{y + 16}" text-anchor="end">{label}</text>\n'
            f'  <rect x="96" y="{y}" width="{w}" height="26" rx="4" fill="{ACCENT}"/>\n'
            f'  <text class="v" x="{96 + w + 12}" y="{y + 18}">{value}명</text>'
        )
        y += 52
    height = y + 60
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 {height}" width="760" height="{height}" role="img" aria-label="{title}. {', '.join(f'{k} {v}명' for k, v in stages)}.">
  <title>{title} — {sub}</title>
{_style()}
  <rect width="760" height="{height}" fill="#ffffff"/>
  <text class="cap" x="0" y="16">{title}</text>
  <text class="sub" x="0" y="42">{sub}</text>
  <line x1="96" y1="62" x2="96" y2="{y - 26}" stroke="{TRACK}" stroke-width="1"/>
{chr(10).join(rows)}
  <text class="src" x="96" y="{height - 16}">{source}</text>
</svg>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stages", required=True, help='예) "선발=109,수료=98,인증=93"')
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="인증률")
    ap.add_argument("--sub", default="")
    ap.add_argument("--source", default="자료 · K-Brain EMS")
    a = ap.parse_args()

    stages = []
    for part in a.stages.split(","):
        k, _, v = part.partition("=")
        stages.append((k.strip(), int(v)))
    if len(stages) < 2:
        raise SystemExit("단계가 둘 이상이어야 합니다.")

    rate = stages[-1][1] / stages[0][1]
    form = "meter" if (rate >= METER_THRESHOLD or len(stages) == 2) else "bars"
    svg = (meter if form == "meter" else bars)(stages, a.title, a.sub, a.source)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8")
    print("%s (달성률 %.0f%%) → %s" % (form, rate * 100, out))


if __name__ == "__main__":
    main()
