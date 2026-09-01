"""사용법:
  uv run prpub template            양식 파일 생성 (templates/)
  uv run prpub scan [--json]       접수함 검사·검증 결과 출력
  uv run prpub build [폴더명...]   검증 통과분 → out/ 패키지 생성 (폴더명 생략 시 전부)
  uv run prpub done  <폴더명...>   접수함 → 발행완료/ 로 이동
"""

import argparse
import json
import shutil
import sys
import tomllib
from datetime import date
from pathlib import Path

from .build import build_entry
from .scan import scan_entry, scan_inbox
from .schema import Entry

ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    cfg = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))
    for k in ("inbox", "done", "out"):
        cfg[k] = (ROOT / cfg[k]).resolve() if not Path(cfg[k]).is_absolute() else Path(cfg[k])
    return cfg


def _print_entries(entries: list[Entry]) -> None:
    if not entries:
        print("접수함이 비어 있습니다.")
        return
    for e in entries:
        name = Path(e.folder).name
        mark = "✅" if e.ok else "❌"
        print(f"{mark} {name}")
        if e.headline:
            print(f"   {e.headline}  [{e.data.get('category', '')}]")
        print(f"   양식: {Path(e.form_file).name if e.form_file else '-'} · 사진 {len(e.photos)} · 자료 {len(e.attachments)}")
        for err in e.errors:
            print(f"   ✗ {err}")
        for w in e.warnings:
            print(f"   ⚠ {w}")


def cmd_template(_: argparse.Namespace) -> None:
    from .template import build_docx, convert_with_hwp  # noqa: PLC0415

    tdir = ROOT / "templates"
    docx = build_docx(tdir / "홍보자료_양식.docx")
    print(f"생성: {docx}")
    try:
        out = convert_with_hwp(docx, "HWP", tdir / "홍보자료_양식.hwp")
        print(f"생성: {out}")
    except Exception as ex:  # noqa: BLE001
        print(f".hwp 변환 실패 (한글 미설치?): {ex}")


def cmd_scan(args: argparse.Namespace) -> None:
    cfg = load_config()
    entries = scan_inbox(cfg["inbox"])
    if args.json:
        print(json.dumps([e.__dict__ for e in entries], ensure_ascii=False, indent=2))
    else:
        print(f"접수함: {cfg['inbox']}")
        _print_entries(entries)


def cmd_build(args: argparse.Namespace) -> None:
    cfg = load_config()
    folders = [cfg["inbox"] / n for n in args.folders] if args.folders else [
        p for p in sorted(cfg["inbox"].iterdir()) if p.is_dir() and not p.name.startswith(("_", "."))
    ]
    built, skipped = [], []
    for folder in folders:
        e = scan_entry(folder)
        if not e.ok:
            skipped.append((folder.name, e.errors))
            continue
        out = build_entry(e, cfg["out"])
        built.append(out)
        print(f"✅ {folder.name} → {out.relative_to(ROOT)}")
    for name, errs in skipped:
        print(f"❌ {name} 건너뜀: " + "; ".join(errs))
    if not built:
        sys.exit(1)


def cmd_done(args: argparse.Namespace) -> None:
    cfg = load_config()
    dest_root = cfg["done"] / date.today().strftime("%Y-%m")
    dest_root.mkdir(parents=True, exist_ok=True)
    for name in args.folders:
        src = cfg["inbox"] / name
        if not src.is_dir():
            print(f"없음: {name}")
            continue
        shutil.move(str(src), str(dest_root / name))
        print(f"이동: {name} → {dest_root.relative_to(ROOT)}/")


def main() -> None:
    ap = argparse.ArgumentParser(prog="prpub", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("template").set_defaults(fn=cmd_template)
    s = sub.add_parser("scan")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_scan)
    s = sub.add_parser("build")
    s.add_argument("folders", nargs="*")
    s.set_defaults(fn=cmd_build)
    s = sub.add_parser("done")
    s.add_argument("folders", nargs="+")
    s.set_defaults(fn=cmd_done)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
