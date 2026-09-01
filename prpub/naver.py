"""네이버 블로그 자동 발행.

네이버는 2020년에 글쓰기 API 를 닫았다. 남은 방법이 브라우저 자동화뿐이라
Playwright 로 스마트에디터를 직접 조작한다.

로그인은 사람이 한 번 하고, 그 세션을 `.naver-profile/` 에 남겨 다음부터 재사용한다.
비밀번호는 코드에도 설정에도 두지 않는다.
"""

import io
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / ".naver-profile"
SESSION = ROOT / ".naver-session.json"  # 로그인 쿠키. 자격증명이므로 저장소에 올리지 않는다.

LOGIN_URL = "https://nid.naver.com/nidlogin.login"
WRITE_URL = "https://blog.naver.com/GoBlogWrite.naver"
HOME_URL = "https://www.naver.com"


def _browser(p, headless: bool):
    """사람이 쓰는 크롬으로 띄운다. 없으면 Playwright 가 받아둔 크로미움으로 떨어진다.

    네이버는 자동화 브라우저를 감지하면 로그인을 막는다. Playwright 가 기본으로 붙이는
    자동화 표식을 떼고, navigator.webdriver 도 지운 채로 띄운다.
    """
    PROFILE.mkdir(exist_ok=True)
    opts = dict(
        user_data_dir=str(PROFILE),
        headless=headless,
        viewport={"width": 1440, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )
    try:
        ctx = p.chromium.launch_persistent_context(channel="chrome", **opts)
    except Exception:
        ctx = p.chromium.launch_persistent_context(**opts)
    ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return ctx


def logged_in(ctx) -> bool:
    """로그인 여부를 별도 탭에서 확인한다.

    사람이 쓰고 있는 탭에서 goto 를 하면 입력 중인 로그인 화면이 날아가므로
    확인용 탭을 따로 열고 바로 닫는다.
    """
    probe = ctx.new_page()
    try:
        probe.goto(HOME_URL, wait_until="domcontentloaded")
        return probe.locator('a[href*="nid.naver.com/nidlogin.logout"]').count() > 0
    except Exception:
        return False
    finally:
        probe.close()


def login(timeout_min: int = 10) -> bool:
    """로그인 창을 띄우고 사람이 끝낼 때까지 기다린다."""
    with sync_playwright() as p:
        ctx = _browser(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        if logged_in(ctx):
            print("이미 로그인되어 있습니다.")
            ctx.close()
            return True

        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        print("열린 창에서 네이버에 로그인한 뒤, 창을 닫아 주세요.")

        # 로그인 여부를 판정하려 들지 않는다. 판정이 빗나가면 세션을 통째로 놓치고,
        # 확인용 탭을 여는 것 자체가 사람이 쓰는 화면을 방해한다.
        # 대신 5초마다 현재 쿠키를 파일에 덮어써 둔다 — 창을 닫는 순간의 상태가 남는다.
        saved = 0
        while True:
            try:
                page.wait_for_timeout(5000)
                if not ctx.pages:
                    break
                ctx.storage_state(path=str(SESSION))
                saved += 1
            except Exception:
                break  # 사람이 창을 닫음

        print(f"창이 닫혔습니다. 세션을 {SESSION.name} 에 저장했습니다. (스냅샷 {saved}회)")
        return SESSION.exists()


def session_context(p, headless: bool = False):
    """저장해 둔 로그인 세션으로 브라우저를 연다. 발행할 때 쓴다."""
    if not SESSION.exists():
        raise RuntimeError(f"{SESSION.name} 이 없습니다. 먼저 `uv run prpub naver-login` 을 실행하세요.")
    browser = p.chromium.launch(
        channel="chrome",
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )
    ctx = browser.new_context(storage_state=str(SESSION), viewport={"width": 1440, "height": 900})
    ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return ctx


def check() -> bool:
    """저장된 세션이 아직 로그인 상태인지 조용히 확인한다."""
    with sync_playwright() as p:
        ctx = session_context(p, headless=True)
        try:
            return logged_in(ctx)
        finally:
            ctx.close()


def parse(md_path: Path) -> dict:
    """naver.md → {제목, 카테고리, 태그[], 대표사진, 본문 블록[]}

    본문 블록은 {"kind": "text"|"image"|"line", "value": …} 로 만든다.
    """
    raw = io.open(md_path, encoding="utf-8").read()
    meta = {}
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    body = raw
    if m:
        for line in m.group(1).split("\n"):
            k, _, v = line.partition(":")
            if v:
                meta[k.strip()] = v.strip()
        body = m.group(2)

    blocks = []
    after_line = False  # 구분선 바로 다음 문단이 소제목이다
    for chunk in body.strip().split("\n"):
        s = chunk.strip()
        if not s:
            # 문단 사이 빈 줄은 기존 글에도 그대로 있다. 연속 빈 줄은 하나로 줄인다.
            if blocks and blocks[-1]["kind"] != "blank":
                blocks.append({"kind": "blank", "value": ""})
            continue
        if s.startswith("─"):
            blocks.append({"kind": "line", "value": ""})
            after_line = True
            continue
        if s == "[대표사진]" or s == "[사진]":
            blocks.append({"kind": "image", "value": s})
        elif s.startswith("#") and " " not in s:
            continue  # 해시태그 줄은 태그로 따로 넣는다
        elif after_line and len(s) <= 40 and not s.startswith("["):
            # 구분선 다음 짧은 한 줄이 소제목이다. 맺음의 [교육 문의 …] 안내는 본문으로 둔다.
            blocks.append({"kind": "heading", "value": s})
        else:
            blocks.append({"kind": "text", "value": s})
        after_line = False

    tags = [t.strip() for t in meta.get("태그", "").split(",") if t.strip()]
    return {
        "제목": meta.get("제목", ""),
        "카테고리": meta.get("카테고리", ""),
        "태그": tags,
        "대표사진": meta.get("대표사진", ""),
        "블록": blocks,
    }


# 스마트에디터 셀렉터 (2026-09 기준). 화면이 바뀌면 여기만 고치면 된다.
SEL = {
    "도움말닫기": ".se-help-panel-close-button",
    "팝업취소": ".se-popup-button-cancel",
    "제목": ".se-documentTitle .se-text-paragraph",
    "본문": ".se-component.se-text .se-text-paragraph",
    "사진": ".se-image-toolbar-button",
    "구분선": ".se-insert-horizontal-line-default-toolbar-button",
    "크기버튼": ".se-font-size-code-toolbar-button",
    "크기옵션": '[class*=font-size] button[data-value="{}"]',
    # 발행 팝업
    "발행열기": "button.publish_btn__m9KHH",
    "카테고리버튼": "button.selectbox_button__jb1Dt",
    "전체공개": "#open_public",
    "태그입력": "#tag-input",
    "발행확정": "button.confirm_btn__WEaBq",
    "태그칩": ".tag__zPnmI",
}

# 기존 글의 서식: 소제목은 30 굵게, 본문은 기본 15
HEADING_SIZE = "fs30"
BODY_SIZE = "fs15"


def _set_size(pg, fr, value: str):
    fr.locator(SEL["크기버튼"]).click()
    pg.wait_for_timeout(400)
    fr.locator(SEL["크기옵션"].format(value)).click()
    pg.wait_for_timeout(400)


def _fill_publish_form(pg, fr, data: dict) -> None:
    """발행 팝업을 열고 카테고리·공개범위·태그를 채운다. 발행 버튼은 누르지 않는다."""
    fr.locator(SEL["발행열기"]).click()
    pg.wait_for_timeout(2500)

    if data["카테고리"]:
        fr.locator(SEL["카테고리버튼"]).click()
        pg.wait_for_timeout(800)
        # 목록에서 이름이 같은 항목을 고른다 (네이버가 공백을 nbsp 로 넣어 두는 곳이 있다)
        want = data["카테고리"].replace(" ", "")
        opt = fr.locator("button, label, li").filter(has_text=data["카테고리"]).last
        try:
            opt.click(timeout=5000)
        except Exception:
            fr.get_by_text(want, exact=False).last.click(timeout=5000)
        pg.wait_for_timeout(800)

    try:
        fr.locator(SEL["전체공개"]).check(timeout=4000)
    except Exception:
        pass

    if data["태그"]:
        tag = fr.locator(SEL["태그입력"])
        chips = fr.locator(SEL["태그칩"])
        for i, t in enumerate(data["태그"], start=1):
            # 태그마다 입력창을 다시 집고, 칩이 실제로 늘었는지 확인하고 넘어간다.
            # 한 번 집어두고 연달아 치면 Enter 가 새어 두 태그가 붙는다.
            for _ in range(3):
                tag.click()
                tag.type(t, delay=30)
                pg.wait_for_timeout(400)
                tag.press("Enter")
                pg.wait_for_timeout(900)
                if chips.count() >= i:
                    break
        made = chips.count()
        if made != len(data["태그"]):
            print(f"태그 {len(data['태그'])}개 중 {made}개만 등록됐습니다.")

    pg.wait_for_timeout(500)


def _photo_paths(slug_dir: Path, data: dict) -> list[Path]:
    """[대표사진] · [사진] 자리에 넣을 파일을 순서대로 만든다."""
    cover = slug_dir / data["대표사진"] if data["대표사진"] else None
    rest = sorted((slug_dir / "images").glob("*")) if (slug_dir / "images").exists() else []
    order = ([cover] if cover and cover.exists() else []) + [f for f in rest if f != cover]
    return order


def write(slug_dir: Path, publish: bool = False, headless: bool = False) -> bool:
    """naver.md 를 스마트에디터에 채운다. publish=False 면 발행 직전에서 멈춘다."""
    data = parse(slug_dir / "naver.md")
    photos = _photo_paths(slug_dir, data)
    photo_i = 0

    with sync_playwright() as p:
        ctx = session_context(p, headless=headless)
        pg = ctx.new_page()
        pg.goto(WRITE_URL, wait_until="domcontentloaded")
        pg.wait_for_timeout(6000)
        fr = pg.frame_locator("#mainFrame")

        # 임시저장 글이 있으면 "이어서 쓰시겠습니까" 팝업이 떠서 모든 클릭을 가로막는다.
        # 취소를 눌러 새 글로 시작한다.
        for key in ("팝업취소", "도움말닫기"):
            try:
                fr.locator(SEL[key]).first.click(timeout=4000)
                pg.wait_for_timeout(800)
            except Exception:
                pass
        pg.wait_for_timeout(1000)

        fr.locator(SEL["제목"]).click()
        pg.keyboard.type(data["제목"], delay=0)
        pg.wait_for_timeout(500)

        fr.locator(SEL["본문"]).last.click()
        pg.wait_for_timeout(500)

        for b in data["블록"]:
            if b["kind"] == "text":
                pg.keyboard.type(b["value"], delay=0)
                if "http" in b["value"]:
                    # URL 을 치면 자동 링크 변환이 끼어들어 다음 Enter 를 삼킨다
                    pg.wait_for_timeout(600)
                    pg.keyboard.press("Escape")
                    pg.wait_for_timeout(200)
                pg.keyboard.press("Enter")
            elif b["kind"] == "blank":
                pg.keyboard.press("Enter")
            elif b["kind"] == "heading":
                # 기존 글과 같이 크기 30 · 굵게 로 쓰고, 다음 줄에서 본문 서식으로 되돌린다
                _set_size(pg, fr, HEADING_SIZE)
                pg.keyboard.press("Control+b")
                pg.keyboard.type(b["value"], delay=0)
                pg.keyboard.press("Control+b")
                pg.keyboard.press("Enter")
                _set_size(pg, fr, BODY_SIZE)
            elif b["kind"] == "line":
                fr.locator(SEL["구분선"]).click()
                pg.wait_for_timeout(700)
            elif b["kind"] == "image":
                if photo_i >= len(photos):
                    continue
                with pg.expect_file_chooser(timeout=15000) as fc:
                    fr.locator(SEL["사진"]).click()
                fc.value.set_files(str(photos[photo_i]))
                photo_i += 1
                pg.wait_for_timeout(3000)
            pg.wait_for_timeout(120)

        print(f"본문 입력 완료. 사진 {photo_i}장, 블록 {len(data['블록'])}개")

        # 에디터가 자체 스크롤이라 full_page 로도 위쪽이 안 잡힌다. 맨 위로 올리고 나눠 찍는다.
        try:
            pg.keyboard.press("Control+Home")
            pg.wait_for_timeout(1200)
            for i in range(1, 4):
                pg.screenshot(path=str(slug_dir / f"naver_미리보기{i}.png"))
                pg.mouse.wheel(0, 780)
                pg.wait_for_timeout(900)
            print("화면을 naver_미리보기1~3.png 에 저장했습니다.")
        except Exception as e:
            print("스크린샷 실패:", str(e)[:80])

        _fill_publish_form(pg, fr, data)
        print(f"발행 설정 완료. 카테고리 '{data['카테고리']}', 태그 {len(data['태그'])}개")
        try:
            pg.screenshot(path=str(slug_dir / "naver_발행설정.png"))
        except Exception:
            pass

        if publish:
            fr.locator(SEL["발행확정"]).click()
            pg.wait_for_timeout(6000)
            print("발행했습니다:", pg.url)
        else:
            print("발행 직전에서 멈춥니다. 창에서 확인하고 직접 발행하세요.")
            try:
                pg.wait_for_timeout(600000)
            except Exception:
                pass
        ctx.close()
        return True
