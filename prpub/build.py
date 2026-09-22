"""검증 통과한 Entry → 발행 패키지 (out/{slug}/brief.md + meta.json + images/ + files/).

brief.md 는 LLM 이 게시글(제목·본문)을 작성할 때 참고하는 등록 내용 정리본이다. 글은 여기서 쓰지 않는다.
"""

import hashlib
import io
import json
import re
import shutil
from datetime import date
from pathlib import Path

from PIL import Image, ImageOps

from .parse import embedded_photos
from .schema import FIELDS, SECTIONS, Entry

MAX_W = 1600

# 게시 위치는 양식에서 받지 않는다. 우리가 정하는 것이라 기본값을 둔다.
# 다른 곳에 올릴 건은 /홍보발행 단계에서 바꾼다.
DEFAULT_SECTION = "cases"


def slugify(e: Entry) -> str:
    d = e.data
    parts = [e.date_from, d["org"], d.get("course", "")]
    return "_".join(re.sub(r"[^\w가-힣]+", "-", p).strip("-") for p in parts if p)


def _resize_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() in {".gif", ".heic"}:
        shutil.copy2(src, dst)
        return
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        if im.width > MAX_W:
            im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGB")
        im.save(dst, quality=88, optimize=True)


def _resize_bytes(data: bytes, dst: Path) -> None:
    """임베드 이미지 바이트를 _resize_copy 와 같은 규칙으로 저장한다."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.suffix.lower() == ".gif":
        dst.write_bytes(data)
        return
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im)
        if im.width > MAX_W:
            im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGB")
        im.save(dst, quality=88, optimize=True)


def _brief_md(e: Entry, images: list[str], files: list[str]) -> str:
    d = e.data
    lines = ["# 홍보자료 등록 내용", ""]
    for key, (title, _) in SECTIONS.items():
        block = []
        started = False
        for f in FIELDS:
            if f.key == key:
                started = True
            elif f.key in SECTIONS:
                started = False
            if started and d.get(f.key, "").strip():
                v = d[f.key].strip()
                block.append(f"- {f.label}: " + (("\n  " + v.replace("\n", "\n  ")) if "\n" in v else v))
        if block:
            lines += ["", f"## {title}", *block]
    if images:
        lines += ["", "## 사진 파일", *[f"- {i}. {img}" for i, img in enumerate(images, 1)]]
    if files:
        lines += ["", "## 첨부 자료", *[f"- {f}" for f in files]]
    return "\n".join(lines) + "\n"


def build_entry(e: Entry, out_root: Path) -> Path:
    d = e.data
    slug = slugify(e)
    out = out_root / slug
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    images = []
    for i, p in enumerate(e.photos, 1):
        src = Path(p)
        dst = out / "images" / f"{i:02d}{src.suffix.lower()}"
        _resize_copy(src, dst)
        images.append(f"images/{dst.name}")

    # 양식 문서에 임베드된 사진 — 사진/ 폴더에 없는 것만 꺼내 뒤에 붙인다.
    # 팀들이 사진을 폴더 대신 문서에 붙여 넣는 경우가 실제로 있다.
    folder_hashes = {hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in e.photos}
    idx = len(images)
    for name, data in embedded_photos(Path(e.form_file)):
        if hashlib.sha256(data).hexdigest() in folder_hashes:
            continue  # 폴더에도 같은 사진을 넣은 경우
        idx += 1
        ext = Path(name).suffix.lower()
        dst = out / "images" / f"{idx:02d}{'.jpg' if ext == '.jpeg' else ext}"
        _resize_bytes(data, dst)
        images.append(f"images/{dst.name}")

    files = []
    for p in e.attachments:
        src = Path(p)
        dst = out / "files" / src.name
        dst.parent.mkdir(exist_ok=True)
        shutil.copy2(src, dst)
        files.append(f"files/{src.name}")

    meta = {
        "slug": slug,
        "section": DEFAULT_SECTION,
        "date": e.date_from or date.today().isoformat(),
        "date_from": e.date_from,
        **d,
        "images": images,
        "files": files,
        "source_folder": e.folder,
        "warnings": e.warnings,
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "brief.md").write_text(_brief_md(e, images, files), encoding="utf-8")
    return out
