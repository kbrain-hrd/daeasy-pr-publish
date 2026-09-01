"""양식 항목 정의. 양식 파일(docx/hwpx/hwp)의 표 항목명과 1:1로 대응한다.

글(제목·본문)은 LLM 이 작성한다. 등록자에게는 사실과 에피소드만 받는다.
사진 설명·대표 사진·관련 링크는 양식에서 받지 않고 /홍보발행 에서 LLM 이 정한다.
"""

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    required: bool = False
    choices: tuple[str, ...] = ()
    hint: str = ""
    multiline: bool = False
    half: bool = False  # True 면 다음 half 항목과 좌우 2단으로 배치


CATEGORIES = ("교육후기", "인사이트", "뉴스·보도자료", "교육 산출물", "기타")
COURSES = (
    "AI챔피언 그린",
    "AI챔피언 블루",
    "AI 리터러시",
    "데이터 리터러시",
    "생성형 AI 활용 업무 효율화",
    "AI 서비스 융합 기획",
    "기타",
)

PHOTO_DIR = "사진"
ATTACH_DIR = "자료"

# (구분 제목 "번호 이름", 설명) — 각 구분의 첫 항목 key 에 매핑
SECTIONS: dict[str, tuple[str, str]] = {
    "course": ("01 기본 정보", ""),
    "topics": ("02 교육 내용", ""),
    "quotes": ("03 참여자 반응", ""),
    "category": ("04 게시 정보", ""),
    "submitter": ("05 등록자", ""),
}

FIELDS: tuple[Field, ...] = (
    # 01 기본 정보
    Field("course", "교육과정", choices=COURSES, hint="목록에 없으면 과정명을 직접 기재"),
    Field("org", "교육 기관", required=True, hint="예) 부산시, 농촌진흥청"),
    Field("dates", "교육 일자", required=True, hint="예) 2026-08-25 ~ 2026-08-27  (1일 교육은 날짜 하나)", half=True),
    Field("participants", "참여 인원·대상", required=True, hint="예) 32명, 주무관·데이터 담당자", half=True),
    # 02 교육 내용
    Field("topics", "다룬 주제", required=True, hint="2~3개. 예) 챗GPT 민원 답변 초안, 엑셀 데이터 정리"),
    Field("outputs", "실습 결과물", hint="예) 민원 분류 대시보드 6개"),
    Field("highlight", "특별했던 점", multiline=True, hint="예) 부서별 실제 데이터로 실습, 현장 발표회. 만족도·합격률 등 수치가 있으면 함께"),
    # 03 참여자 반응
    Field("quotes", "참가자가 한 말 (선택)", multiline=True, hint='1~2개, 발언 그대로. 예) "내일 업무에 바로 적용하겠다"'),
    # 04 게시 정보
    Field("category", "게시 위치", required=True, choices=CATEGORIES, half=True),
    Field("publish_at", "게시 희망일", hint="예) 2026-09-05", half=True),
    Field("key_message", "강조할 점 (선택)", hint='예) "공공기관 최초 자체 데이터 실습 사례"'),
    # 05 등록자
    Field("submitter", "등록자", required=True, hint="이름 / 팀. 예) 이예진 / 사업4팀"),
)

BY_LABEL: dict[str, Field] = {f.label: f for f in FIELDS}
BY_KEY: dict[str, Field] = {f.key: f for f in FIELDS}

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"}
ATTACH_EXT = {".pdf", ".ppt", ".pptx", ".doc", ".docx", ".hwp", ".hwpx", ".xls", ".xlsx", ".zip", ".mp4"}
FORM_EXT = {".docx", ".hwpx", ".hwp"}


_SECTION_LINE = re.compile(r"^\d{2}\s")


def normalize_label(text: str) -> str:
    """표 셀의 항목명을 FIELDS.label 형태로 정규화.

    별표·공백 제거. 칸 안에 구분 제목("01 기본 정보")이 먼저 올 수 있으므로
    그런 줄은 건너뛰고 첫 항목명 줄을 쓴다.
    """
    for line in text.replace("*", "").replace("＊", "").replace("★", "").split("\n"):
        t = " ".join(line.split())
        if not t or _SECTION_LINE.match(t):
            continue
        return t
    return ""


@dataclass
class Entry:
    """접수함의 폴더 하나 = 게시글 하나."""

    folder: str
    form_file: str
    data: dict[str, str] = field(default_factory=dict)
    photos: list[str] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def date_from(self) -> str:
        return self.data.get("dates", "").strip()[:10]

    @property
    def headline(self) -> str:
        """목록 표시용: 기관 · 과정 · 일자."""
        d = self.data
        return " · ".join(x for x in (d.get("org"), d.get("course"), self.date_from) if x)
