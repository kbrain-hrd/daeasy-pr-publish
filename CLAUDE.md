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
.claude/commands/홍보발행.md               슬래시 명령 절차
config.toml                                접수함·발행완료·out 경로, daeasy 저장소 경로
```

## 명령
- `uv run prpub template` — 양식 생성 (docx + 한글 설치 시 hwp)
- `uv run prpub scan` — 접수함 검증
- `uv run prpub build [폴더명...]` — 패키지 생성
- `uv run prpub done <폴더명...>` — 발행완료로 이동

## 규칙
- 항목을 바꾸려면 `prpub/schema.py` 의 `FIELDS` 만 고치고 `uv run prpub template` 로 양식을 다시 뽑는다. 양식 표의 왼쪽 열 라벨이 파싱 키다.
- `.hwp` 파싱은 한글 COM 으로 hwpx 변환을 거친다 — 한글이 설치된 PC 에서만 된다. `.hwpx`/`.docx` 는 어디서나 된다.
- `daeasy_repo` 가 비어 있으면 `/홍보발행` 은 `out/` 생성까지만 하고 멈춘다.
- 접수함 안의 파일은 팀들이 넣은 원본이다. `done` 으로 옮기는 것 외에 수정·삭제하지 않는다.
