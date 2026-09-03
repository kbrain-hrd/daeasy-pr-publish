# daeasy 홍보자료 발행 도구

다른 팀이 **한글/워드 양식 + 사진·자료 폴더**로 홍보자료를 접수함에 넣으면,
개발자가 `/홍보발행` 슬래시 명령 한 번으로 검증 → 게시글 패키지 생성 → 사이트 반영까지 처리한다.

## 구조
```
templates/홍보자료_양식.{hwp,docx}        배포용 양식 (uv run prpub template 로 재생성)
접수함/<날짜_기관_과정>/                   팀들이 넣는 폴더: 양식 파일 + 사진/ + 자료/
발행완료/<YYYY-MM>/                        발행 끝난 폴더 이동처
out/<slug>/                                brief.md(등록 내용 정리) · meta.json · images/ · files/ · photos.md · post.md(LLM 작성)
prpub/                                     schema(항목) · template · parse(docx/hwpx/hwp) · scan(검증) · build · cli
scripts/                                   search_kr(한국 웹 검색) · make_chart · preview · style_check
.claude/commands/홍보발행.md               슬래시 명령 절차
.claude/agents/                            정보수집 → 글검수(1차) → 발행검수(2차)
config.toml                                접수함·발행완료·out 경로, daeasy 저장소 경로
.secrets.toml                              검색 API 키. 저장소에 올라가지 않는다
```

## 명령
- `uv run prpub template` — 양식 생성 (docx + 한글 설치 시 hwp)
- `uv run prpub scan` — 접수함 검증
- `uv run prpub build [폴더명...]` — 패키지 생성
- `uv run prpub done <폴더명...>` — 발행완료로 이동
- `uv run prpub naver-login` — 네이버 로그인 창을 띄워 세션 저장 (최초 1회)
- `uv run prpub naver <폴더명> [--publish]` — 네이버 블로그에 글 작성 (`--publish` 없으면 발행 직전 정지)

## 규칙
- 항목을 바꾸려면 `prpub/schema.py` 의 `FIELDS` 만 고치고 `uv run prpub template` 로 양식을 다시 뽑는다. 양식 표의 왼쪽 열 라벨이 파싱 키다.
- `.hwp` 파싱은 한글 COM 으로 hwpx 변환을 거친다 — 한글이 설치된 PC 에서만 된다. `.hwpx`/`.docx` 는 어디서나 된다.
- `daeasy_repo` 가 비어 있으면 `/홍보발행` 은 `out/` 생성까지만 하고 멈춘다.
- 접수함 안의 파일은 팀들이 넣은 원본이다. `done` 으로 옮기는 것 외에 수정·삭제하지 않는다.
- 네이버는 2020년에 글쓰기 API 를 닫아 브라우저 자동화 외에 방법이 없다. 로그인 세션은 `.naver-session.json` 에 두고 저장소에 올리지 않는다.
- 자료조사는 `scripts/search_kr.py` 로 한다. 정책브리핑은 키 없이 되고, 네이버·다음 검색 API 는 키가 있어야 한다. **키가 없으면 "못 돌림"이지 "없음"이 아니다** — 보고에 구분해 적는다.
- 네이버 검색 API 는 개발자센터가 2026-07-31 신규 신청을 닫아 **NAVER API HUB(NCP)** 에서 받는다. 주소·헤더가 바뀌면 코드가 아니라 `.secrets.toml` 의 `naver_api_base` · `naver_id_header` · `naver_secret_header` 를 고친다.
- **네이버는 긁지 않는다.** `search.naver.com`·`blog.naver.com`·`rss.blog.naver.com` 모두 `robots.txt` 가 전면 차단이고 RAG 목적 봇을 명시 금지하며 `ClaudeBot` 을 지목한다. 검색 API 가 유일한 문이다. 구글 뉴스 RSS 도 비상업 전용이라 쓰지 않는다.
- 스마트에디터 화면이 바뀌면 `prpub/naver.py` 의 `SEL` 만 고치면 된다.

---

# 교육산출물 보관 (`output-archive/`)

데이지 홈페이지 교육산출물의 lovable 프로토타입을 외부 의존 없는 정적 파일로 떠서 보관한다.
홍보자료 발행과는 별개의 작업이고, 폴더 안에 자체 `README.md` · `CLAUDE.md` 가 있다.
산출물 보관 관련 요청은 그 문서를 먼저 읽는다.

- `/산출물 <원본주소>` 새 산출물을 보관본으로 만드는 슬래시 명령
- `output-archive/sites.json` 대상 사이트 목록
- `output-archive/tools/` 내려받기·타일·주입 스크립트 (표준 라이브러리만 사용)
- `output-archive/serve.py` 로컬 확인
