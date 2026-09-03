"""테스트 접수 건을 검사하고 패키지를 만든다. 실제 접수함·config 는 건드리지 않는다."""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from prpub.scan import scan_entry
from prpub.build import build_entry

INBOX = ROOT / "test" / "접수함"
OUT = ROOT / "test" / "out"

shutil.rmtree(OUT, ignore_errors=True)
OUT.mkdir(parents=True)

for folder in sorted(p for p in INBOX.iterdir() if p.is_dir()):
    e = scan_entry(folder)
    mark = "OK" if e.ok else "FAIL"
    print(f"[{mark}] {folder.name}")
    print(f"      {e.headline}")
    print(f"      양식 {Path(e.form_file).name} · 사진 {len(e.photos)} · 자료 {len(e.attachments)}")
    for err in e.errors:
        print(f"      X {err}")
    for w in e.warnings:
        print(f"      ! {w}")
    if e.ok:
        out = build_entry(e, OUT)
        print(f"      -> {out.relative_to(ROOT)}")
