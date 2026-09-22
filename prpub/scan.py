"""접수함 폴더를 훑어 Entry 목록을 만들고 검증한다."""

import re
from pathlib import Path

from .parse import embedded_photos, parse_form
from .schema import (
    ATTACH_DIR,
    ATTACH_EXT,
    FIELDS,
    FORM_EXT,
    PHOTO_DIR,
    PHOTO_EXT,
    Entry,
)

_DATES_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:\s*~\s*(\d{4}-\d{2}-\d{2}))?$")


def _files(folder: Path, sub: str, exts: set[str]) -> list[str]:
    d = folder / sub
    if not d.is_dir():
        return []
    return sorted(str(p) for p in d.iterdir() if p.is_file() and p.suffix.lower() in exts)


def _validate(e: Entry) -> None:
    d = e.data
    for f in FIELDS:
        if f.required and not d.get(f.key, "").strip():
            e.errors.append(f"항목 비어 있음: {f.label}")
    dates = d.get("dates", "").strip()
    if dates:
        m = _DATES_RE.match(dates)
        if not m:
            e.errors.append(f"교육 일자 형식 오류: '{dates}' (YYYY-MM-DD 또는 YYYY-MM-DD ~ YYYY-MM-DD)")
        elif m.group(2) and m.group(2) < m.group(1):
            e.errors.append("교육 종료일이 시작일보다 앞섭니다")
    if not e.photos and not e.attachments:
        if e.form_file and embedded_photos(Path(e.form_file)):
            e.warnings.append("사진이 양식 문서에 임베드돼 있음 — build 가 자동 추출한다")
        else:
            e.errors.append(f"'{PHOTO_DIR}' 또는 '{ATTACH_DIR}' 폴더에 파일이 하나도 없음")
    if not d.get("highlight", "").strip():
        e.warnings.append("이 과정의 주요 포인트가 비어 있음 — 수치 나열 위주의 글이 됨")
    topics = d.get("topics", "").strip()
    if topics and thin_topics(topics):
        e.errors.append(
            f"교육 내용이 너무 짧음 ({len(topics)}자) — 3~5개 항목에 각각 무엇을 했는지 한 줄씩 적어주세요. "
            "제목만 나열하면 글에 쓸 재료가 없어 채점을 통과하지 못합니다"
        )


TOPICS_MIN_CHARS = 120
TOPICS_MIN_DETAIL_LINES = 2  # 20자 넘는 줄이 이만큼은 있어야 "무엇을 했는지" 가 적힌 것으로 본다


def thin_topics(text: str) -> bool:
    """교육 내용이 제목 나열 수준인지. LLM 을 10번 부르기 전에 접수에서 돌려보내기 위한 코드 검사."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    detail = sum(1 for ln in lines if len(ln) > 20)
    return len(text) < TOPICS_MIN_CHARS or detail < TOPICS_MIN_DETAIL_LINES


def scan_entry(folder: Path) -> Entry:
    forms = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in FORM_EXT)
    if not forms:
        e = Entry(folder=str(folder), form_file="")
        e.errors.append("양식 파일(.hwp/.hwpx/.docx)이 없음")
        return e
    if len(forms) > 1:
        # 우선순위: hwpx > docx > hwp (hwp 는 변환이 필요해 마지막)
        forms.sort(key=lambda p: {".hwpx": 0, ".docx": 1, ".hwp": 2}[p.suffix.lower()])
    form = forms[0]
    e = Entry(folder=str(folder), form_file=str(form))
    try:
        e.data = parse_form(form)
    except Exception as ex:  # noqa: BLE001
        e.errors.append(f"양식 파싱 실패: {ex}")
        return e
    e.photos = _files(folder, PHOTO_DIR, PHOTO_EXT)
    e.attachments = _files(folder, ATTACH_DIR, ATTACH_EXT)
    _validate(e)
    return e


def scan_inbox(inbox: Path) -> list[Entry]:
    if not inbox.is_dir():
        return []
    return [scan_entry(p) for p in sorted(inbox.iterdir()) if p.is_dir() and not p.name.startswith(("_", "."))]


if __name__ == "__main__":
    # 재료 충분성 자체 점검
    assert thin_topics("챗GPT 활용\n엑셀 정리\n대시보드 만들기")
    assert thin_topics("생성형 AI 기초와 프롬프트 작성법을 배우고 엑셀로 데이터를 정리하는 방법을 익혔습니다. 마지막에 발표를 했습니다.")
    assert not thin_topics(
        "1. 프롬프트 5요소로 공문 초안 쓰기 — 부서에서 실제 쓰는 문서를 가져와 다시 썼다\n"
        "2. 민원 답변 초안 자동 생성 — 자주 오는 민원 유형 6개를 골라 답변 템플릿을 만들었다\n"
        "3. 엑셀로 부서 데이터 정리 — 피벗과 파워쿼리로 월별 민원 집계 자동화"
    )
    print("scan self-check ok")
