"""네이버 블로그 자동 발행.

네이버는 2020년에 글쓰기 API 를 닫았다. 남은 방법이 브라우저 자동화뿐이라
Playwright 로 스마트에디터를 직접 조작한다.

로그인은 사람이 한 번 하고, 그 세션을 `.naver-profile/` 에 남겨 다음부터 재사용한다.
비밀번호는 코드에도 설정에도 두지 않는다.
"""

import html
import io
import json
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
    """로그인할 때 쓴 브라우저 프로필을 그대로 다시 연다.

    전에는 쿠키 파일(.naver-session.json)만 새로 띄운 브라우저에 주입했다. 그러면
    네이버가 그 세션을 인정하지 않아 발행할 때마다 로그인 화면으로 되돌아갔다.
    login() 이 쓰는 프로필(.naver-profile/)을 그대로 열면 쿠키와 로컬스토리지가
    로그인 직후 상태 그대로 남아 있다.
    """
    if not PROFILE.exists():
        raise RuntimeError(
            f"{PROFILE.name} 폴더가 없습니다. 먼저 `uv run prpub naver-login` 을 실행하세요."
        )
    return _browser(p, headless)


def check() -> bool:
    """저장된 세션이 아직 로그인 상태인지 조용히 확인한다."""
    with sync_playwright() as p:
        ctx = session_context(p, headless=True)
        try:
            return logged_in(ctx)
        finally:
            ctx.close()


# `::수치 A|B|C::` 요약 박스, `::인용 말|누가::` 인용구.
# site.py 의 _STATS·_QUOTE 와 같은 규칙이어야 사이트와 네이버 결과가 어긋나지 않는다.
_STATS = re.compile(r"^::수치\s*(.+?)\s*::$")
_QUOTE = re.compile(r"^::인용\s*(.+?)\s*::$")
# 주소만 있는 줄이라야 링크 카드가 된다. 문장 안에 섞인 주소는 글자 링크로 둔다 —
# 교육 문의 안내문이 카드로 변해 맺음에 카드가 하나 더 붙던 것을 막는다.
_URL_ONLY = re.compile(r"^https?://\S+$")


