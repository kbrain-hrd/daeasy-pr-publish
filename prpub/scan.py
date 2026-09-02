"""접수함 폴더를 훑어 Entry 목록을 만들고 검증한다."""

import re
from pathlib import Path

from .parse import parse_form
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
        e.errors.append(f"'{PHOTO_DIR}' 또는 '{ATTACH_DIR}' 폴더에 파일이 하나도 없음")
    if not d.get("highlight", "").strip():
        e.warnings.append("이 과정의 주요 포인트가 비어 있음 — 수치 나열 위주의 글이 됨")


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
