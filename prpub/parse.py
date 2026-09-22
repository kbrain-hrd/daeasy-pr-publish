"""양식 파일(docx / hwpx / hwp) → {key: value} 딕셔너리.

양식 구조: 표의 한 행에 항목명(+안내)이 있고, 바로 아래 행이 그 입력칸이다.
짧은 항목은 [A | 여백 | B] 세 칸으로 좌우 2단. 항목명 행과 입력 행은 칸 구조가 같으므로
같은 칸 위치(index)로 짝을 맞춘다.
"""

import re
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from docx import Document

from .schema import BY_LABEL, Field, normalize_label


def _clean_value(raw: str, choices: tuple[str, ...]) -> str:
    v = raw.replace("\r", "")
    if choices:
        # "교육후기 " 나 "→ 교육후기" 처럼 선택지 하나만 남긴 경우 그 선택지로 정규화
        hits = [c for c in choices if c in v]
        if len(hits) == 1 and v.replace(hits[0], "").strip(" /→:·\n") == "":
            return hits[0]
    lines = [ln.rstrip() for ln in v.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines).strip()


def pair_rows(rows: list[list[str]]) -> list[tuple[Field, int, int, bool]]:
    """행별 칸 텍스트 목록 → (Field, 행 index, 칸 index, 라벨 칸 내부 여부).

    항목명 행 바로 아래 행이 입력칸이다. 입력 행이 없는 항목 — 라벨 행이 표의
    마지막이거나 바로 다음도 라벨 행 — 은 라벨 칸 자체를 입력칸으로 본다
    (마지막 값 True). 값은 strip_label_hint 로 라벨·안내문을 걷어내고 읽는다.
    배포 양식이 워드 편집을 거치며 입력 행을 잃는 경우가 실제로 있다.
    """
    out: list[tuple[Field, int, int, bool]] = []
    pending: list[tuple[int, Field, int]] = []  # (칸 i, Field, 라벨 행 r)
    for r, cells in enumerate(rows):
        labels = [(i, BY_LABEL.get(normalize_label(t))) for i, t in enumerate(cells) if t.strip()]
        if labels and all(f is not None for _, f in labels):
            for i, f, lr in pending:  # 입력 행 없이 또 라벨 행 — 앞 항목은 라벨 칸에서 읽는다
                out.append((f, lr, i, True))
            pending = [(i, f, r) for i, f in labels if f is not None]
            continue
        if pending:
            for i, f, lr in pending:
                if i < len(cells):
                    out.append((f, r, i, False))
            pending = []
    for i, f, lr in pending:  # 표가 라벨 행으로 끝남
        out.append((f, lr, i, True))
    return out


def strip_label_hint(cell_text: str, f: Field) -> str:
    """라벨 칸 안에 값이 같이 적힌 경우 — 라벨 줄과 안내문을 걷어내고 값만 남긴다.

    안내문은 칸 안에서 여러 줄로 감겨 있을 수 있어, 줄을 이어붙인 것이
    schema 의 hint 앞부분과 일치하는 동안 안내문으로 보고 걷어낸다.
    """
    lines = cell_text.split("\n")
    body_start = 0
    for j, ln in enumerate(lines):
        t = " ".join(ln.replace("*", "").replace("＊", "").replace("★", "").split())
        if t == f.label:
            body_start = j + 1
            break
    hint_norm = " ".join(f.hint.split())
    consumed = ""
    j = body_start
    while j < len(lines):
        t = " ".join(lines[j].split())
        if not t:
            j += 1
            continue
        cand = (consumed + " " + t).strip()
        if hint_norm and hint_norm.startswith(cand):
            consumed = cand
            j += 1
            continue
        break
    return "\n".join(lines[j:])


def _rows_to_data(rows: list[list[str]]) -> dict[str, str]:
    data: dict[str, str] = {}
    for f, r, i, in_cell in pair_rows(rows):
        raw = rows[r][i]
        if in_cell:
            raw = strip_label_hint(raw, f)
        data[f.key] = _clean_value(raw, f.choices)
    return data