def parse(md_path: Path) -> dict:
    """naver.md → {제목, 카테고리, 태그[], 대표사진, 본문 블록[]}

    본문 블록은 {"kind": "text"|"heading"|"stats"|"image"|"line"|"blank", "value": …} 로 만든다.
    stats 의 value 는 항목 문자열 목록이다.
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
        if s.startswith("## "):
            # 마크다운 소제목. 전에는 이 줄을 알아보지 못해 본문에 '## ' 가 글자
            # 그대로 들어갔다. 구분선 다음 줄만 소제목으로 보던 규칙에 이걸 더한다.
            blocks.append({"kind": "heading", "value": s[3:].strip()})
            after_line = False
            continue
        m = _QUOTE.match(s)
        if m:
            # `::인용 말|누가::`. site.py 와 같이 첫 조각이 말, 둘째가 말한 사람이다.
            parts = [x.strip() for x in m.group(1).split("|")]
            blocks.append({"kind": "quote",
                           "value": (parts[0], parts[1] if len(parts) > 1 else "")})
            after_line = False
            continue
        m = _STATS.match(s)
        if m:
            # `::수치 A|B|C::` 요약 박스. site.py 와 같은 규칙으로 쪼갠다.
            # 전에는 이 줄을 몰라 `::수치 …::` 가 글자 그대로 들어갔다.
            items = [x.strip() for x in m.group(1).split("|") if x.strip()]
            blocks.append({"kind": "stats", "value": items})
            after_line = False
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
    # 글꼴. 크기 버튼과 같은 자리에 있고 이름만 다르다. 화면에서 직접 확인한 값이다.
    # 옵션은 클래스에 글꼴 이름이 박혀 있어(se-toolbar-option-font-family-system-button)
    # 공통 클래스로는 잡히지 않는다. data-value 로 집는다.
    "글꼴버튼": ".se-font-family-toolbar-button",
    "글꼴옵션": 'button[class*="font-family"][data-value="{}"]',
    # 굵게 토글. Ctrl+B 는 이 에디터에서 먹지 않아 버튼을 눌러야 한다.
    "굵게": "button[class*='bold-toolbar-button']",
    # 글머리 목록. 버튼을 누르면 기호·숫자·해제 세 항목이 뜬다.
    # 기호목록을 고르면 사이트의 <ul><li> 와 같은 구조가 된다.
    "목록버튼": "button[class*='list-bullet-toolbar-button']",
    "목록옵션": "button[class*='toolbar-option-list'][data-value='{}']",
    # URL 만 있는 줄이 바뀌는 링크 카드. 변환이 끝났는지 개수로 확인한다.
    "링크카드": ".se-component.se-oglink",
    # 인용구. 본문과 출처 칸이 따로 있다 (se-quote / se-cite).
    "인용구추가": "button[class*='insert-quotation-default-toolbar-button']",
    "인용구": ".se-component.se-quotation",
    "인용구출처": ".se-component.se-quotation .se-cite",
    # 사진 아래 '사진 설명을 입력하세요.' 칸. 사이트의 <figcaption> 자리다 (측정으로 확인).
    "사진컴포넌트": ".se-component.se-image",
    "사진본체": ".se-component.se-image .se-image-resource",
    "사진캡션": ".se-component.se-image .se-caption .se-text-paragraph",
    # 발행 팝업.
    # 네이버가 CSS 모듈 해시 클래스(publish_btn__m9KHH 처럼)를 쓰는데 화면을 재배포하면
    # 뒤쪽 해시가 바뀐다. 실제로 이것 때문에 버튼을 30초 기다리다 실패했다.
    # 해시 앞부분만 부분 일치로 찾으면 재배포에 흔들리지 않는다.
    "발행열기": "button[class*='publish_btn']",
    "카테고리버튼": "button[class*='selectbox_button']",
    "전체공개": "#open_public",
    "태그입력": "#tag-input",
    "발행확정": "button[class*='confirm_btn']",
    # 태그 칩은 감싸는 요소까지 잡히면 개수가 부풀려져 "등록됐다"고 잘못 판정한다.
    # 칩으로 쓰일 만한 태그로 좁혔다. 등록 여부의 실제 근거는 입력창이 비워졌는지
    # 보는 쪽이고, 이 개수는 마지막 집계 보고에 쓴다.
    "태그칩": "span[class*='tag__'], li[class*='tag__']",
}

# 기존 글의 서식: 소제목은 30 굵게, 본문은 기본 15
HEADING_SIZE = "fs30"
BODY_SIZE = "fs15"

# 글꼴은 기본서체로 고정한다. 블로그마다 기본값이 달라(이 계정은 나눔고딕) 글이
# 제각각으로 보였다. "system" 은 서체 목록의 기본서체 항목이 쓰는 값이다.
BODY_FONT = "system"

# UI 상태를 기다리는 기본 한계(ms). 네트워크·렌더링이 느릴 때를 고려한 값이다.
UI_TIMEOUT_MS = 15000

# 에디터가 프레임 안에서 만들어지기를 기다리는 한계(ms). 첫 진입이라 더 넉넉히 둔다.
EDITOR_TIMEOUT_MS = 45000


def _wait_count(pg, locator, want: int, timeout_ms: int = 5000, step_ms: int = 150) -> bool:
    """locator 개수가 want 이상이 될 때까지 기다린다. 되면 True.

    태그 칩이나 본문 이미지처럼 "몇 개가 됐는지"로 완료를 알 수 있는 곳에 쓴다.
    정해진 시간을 세는 것보다 실제 결과를 확인하는 편이 확실하다.
    """
    waited = 0
    while waited < timeout_ms:
        if locator.count() >= want:
            return True
        pg.wait_for_timeout(step_ms)
        waited += step_ms
    return locator.count() >= want


def _wait_text(pg, locator, want: str, timeout_ms: int = 5000, step_ms: int = 150) -> bool:
    """locator 안에 want 가 나타날 때까지 기다린다. 되면 True.

    넣은 내용이 실제로 에디터에 들어갔는지 확인할 때 쓴다. 넣는 방식이 바뀌었으니
    들어갔는지도 같이 봐야 한다.
    """
    waited = 0
    while waited < timeout_ms:
        try:
            if want and want in (locator.inner_text() or ""):
                return True
        except Exception:
            pass
        pg.wait_for_timeout(step_ms)
        waited += step_ms
    return False


def _wait_value(pg, locator, want: str, timeout_ms: int = 3000, step_ms: int = 100) -> bool:
    """입력창의 값이 want 가 될 때까지 기다린다. 되면 True.

    친 글자가 입력창에 다 반영됐는지 확인할 때 쓴다.
    """
    waited = 0
    while waited < timeout_ms:
        try:
            if locator.input_value() == want:
                return True
        except Exception:
            return False
        pg.wait_for_timeout(step_ms)
        waited += step_ms
    return False


def _set_size(pg, fr, value: str):
    """글자 크기를 바꾼다.

    메뉴가 뜨는 데 걸리는 시간이 매번 달라, 400ms 고정 대기로는 느릴 때 클릭을 놓쳤다.
    항목이 실제로 보일 때까지 기다린 뒤 누른다.
    """
    fr.locator(SEL["크기버튼"]).click()
    opt = fr.locator(SEL["크기옵션"].format(value))
    opt.wait_for(state="visible", timeout=5000)
    opt.click()
    try:
        opt.wait_for(state="hidden", timeout=3000)
    except Exception:
        pg.wait_for_timeout(400)  # 메뉴가 남아 있으면 종전처럼 잠깐 기다린다


def _set_font_default(pg, fr) -> None:
    """글꼴을 기본서체로 맞춘다.

    블로그마다 기본 글꼴 설정이 달라 같은 원고가 제각각으로 보인다(이 계정은 나눔고딕).
    서체 목록에서 기본서체 항목은 data-value="system" 이다 — 글자로 찾으면 '기본서체'
    라는 말이 목록 전체 텍스트에도 걸려 엉뚱한 요소를 누른다. 크기 옵션과 같이
    값으로 집는다. 실패해도 글쓰기는 계속한다. 글꼴은 발행을 막을 일이 아니다.
    """
    try:
        fr.locator(SEL["글꼴버튼"]).first.click()
        opt = fr.locator(SEL["글꼴옵션"].format(BODY_FONT)).first
        opt.wait_for(state="visible", timeout=5000)
        opt.click()
        try:
            opt.wait_for(state="hidden", timeout=3000)
        except Exception:
            pg.wait_for_timeout(400)
    except Exception:
        print("글꼴을 기본서체로 바꾸지 못했습니다. 에디터에서 직접 확인하세요.")


def _toggle_bold(pg, fr) -> None:
    """굵게를 켜거나 끈다.

    Ctrl+B 는 이 에디터에서 반응하지 않는다(측정으로 확인). 도구막대 버튼을 눌러야
    커서 위치의 굵게 상태가 바뀌고, 그다음에 넣는 글자가 `<b>` 로 감싸진다.
    """
    fr.locator(SEL["굵게"]).first.click()
    pg.wait_for_timeout(250)


def _insert_rich(pg, fr, text: str) -> None:
    """문단 하나를 넣는다. `**굵게**` 구간만 굵게 처리한다.

    전에는 문단을 통째로 넣어 별표가 글자 그대로 들어갔다. 사이트 쪽은 site.py 가
    `**` 를 굵게 태그로 바꾸는데 네이버에만 그 처리가 없었다.
    """
    parts = re.split(r"\*\*(.+?)\*\*", text)
    for i, seg in enumerate(parts):
        if not seg:
            continue
        if i % 2 == 1:          # 홀수 조각이 별표 안쪽이다
            _toggle_bold(pg, fr)
            pg.keyboard.insert_text(seg)
            _toggle_bold(pg, fr)
        else:
            pg.keyboard.insert_text(seg)


def _set_list(pg, fr, value: str) -> None:
    """글머리 목록을 켜거나(bullet) 끈다(reset)."""
    fr.locator(SEL["목록버튼"]).first.click()
    opt = fr.locator(SEL["목록옵션"].format(value))
    opt.wait_for(state="visible", timeout=5000)
    opt.click()
    pg.wait_for_timeout(300)


def _insert_stats(pg, fr, items: list[str]) -> None:
    """`::수치 A|B|C::` 를 글머리 목록으로 넣는다.

    사이트(site.py)는 이 문법을 `<ul><li>…</li></ul>` 로 바꾼다. 네이버에도 같은
    구조를 만들어 의미를 맞춘다 — 기호목록을 고르면 에디터가 ul/li 를 만든다.
    전에는 이 처리가 없어 `::수치 …::` 가 글자 그대로 본문에 들어갔다.

    항목 안의 `**굵게**` 도 사이트와 같이 살린다 (site.py 가 _inline 을 거치는 것과 같다).
    """
    _set_list(pg, fr, "bullet")
    for i, item in enumerate(items):
        _insert_rich(pg, fr, item)
        if i < len(items) - 1:
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(200)
    # 목록을 끊고 다음 문단으로 나간다. 켠 채로 두면 뒤 문단까지 목록이 된다.
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(200)
    _set_list(pg, fr, "reset")


def _insert_quote(pg, fr, said: str, who: str) -> None:
    """`::인용 말|누가::` 를 에디터의 인용구 컴포넌트로 넣는다.

    사이트(site.py)는 이 문법을 `<blockquote><p>말</p><p><em>누가</em></p></blockquote>` 로
    바꾼다. 네이버 인용구도 본문(se-quote)과 출처(se-cite) 두 칸이라 구조가 같다.
    전에는 이 처리가 없어 `::인용 …::` 가 글자 그대로 들어갔다.

    출처 칸은 Tab 으로 넘어가지지 않아 직접 눌러야 하고, 인용구 안에서는 Enter 로
    빠져나올 수 없어 아래 빈 곳을 눌러 새 문단으로 나온다 (측정으로 확인).
    """
    fr.locator(SEL["인용구추가"]).first.click()
    pg.wait_for_timeout(1200)
    _insert_rich(pg, fr, said)
    pg.wait_for_timeout(300)

    if who:
        try:
            fr.locator(SEL["인용구출처"]).last.click(timeout=4000)
            pg.wait_for_timeout(300)
            pg.keyboard.insert_text(who)
            pg.wait_for_timeout(300)
        except Exception:
            print("인용구 출처 칸을 채우지 못했습니다.")

    # 인용구 밖으로 — 컴포넌트 아래를 눌러 새 문단을 만든다
    try:
        box = fr.locator(SEL["인용구"]).last.bounding_box()
        if box:
            pg.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] + 60)
            pg.wait_for_timeout(600)
    except Exception:
        print("인용구 뒤로 빠져나오지 못했습니다. 이후 문단이 인용구 안에 들어갈 수 있습니다.")


def _set_caption(pg, fr, caption: str) -> None:
    """방금 넣은 사진에 사진 설명을 단다.

    사이트(site.py)는 `![설명](…)` 의 설명을 `<figcaption>` 으로 보여준다. 네이버
    사진에도 '사진 설명을 입력하세요.' 칸이 붙어 있어 같은 자리에 같은 글을 넣는다.
    전에는 이 처리가 없어 네이버 글만 사진 설명이 통째로 빠졌다.

    캡션 칸은 사진을 넣은 직후에는 `display:none` 이라 눌리지 않는다. 사진을 한 번
    눌러 고르면 그때 나타난다 (측정: 사진 직후 h=0 → 사진 클릭 후 h=23). 인용구와
    같이 컴포넌트 아래를 눌러 본문으로 되돌아온다.
    """
    # 한 번 눌러도 안 열릴 때가 있다 — 실측에서 두 번째 사진만 번번이 실패했다.
    # 열렸는지 보고 안 열렸으면 다시 누른다. 정해진 시간을 세는 대신 상태를 본다.
    cap = fr.locator(SEL["사진캡션"]).last
    opened = False
    for _ in range(3):
        try:
            fr.locator(SEL["사진본체"]).last.click(timeout=5000)
            cap.wait_for(state="visible", timeout=4000)
            opened = True
            break
        except Exception:
            pg.wait_for_timeout(600)
    if not opened:
        print(f"사진 설명 칸이 열리지 않았습니다: {caption[:40]}")
        return

    try:
        cap.click(timeout=5000)
        pg.wait_for_timeout(300)
        pg.keyboard.insert_text(caption)
        pg.wait_for_timeout(300)
    except Exception:
        print(f"사진 설명을 넣지 못했습니다: {caption[:40]}")
        return

    # 사진 밖으로 — 사진 **다음 문단**을 직접 눌러 커서를 제자리에 돌려놓는다.
    #
    # 컴포넌트 아래 60px 을 누르던 방식은 그 자리가 늘 빈 곳이 아니어서(다음 사진이나
    # 구분선이 바로 붙어 있으면 그것을 누른다) 커서가 캡션에 남곤 했다. 그러면 뒤이어
    # 글머리 목록을 켜려 할 때 글자 도구막대 자체가 없어 목록 버튼을 못 찾고, 목록이
    # 엉뚱한 자리에 들어가거나 발행이 통째로 멈췄다. 자리를 좌표로 어림하지 않고
    # 사진 다음 문단이라는 실제 요소를 집는다.
    try:
        nxt = fr.locator(SEL["사진컴포넌트"]).last.locator(
            "xpath=following-sibling::*[contains(@class,'se-component')][1]"
            "//p[contains(@class,'se-text-paragraph')]")
        nxt.first.click(timeout=4000)
        pg.wait_for_timeout(400)
        return
    except Exception:
        pass

    # 다음 문단이 아직 없으면(사진이 글 맨 끝인 경우) 종전대로 아래 빈 곳을 누른다
    try:
        box = fr.locator(SEL["사진컴포넌트"]).last.bounding_box()
        if box:
            pg.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] + 60)
            pg.wait_for_timeout(600)
    except Exception:
        print("사진 뒤로 빠져나오지 못했습니다. 이후 문단이 사진 설명에 들어갈 수 있습니다.")


def _tag_registered(fr, t: str) -> bool:
    """이 태그가 이미 칩으로 붙어 있는가. 칩 글자는 `#태그` 형태로 나온다."""
    try:
        return any(c.strip().lstrip("#") == t for c in fr.locator(SEL["태그칩"]).all_inner_texts())
    except Exception:
        return False


def _open_publish_popup(fr) -> None:
    """발행 설정 팝업을 연다.

    네이버는 CSS 모듈이 만든 해시 클래스(publish_btn__…)를 쓰는데, 화면을 재배포할
    때마다 해시가 바뀐다. 실제로 클래스가 어긋나 버튼을 30초 기다리다 실패했다.
    클래스로 먼저 찾고 없으면 버튼 글자로 찾는다. 글자는 개편에 덜 흔들린다.
    """
    by_class = fr.locator(SEL["발행열기"])
    if by_class.count():
        by_class.first.click()
        return
    fr.get_by_role("button", name="발행", exact=True).first.click()


def _fill_publish_form(pg, fr, data: dict) -> None:
    """발행 팝업을 열고 카테고리·공개범위·태그를 채운다. 발행 버튼은 누르지 않는다."""
    _open_publish_popup(fr)
    # 팝업이 그려지는 시간이 매번 다르다. 2.5초를 세는 대신 태그 입력창이 보일 때까지
    # 기다린다. 팝업이 덜 뜬 상태에서 카테고리를 누르던 것을 막는다.
    fr.locator(SEL["태그입력"]).wait_for(state="visible", timeout=UI_TIMEOUT_MS)

    if data["카테고리"]:
        # 부분 일치라 여러 개가 잡힐 수 있어 첫 번째를 집는다
        fr.locator(SEL["카테고리버튼"]).first.click()
        # 목록에서 이름이 같은 항목을 고른다. 네이버가 공백을 nbsp 로 넣어 두는 곳이
        # 있어 공백을 느슨하게 보는 정규식으로 찾는다. 전에는 공백을 지운 문자열로
        # 찾았는데, 화면에는 공백이 그대로 있어 영영 못 찾았다.
        # 찾는 범위는 종전대로 button·label·li 로 한정한다. 화면 전체에서 글자로
        # 찾으면 설명문 같은 엉뚱한 요소를 누를 수 있다.
        pattern = re.compile(r"\s*".join(re.escape(w) for w in data["카테고리"].split()))
        opt = fr.locator("button, label, li").filter(has_text=pattern).last
        try:
            # 목록이 펼쳐진 뒤에 누른다. 800ms 고정으로는 느릴 때 빈 곳을 눌렀다.
            opt.wait_for(state="visible", timeout=5000)
            opt.click()
            try:
                opt.wait_for(state="hidden", timeout=3000)   # 목록이 닫힌 것을 확인
            except Exception:
                pg.wait_for_timeout(800)
        except Exception:
            # 이 블로그에 없는 카테고리일 수 있다(테스트 블로그 등). 글을 통째로
            # 버리는 것보다 카테고리 하나를 놓치는 편이 낫다. 알리고 계속한다.
            print(f"카테고리 '{data['카테고리']}' 를 목록에서 찾지 못했습니다. 기본값으로 둡니다.")
            # Escape 는 펼친 목록이 아니라 발행 팝업 자체를 닫는다. 실제로 그 바람에
            # 뒤이어 태그 입력창을 30초 기다리다 실패했다. 카테고리 버튼을 한 번 더
            # 눌러 목록만 접는다.
            try:
                fr.locator(SEL["카테고리버튼"]).first.click(timeout=4000)
            except Exception:
                pass
            pg.wait_for_timeout(500)

    # 위 과정에서 팝업이 닫혔을 수 있다. 태그·공개범위를 건드리기 전에 확인하고 되살린다.
    try:
        fr.locator(SEL["태그입력"]).wait_for(state="visible", timeout=3000)
    except Exception:
        print("발행 팝업이 닫혀 다시 엽니다.")
        _open_publish_popup(fr)
        fr.locator(SEL["태그입력"]).wait_for(state="visible", timeout=UI_TIMEOUT_MS)

    try:
        fr.locator(SEL["전체공개"]).check(timeout=4000)
    except Exception:
        pass

    if data["태그"]:
        tag = fr.locator(SEL["태그입력"])
        chips = fr.locator(SEL["태그칩"])
        # 같은 태그를 두 번 넣으면 네이버가 "이미 등록된 태그입니다" 를 띄우고
        # 그 자리에서 멈춘다. 순서를 지키며 중복만 걸러낸다.
        seen: set[str] = set()
        wanted = [t for t in data["태그"] if not (t in seen or seen.add(t))]
        if len(wanted) != len(data["태그"]):
            print(f"태그 {len(data['태그']) - len(wanted)}개가 중복이라 건너뜁니다.")
        for i, t in enumerate(wanted, start=1):
            # 태그마다 입력창을 다시 집고, 칩이 실제로 늘었는지 확인하고 넘어간다.
            # 한 번 집어두고 연달아 치면 Enter 가 새어 두 태그가 붙는다.
            for _ in range(3):
                # 등록이 늦게 잡히면 아래 확인이 시간 초과되고 재시도가 같은 태그를
                # 또 넣는다. 실제로 마지막 태그가 두 번 들어가 네이버가
                # "이미 등록된 태그입니다" 를 띄우고 멈췄다. 칩에 이미 있으면 끝낸다.
                if _tag_registered(fr, t):
                    break
                tag.click()
                # 재시도로 들어왔을 때 앞 태그가 입력창에 남아 있으면, 커서 위치에
                # 덧쓰면서 "케이브레인컴공공기관AI퍼니" 처럼 두 태그가 섞인 것이
                # 등록됐다. 매번 비우고 시작한다.
                tag.fill("")
                tag.type(t, delay=30)
                # 400ms 를 세던 자리다. 여기서 기다리는 것은 친 글자가 입력창에
                # 반영되는 일이라, 값이 실제로 들어왔는지 보고 누른다. 덜 들어간
                # 상태에서 Enter 를 눌러 태그가 잘리던 것을 막는다.
                if not _wait_value(pg, tag, t, timeout_ms=2000):
                    pg.wait_for_timeout(400)
                tag.press("Enter")
                # 900ms 를 세는 대신 태그가 실제로 등록됐는지 확인한다.
                # 칩 개수가 늘거나, 등록되면서 입력창이 비워지거나 둘 중 하나면 된다.
                # 칩 클래스는 네이버 재배포 때마다 바뀌어 그것만 믿으면 같은 태그를
                # 세 번 넣게 된다.
                if _wait_count(pg, chips, i, timeout_ms=4000):
                    break
                try:
                    if tag.input_value() == "":
                        break
                except Exception:
                    pass
        made = chips.count()
        if made != len(data["태그"]):
            print(f"태그 {len(data['태그'])}개 중 {made}개만 등록됐습니다.")

    pg.wait_for_timeout(500)


# post.md 의 `![설명](images/01.jpg)` 줄. 사이트가 읽는 것과 같은 규칙이다.
_MD_IMG = re.compile(r"!\[(.*?)\]\((.+?)\)")


def _photo_plan(slug_dir: Path, data: dict) -> list[tuple[Path, str]]:
    """[대표사진] · [사진] 자리에 넣을 (파일, 사진 설명) 을 차례대로 만든다.

    차례와 설명을 **post.md 에서** 가져온다. 사이트가 쓰는 원고가 post.md 라,
    여기서 파일 이름 순으로 정렬하면 두 채널의 사진 차례가 어긋난다 — 실제로
    사이트는 01·03·02 순인데 네이버만 01·02·03 으로 나갔다. 사이트가
    `<figcaption>` 으로 보여주는 사진 설명도 같은 줄에 있다.
    """
    post = slug_dir / "post.md"
    plan: list[tuple[Path, str]] = []
    if post.exists():
        for cap, rel in _MD_IMG.findall(post.read_text(encoding="utf-8")):
            f = slug_dir / rel
            if f.exists():
                # site.py 와 같이 엔티티를 먼저 푼다 (`&#39;` 가 글자로 남지 않게)
                plan.append((f, html.unescape(cap).strip()))
    if plan:
        return plan

    # post.md 가 없는 옛 원고는 종전대로 파일 이름 순, 설명 없이
    cover = slug_dir / data["대표사진"] if data["대표사진"] else None
    rest = sorted((slug_dir / "images").glob("*")) if (slug_dir / "images").exists() else []
    order = ([cover] if cover and cover.exists() else []) + [f for f in rest if f != cover]
    return [(f, "") for f in order]


def _edu_info_items(meta: dict) -> list[str]:
    """제목·대표사진 아래에 고정으로 붙는 교육 개요. site.py 의 _edu_info_block 과 같다.

    사이트는 이것을 `<ul class="edu-info"><li><strong>교육명</strong> …` 로 넣는다.
    네이버에도 같은 네 줄을 같은 차례로 넣어야 두 채널의 글 머리가 맞는다.
    값은 meta.json(양식 파싱 결과)에서 오므로 글마다 형식이 흔들리지 않는다.
    """
    rows = (
        ("교육명", meta.get("course_name", "")),
        ("교육기관", meta.get("org", "")),
        ("교육 일자", meta.get("dates", "")),
        ("교육 대상·인원", meta.get("participants", "")),
    )
    return [f"**{label}** {' '.join(value.split())}"
            for label, value in rows if value.strip()]


def write(slug_dir: Path, publish: bool = False, headless: bool = False) -> bool:
    """naver.md 를 스마트에디터에 채운다. publish=False 면 발행 직전에서 멈춘다."""
    data = parse(slug_dir / "naver.md")
    photos = _photo_plan(slug_dir, data)
    photo_i = 0
    meta_path = slug_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    edu_items = _edu_info_items(meta)
    edu_done = not edu_items

    with sync_playwright() as p:
        ctx = session_context(p, headless=headless)
        pg = ctx.new_page()
        pg.goto(WRITE_URL, wait_until="domcontentloaded")
        fr = pg.frame_locator("#mainFrame")
        # 6초를 세고 다음으로 넘어가던 자리다. 이 단계에서 실제로 기다리는 것은
        # 프레임 안에서 에디터가 만들어지는 일이고, 그 시간은 매번 다르다.
        # 제목 칸이 붙는 것이 에디터 생성이 끝났다는 신호라 그것을 기다린다.
        fr.locator(SEL["제목"]).wait_for(state="visible", timeout=EDITOR_TIMEOUT_MS)

        # 임시저장 글이 있으면 "이어서 쓰시겠습니까" 팝업이 떠서 모든 클릭을 가로막는다.
        # 취소를 눌러 새 글로 시작한다.
        for key in ("팝업취소", "도움말닫기"):
            try:
                fr.locator(SEL[key]).first.click(timeout=4000)
                pg.wait_for_timeout(800)
            except Exception:
                pass
        pg.wait_for_timeout(1000)

        title_box = fr.locator(SEL["제목"])
        title_box.click()
        # 제목도 본문과 같은 방식으로 넣는다. 짧지만 굳이 글자마다 키 이벤트를
        # 만들 이유가 없고, delay=0 으로 몰아치면 앞글자가 새는 일이 있었다.
        pg.keyboard.insert_text(data["제목"])
        # 실제로 들어갔는지 확인하고 넘어간다.
        if not _wait_text(pg, title_box, data["제목"][:10]):
            print("제목이 입력되지 않았습니다. 화면을 확인하세요.")

        body_box = fr.locator(SEL["본문"]).last
        body_box.click()
        pg.wait_for_timeout(500)

        # 본문을 쓰기 전에 글꼴을 고정한다. 블로그 기본값이 제각각이라 글마다
        # 서체가 달라 보였다. 크기는 블록별로 _set_size 가 따로 맞춘다.
        _set_font_default(pg, fr)

        for b in data["블록"]:
            if b["kind"] == "text":
                # 문단을 통째로 넣는다. 전에는 글자마다 키 이벤트를 만들어, 2,800자
                # 원고면 브라우저 왕복이 2,800번이었다. 느린 데다 리치 에디터가
                # 처리 중에 일부를 흘리기도 했다. insert_text 는 붙여넣기와 같은
                # input 이벤트 한 번으로 끝난다. 문단 구분은 아래 Enter 가 그대로 맡는다.
                # `**굵게**` 구간은 _insert_rich 가 나눠 굵게로 넣는다.
                _insert_rich(pg, fr, b["value"])
                if _URL_ONLY.match(b["value"].strip()):
                    # URL 만 있는 줄은 Enter 를 눌러야 에디터가 링크 카드로 바꾼다.
                    # 카드가 그려지는 데 시간이 걸리는데, 그 전에 다음 블록을 넣으면
                    # 변환이 취소돼 주소가 글자로 남는다. 실제로 마지막 URL 만
                    # 카드가 안 만들어졌다 — 뒤에 빈 줄이 와서 기다릴 틈이 없었다.
                    pg.wait_for_timeout(600)
                    pg.keyboard.press("Escape")
                    pg.wait_for_timeout(200)
                    before = fr.locator(SEL["링크카드"]).count()
                    pg.keyboard.press("Enter")
                    if not _wait_count(pg, fr.locator(SEL["링크카드"]),
                                       before + 1, timeout_ms=8000):
                        print(f"링크 카드가 만들어지지 않았습니다: {b['value'][:60]}")
                else:
                    pg.keyboard.press("Enter")
            elif b["kind"] == "stats":
                # `::수치 …::` 를 글머리 목록으로. 사이트의 <ul><li> 와 같은 구조다.
                _insert_stats(pg, fr, b["value"])
            elif b["kind"] == "quote":
                # `::인용 …::` 를 인용구 컴포넌트로. 사이트의 blockquote 와 같다.
                _insert_quote(pg, fr, b["value"][0], b["value"][1])
            elif b["kind"] == "blank":
                pg.keyboard.press("Enter")
            elif b["kind"] == "heading":
                # 기존 글과 같이 크기 30 · 굵게 로 쓰고, 다음 줄에서 본문 서식으로 되돌린다
                _set_size(pg, fr, HEADING_SIZE)
                # 종전에는 Ctrl+B 로 감쌌는데 이 에디터에서 그 단축키가 먹지 않아
                # 소제목이 크기만 30 이고 굵게가 아니었다. 버튼 토글로 바꾼다.
                _toggle_bold(pg, fr)
                pg.keyboard.insert_text(b["value"])
                _toggle_bold(pg, fr)
                pg.keyboard.press("Enter")
                _set_size(pg, fr, BODY_SIZE)
            elif b["kind"] == "line":
                fr.locator(SEL["구분선"]).click()
                pg.wait_for_timeout(700)
            elif b["kind"] == "image":
                if photo_i >= len(photos):
                    continue
                path, caption = photos[photo_i]
                inserted = fr.locator(".se-component.se-image")
                before = inserted.count()
                with pg.expect_file_chooser(timeout=15000) as fc:
                    fr.locator(SEL["사진"]).click()
                fc.value.set_files(str(path))
                photo_i += 1
                # 3초를 세던 자리다. 여기서 기다리는 것은 업로드가 끝나 사진이 본문에
                # 들어오는 일이고, 그 시간은 파일 크기에 따라 다르다. 실제로 늘었는지
                # 보고 넘어간다. 못 들어오면 알린다.
                if not _wait_count(pg, inserted, before + 1, timeout_ms=30000):
                    print(f"사진 {path.name} 이 본문에 들어오지 않았습니다.")
                elif caption:
                    _set_caption(pg, fr, caption)

                # 사이트는 대표사진 바로 아래에 교육 개요(교육명·기관·일자·대상)와
                # 구분선을 고정으로 넣는다. 첫 사진 다음이 그 자리다.
                if not edu_done:
                    _insert_stats(pg, fr, edu_items)
                    fr.locator(SEL["구분선"]).click()
                    pg.wait_for_timeout(700)
                    edu_done = True
            pg.wait_for_timeout(120)

        print(f"본문 입력 완료. 사진 {photo_i}장, 블록 {len(data['블록'])}개")

        # 에디터가 자체 스크롤이라 full_page 로도 위쪽이 안 잡힌다. 나눠 찍는다.
        #
        # 전에는 780px 씩 세 번 굴렸다. 글 길이에 따라 같은 곳을 두 번 찍거나 끝을
        # 지나쳐 빈 화면을 찍었다. 이제 본문 문단을 처음·중간·끝 세 곳 집어
        # 화면에 들여놓고 찍는다. 픽셀 수가 아니라 실제 요소가 기준이다.
        try:
            # 첫 장은 글 맨 위에서 찍는다. 제목과 글 상단이 들어가야 한다.
            # Ctrl+Home 은 커서가 어디 있느냐에 따라 먹지 않는다 — 실제로 본문을
            # 다 넣은 뒤 눌렀더니 화면이 끝에 머물러 첫 장이 맺음을 찍었다.
            # 둘째·셋째와 같이 요소를 화면에 들여놓는 방식으로 맞춘다.
            try:
                fr.locator(SEL["제목"]).first.scroll_into_view_if_needed(timeout=5000)
            except Exception:
                pg.keyboard.press("Control+Home")
            pg.wait_for_timeout(1200)
            pg.screenshot(path=str(slug_dir / "naver_미리보기1.png"))

            # 둘째·셋째는 본문 문단을 기준으로 아래쪽을 잡는다. 780px 씩 굴리던 것을
            # 대신하며, 글 길이에 상관없이 중간과 끝을 잡는다.
            paras = fr.locator(SEL["본문"])
            n = paras.count()
            # 문단을 못 찾으면 이동 없이 찍는다. 같은 화면이 세 장 남더라도 개수는
            # 종전처럼 1~3 을 채운다.
            picks = [n // 2, n - 1] if n else [None, None]
            for i, idx in enumerate(picks, start=2):
                if idx is not None and idx >= 0:
                    target = paras.nth(idx)
                    target.scroll_into_view_if_needed(timeout=5000)
                    target.wait_for(state="visible", timeout=5000)
                pg.screenshot(path=str(slug_dir / f"naver_미리보기{i}.png"))
            if not n:
                print("본문 문단을 찾지 못해 같은 화면을 세 장 저장했습니다.")
            else:
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
