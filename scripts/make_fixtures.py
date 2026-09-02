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
    "교육명": "부산시 공무원 AI 역량강화 교육",
    "교육과정": "AI 챔피언 그린",
    "교육기관": "부산시",
    "교육 일자": "2026-08-25 ~ 2026-08-27",
    "회차": "5회차",
    "참여 인원·대상": "32명, 주무관·데이터 담당자",
    "핵심내용": "챗GPT 로 민원 답변 초안 쓰기\n엑셀 데이터 정리\n부서 데이터로 대시보드 만들기",
    "과정 내용": "사전 온라인 2일 → 집합수업 3일 → 결과 발표",
    "실습 결과물": "민원 분류 대시보드 프로토타입 6개",
    "이 과정의 주요 포인트": "부서별 실제 민원 데이터로 실습했습니다.\n32명 중 29명이 인증에 합격했습니다.",
    "교육 만족도": "9.4 / 10점 (30명 응답)",
    "게시글 헤드라인": "공공기관 최초, 자체 민원 데이터로 실습했습니다",
    "해시태그": "#AI챔피언 #부산시 #공공데이터",
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
    bad = dict(VALUES, **{"교육기관": "", "교육 일자": "8월 25일"})
    make(inbox / "2026-08-30_오류테스트", ".docx", bad, with_files=False)
    print("fixtures ok")
