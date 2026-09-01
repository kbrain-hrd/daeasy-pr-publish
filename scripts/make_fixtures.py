"""테스트용 접수 폴더 생성 (docx / hwpx / hwp 각 1건 + 오류 1건).
사용: uv run python scripts/make_fixtures.py
"""

from pathlib import Path

from docx import Document
from PIL import Image

from prpub.parse import docx_value_cells
from prpub.template import convert_with_hwp

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "홍보자료_양식.docx"

VALUES = {
    "교육과정": "AI챔피언 그린",
    "교육 기관": "부산시",
    "교육 일자": "2026-08-25 ~ 2026-08-27",
    "참여 인원·대상": "32명, 주무관·데이터 담당자",
    "다룬 주제": "챗GPT 민원 답변 초안, 엑셀 데이터 정리, 대시보드 만들기",
    "실습 결과물": "민원 분류 대시보드 프로토타입 6개",
    "특별했던 점": "부서별 실제 민원 데이터로 실습. 만족도 4.7/5, 32명 중 29명 인증 합격",
    "참가자가 한 말 (선택)": '"이건 내일 바로 써먹겠다"\n"엑셀만 쓰다가 눈이 트였다"',
    "게시 위치": "교육후기",
    "게시 희망일": "2026-09-05",
    "강조할 점 (선택)": "공공기관 최초 자체 데이터 실습 사례",
    "등록자": "이예진 / 사업4팀",
}


def fill(src: Path, dst: Path, vals: dict[str, str]) -> None:
    doc = Document(str(src))
    for f, cell in docx_value_cells(doc):
        cell.paragraphs[0].text = vals.get(f.label, "")
    doc.save(str(dst))


def make(folder: Path, ext: str, vals: dict[str, str], with_files: bool = True) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    docx = folder / "홍보자료_양식.docx"
    fill(TEMPLATE, docx, vals)
    if ext != ".docx":
        convert_with_hwp(docx, ext.lstrip(".").upper(), folder / f"홍보자료_양식{ext}")
        docx.unlink()
    if with_files:
        (folder / "사진").mkdir(exist_ok=True)
        (folder / "자료").mkdir(exist_ok=True)
        for i, col in enumerate([(37, 99, 235), (16, 185, 129)], 1):
            Image.new("RGB", (2400, 1600), col).save(folder / "사진" / f"현장{i}.jpg")
        (folder / "자료" / "결과보고서.pdf").write_bytes(b"%PDF-1.4\n%fixture\n")


if __name__ == "__main__":
    inbox = ROOT / "접수함"
    make(inbox / "2026-08-25_부산시_그린5회차", ".docx", VALUES)
    make(inbox / "2026-08-25_부산시_그린5회차_hwpx", ".hwpx", VALUES)
    make(inbox / "2026-08-25_부산시_그린5회차_hwp", ".hwp", VALUES)
    bad = dict(VALUES, **{"교육 기관": "", "교육 일자": "8월 25일"})
    make(inbox / "2026-08-30_오류테스트", ".docx", bad, with_files=False)
    print("fixtures ok")
