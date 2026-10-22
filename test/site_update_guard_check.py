"""`prpub site` 기존 글 덮어쓰기 제한 점검 — 브라우저·네트워크는 전부 대역, 실제 사이트에 요청하지 않는다.

실행 (pr-publish 루트에서): uv run python test/site_update_guard_check.py
"""

import contextlib
import shutil
import json
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from prpub import site  # noqa: E402


class Resp:
    def __init__(self, status, body=None):
        self.status = status
        self.ok = 200 <= status < 300
        self._body = body or {}

    def json(self):
        return self._body

    def text(self):
        return json.dumps(self._body, ensure_ascii=False)


class Page:
    def __init__(self, ctx):
        self.ctx = ctx

    def goto(self, url, wait_until=None):
        self.ctx.calls.append(("goto", url))

    def evaluate(self, script, slug):
        return self.ctx.row

    def close(self):
        pass


class Request:
    def __init__(self, ctx):
        self.ctx = ctx

    def post(self, url, multipart=None, data=None):
        self.ctx.calls.append(("POST", url, data))
        if url == site.UPLOAD_API:
            return Resp(200, {"url": f"https://cdn.test/{multipart['file']['name']}"})
        return Resp(self.ctx.create_status, {"id": "new-id"})

    def fetch(self, url, method=None, data=None):
        self.ctx.calls.append((method, url, data))
        return Resp(200)


class Ctx:
    def __init__(self, create_status, row):
        self.create_status = create_status
        self.row = row
        self.calls: list = []
        self.request = Request(self)

    def new_page(self):
        return Page(self)

    def close(self):
        pass

    def patched(self) -> list:
        return [c for c in self.calls if c[0] == "PATCH"]


def run(create_status, row, live=False, update=False):
    """publish() 를 대역 브라우저로 돌린다. (ctx, SystemExit 메시지 또는 None)"""
    ctx = Ctx(create_status, row)
    tmp = Path(tempfile.mkdtemp(prefix="prpub_site_guard_"))
    d = tmp / "out" / "2026-10-22_테스트기관_과정"
    (d / "images").mkdir(parents=True)
    (d / "images" / "01.jpg").write_bytes(b"jpg")
    (d / "post.md").write_text("# 테스트 제목\n\n본문입니다.\n\n![대표](images/01.jpg)\n", encoding="utf-8")
    (d / "meta.json").write_text(json.dumps({"site_slug": "test-org-2026", "org": "테스트기관"}), encoding="utf-8")
    session = tmp / ".daeasy-session.json"
    session.write_text("{}", encoding="utf-8")
    saved = (site.SESSION, site.sync_playwright, site._browser)
    site.SESSION = session
    site.sync_playwright = lambda: contextlib.nullcontext(object())
    site._browser = lambda p, headless: ctx
    try:
        with contextlib.redirect_stdout(open(tmp / "stdout.txt", "w", encoding="utf-8")):
            site.publish(d, live=live, update=update)
        return ctx, None
    except SystemExit as ex:
        return ctx, str(ex)
    finally:
        site.SESSION, site.sync_playwright, site._browser = saved
        shutil.rmtree(tmp, ignore_errors=True)


DRAFT = {"id": "case-1", "status": "임시저장"}
PUBLISHED = {"id": "case-1", "status": "공개"}

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


@test
def g1_new_registration_unchanged():
    for live in (False, True):
        ctx, err = run(201, None, live=live)
        assert err is None, err
        assert ctx.patched() == [], "신규 등록은 갱신하지 않는다"
        posted = [c for c in ctx.calls if c[0] == "POST" and c[1] == site.CASES_API]
        assert posted[0][2]["status"] == ("published" if live else "draft")


@test
def g2_draft_overwrite_and_draft_to_live_unchanged():
    for live in (False, True):
        ctx, err = run(409, DRAFT, live=live)
        assert err is None, err
        patched = ctx.patched()
        assert len(patched) == 1 and patched[0][2]["status"] == ("published" if live else "draft"), patched


@test
def g3_published_without_live_refused():
    for update in (False, True):
        ctx, err = run(409, PUBLISHED, live=False, update=update)
        assert err and "임시저장으로 내려갑니다" in err, err
        assert ctx.patched() == []


@test
def g4_published_live_without_update_refused():
    ctx, err = run(409, PUBLISHED, live=True)
    assert err and "--update" in err, err
    assert ctx.patched() == []


@test
def g5_published_live_update_allowed():
    ctx, err = run(409, PUBLISHED, live=True, update=True)
    assert err is None, err
    patched = ctx.patched()
    assert len(patched) == 1 and patched[0][2]["status"] == "published"


@test
def g6_unknown_status_refused():
    for row in ({"id": "case-1", "status": None}, {"id": "case-1", "status": "보관"}, {"id": "case-1"}):
        for live, update in ((False, False), (True, False), (True, True)):
            ctx, err = run(409, row, live=live, update=update)
            assert err and "확인하지 못했습니다" in err, (row, live, update, err)
            assert ctx.patched() == []
    ctx, err = run(409, None, live=True, update=True)  # 행 자체를 못 찾음 — 기존 동작대로 거부
    assert err and "id 를 찾지 못해" in err and ctx.patched() == []


@test
def g7_refusal_not_misread_by_promo():
    # promo 는 출력에 '같은 slug'+'이미 있습니다' → already_exists, '로그인'+'만료' → skipped 로 읽는다.
    # 거부는 그 어느 쪽으로도 읽히면 안 된다 (실패로 남아야 한다).
    for row, live in ((PUBLISHED, False), (PUBLISHED, True), ({"id": "c", "status": None}, True)):
        _, err = run(409, row, live=live)
        assert not ("같은 slug" in err and "이미 있습니다" in err) and not ("로그인" in err and "만료" in err), err


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"OK    {fn.__name__}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n결과: {len(TESTS) - failed}/{len(TESTS)} 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
