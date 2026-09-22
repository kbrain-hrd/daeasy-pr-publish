"""양식 항목 정의. 양식 파일(docx/hwpx/hwp)의 표 항목명과 1:1로 대응한다.

글(제목·본문)은 LLM 이 작성한다. 등록자에게는 사실과 어필 포인트만 받는다.
사진 설명·대표 사진·관련 링크는 양식에서 받지 않고 /홍보발행 에서 LLM 이 정한다.

게시 위치·게시 희망일은 받지 않는다 — 우리가 직접 정하면 되는 것이라 물을 이유가 없다.
대신 희망 헤드라인·해시태그를 받는다. 담당자가 "이 글로 뭘 말하고 싶은지" 한 번
생각해보게 하는 것이 목적이라 필수는 아니다. 비면 LLM 이 정한다.
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

PHOTO_DIR = "사진"
ATTACH_DIR = "자료"

# (구분 제목 "번호 이름", 설명) — 각 구분의 첫 항목 key 에 매핑
SECTIONS: dict[str, tuple[str, str]] = {
    "course_name": ("01 기본 정보", ""),
    "goal": ("02 교육 주요 내용", ""),
    "satisfaction": ("03 교육 만족도", ""),
    "headline": ("04 게시 방향", ""),
}

FIELDS: tuple[Field, ...] = (
    # 01 기본 정보
    Field(
        "course_name",
        "교육명",
        required=True,
        hint="이번 교육의 공식 명칭을 작성해 주세요. 예) 부산시 공무원 AI 역량강화 교육",
        half=True,
    ),
    Field(
        "course",
        "교육과정",
        required=True,
        hint="해당하는 교육과정명을 작성해 주세요. 예) AI 챔피언 그린 / 데이터 리터러시 / 생성형 AI 활용교육",
        half=True,
    ),
    Field("org", "교육기관", required=True, hint="교육 대상 기관을 작성해 주세요. 예) 부산광역시 / 농촌진흥청"),
    Field(
        "dates",
        "교육 일자",
        required=True,
        hint="교육 진행 기간을 작성해 주세요. 예) 2026-07-21 ~ 2026-08-25  (1일 교육은 날짜 하나)",
        half=True,
    ),
    Field("round", "회차", hint="해당 회차 또는 기수를 작성해 주세요. 예) 3회차, 상반기 2기", half=True),
    Field(
        "participants",
        "교육 대상·인원",
        required=True,
        hint="참여 규모와 주요 대상을 함께 작성해 주세요. 예) 공무원 109명 / 연구직·행정직 실무자 35명",
    ),
    # 02 교육 주요 내용
    Field(
        "goal",
        "교육 목표",
        multiline=True,
        hint="이번 교육을 통해 참여자가 무엇을 배우거나 할 수 있도록 했는지 작성해 주세요.",
    ),
    Field(
        "process",
        "교육 구성",
        multiline=True,
        hint="교육이 어떤 순서와 방식으로 진행되었는지 구체적으로 작성해 주세요. "
        "예) 사전 이러닝 → 집합교육 → 팀 프로젝트 → 결과 발표 → 인증평가",
    ),
    Field(
        "topics",
        "교육 내용",
        required=True,
        multiline=True,
        hint="주요 교육내용을 3~5개로 나누어 작성해 주세요. "
        "제목만 나열하기보다 무엇을 했는지 짧게 덧붙이면 좋습니다.",
    ),
    Field(
        "outputs",
        "실습 결과물",
        hint="교육을 통해 실제로 만든 결과물이 있다면 작성해 주세요. "
        "예) 민원 답변 초안 생성 서비스 / 업무 자동화 프로토타입 6건 / 공공서비스 개선 아이디어 8건",
    ),
    Field(
        "output_links",
        "산출물 자료",
        multiline=True,
        hint="산출물을 확인할 수 있는 파일이나 링크를 적어 주세요. 파일은 '자료' 폴더에 함께 넣어 주세요. "
        "예) 업무템플릿_8종.zip / https://drive.google.com/…",
    ),
    Field(
        "highlight",
        "이 과정의 주요 포인트",
        multiline=True,
        hint="다른 교육과의 차별화. 현장에서 인상 깊었던 장면이 있으면 함께. "
        "예) 샘플 데이터가 아니라 참여자가 실제로 쓰는 부서 데이터로 실습했습니다",
    ),
    Field(
        "scene",
        "(운영자 관점) 현장에서 인상 깊었던 내용",
        multiline=True,
        hint="교육생 반응, 발표, 프로젝트, 강사 피드백 등 소개하고 싶은 장면을 작성해 주세요. "
        "예) 교육생들이 자신의 부서 업무를 직접 AI 서비스로 구현하며 높은 참여도를 보임",
    ),
    # 03 교육 만족도
    Field(
        "satisfaction",
        "교육 만족도",
        required=True,
        hint="10점 만점 기준으로 적어주세요. 예) 9.0 / 10점 (106명 응답)",
    ),
    # 04 게시 방향
    Field(
        "headline",
        "게시글 헤드라인",
        required=True,
        hint="이 글의 제목을 뭐라고 뽑고 싶으신가요. 문장이 아니어도 됩니다",
    ),
    Field(
        "hashtags",
        "해시태그",
        required=True,
        hint="어떤 태그를 걸고 싶으신가요. 예) #AI챔피언 #공공데이터 #디지털전환",
    ),
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
