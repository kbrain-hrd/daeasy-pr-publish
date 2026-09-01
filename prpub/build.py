"""검증 통과한 Entry → 발행 패키지 (out/{slug}/brief.md + meta.json + images/ + files/).

brief.md 는 LLM 이 게시글(제목·본문)을 작성할 때 참고하는 등록 내용 정리본이다. 글은 여기서 쓰지 않는다.
"""

import json
import re
import shutil
from datetime import date
from pathlib import Path

from PIL import Image, ImageOps

from .schema import FIELDS, SECTIONS, Entry

MAX_W = 1600
_CAT_SLUG = {
    "교육후기": "cases",
    "인사이트": "insights",
    "뉴스·보도자료": "news",
    "교육 산출물": "outputs",
    "기타": "etc",
}


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


def _brief_md(e: Entry, images: list[str], files: list[str]) -> str:
    d = e.data
    lines = ["# 홍보자료 등록 내용", ""]
    lines.append(f"- 게시 위치: {d['category']}")
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

    files = []
    for p in e.attachments:
        src = Path(p)
        dst = out / "files" / src.name
        dst.parent.mkdir(exist_ok=True)
        shutil.copy2(src, dst)
        files.append(f"files/{src.name}")

    meta = {
        "slug": slug,
        "section": _CAT_SLUG.get(d["category"], "etc"),
        "date": d.get("publish_at") or e.date_from or date.today().isoformat(),
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