# ── docx ──


def docx_rows(table) -> list[list]:
    """행별 셀 객체 목록 (병합 셀은 한 번만)."""
    result = []
    for row in table.rows:
        seen: set[int] = set()
        cells = []
        for c in row.cells:
            if id(c._tc) in seen:
                continue
            seen.add(id(c._tc))
            cells.append(c)
        result.append(cells)
    return result


class _InCellBox:
    """입력 행이 없는 항목의 쓰기 프록시 — 라벨 칸 끝에 문단을 덧붙여 입력칸 노릇을 한다.

    픽스처 채우기 코드가 cell.paragraphs[0].text = … 로 쓰기 때문에,
    라벨 칸을 그대로 주면 라벨 줄이 지워진다. 새 문단만 노출한다.
    """

    def __init__(self, cell):
        self._cell = cell
        self.paragraphs = [cell.add_paragraph("")]

    def add_paragraph(self, text: str = ""):
        p = self._cell.add_paragraph(text)
        self.paragraphs.append(p)
        return p


def docx_value_cells(doc) -> list[tuple[Field, object]]:
    """(Field, 입력 셀) 목록 — 파싱과 테스트 픽스처 채우기가 공유."""
    out = []
    for table in doc.tables:
        cells_by_row = docx_rows(table)
        texts = [[c.text for c in row] for row in cells_by_row]
        for f, r, i, in_cell in pair_rows(texts):
            cell = cells_by_row[r][i]
            out.append((f, _InCellBox(cell) if in_cell else cell))
    return out


def parse_docx(path: Path) -> dict[str, str]:
    doc = Document(str(path))
    data: dict[str, str] = {}
    for table in doc.tables:
        texts = [[c.text for c in row] for row in docx_rows(table)]
        data.update(_rows_to_data(texts))
    return data


# ── hwpx ──

_NS = {"hp": "http://www.hancom.co.kr/hwpml/2011/paragraph"}


def _t_text(t: ET.Element) -> str:
    """<hp:t>앞<hp:lineBreak/>뒤</hp:t> 처럼 줄바꿈 요소 뒤의 tail 텍스트까지 잇는다."""
    parts = [t.text or ""]
    for child in t:
        if child.tag.endswith("lineBreak"):
            parts.append("\n")
        parts.append(child.tail or "")
    return "".join(parts)


def _cell_text(tc: ET.Element) -> str:
    paras = []
    for p in tc.findall(".//hp:p", _NS):
        paras.append("".join(_t_text(t) for t in p.findall(".//hp:t", _NS)))
    return "\n".join(paras)


def parse_hwpx(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    with zipfile.ZipFile(path) as z:
        names = sorted(n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n))
        for name in names:
            root = ET.fromstring(z.read(name))
            for tbl in root.iter(f"{{{_NS['hp']}}}tbl"):
                texts = [[_cell_text(tc) for tc in tr.findall("hp:tc", _NS)] for tr in tbl.findall("hp:tr", _NS)]
                data.update(_rows_to_data(texts))
    return data


def parse_hwp(path: Path) -> dict[str, str]:
    """구형 .hwp 는 한글 COM 으로 hwpx 로 바꾼 뒤 파싱한다 (한글 설치 필요)."""
    from .template import convert_with_hwp  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / (path.stem + ".hwpx")
        convert_with_hwp(path, "HWPX", tmp)
        return parse_hwpx(tmp)


def parse_form(path: Path) -> dict[str, str]:
    ext = path.suffix.lower()
    if ext == ".docx":
        return parse_docx(path)
    if ext == ".hwpx":
        return parse_hwpx(path)
    if ext == ".hwp":
        return parse_hwp(path)
    raise ValueError(f"지원하지 않는 양식 형식: {path.name}")
