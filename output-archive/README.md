# daeasy 교육산출물 보관소

데이지 홈페이지 **교육산출물**에 걸려 있는 프로토타입은 lovable 에 올라가 있습니다.
lovable 이나 뒤에 붙은 API 가 끊기면 그대로 사라집니다.
이 저장소는 그 산출물을 **외부에 아무것도 의존하지 않는 정적 파일로** 떠서 보관합니다.

## 보관 현황

모두 2026-09-01 기준으로 떴습니다.

| 산출물 | 원본 | 화면·데이터 | 동작하지 않는 것 |
|---|---|---|---|
| 종합 취약지역 스코어링 (영등포구) | `ydp-insight-hub` | ✅ 전부 | 없음 |
| 국민신문고 AI 민원 비서 | `singoai` | ✅ 전부 | PDF 업로드 · AI 답변 생성 |
| Juris Lexicon 법률 채팅 | `lawfind` | ✅ 전부 | 녹화한 예시 질문 10개는 **답변됨**. 그 밖의 질문은 불가 |

**영등포구 대시보드는 완전히 살아납니다.** 화면을 열면 데이터가 오는 구조라
그 응답을 미리 떠둘 수 있었습니다.

**나머지 둘은 화면·데이터·이동은 전부 되지만 AI 기능만 죽습니다.** 이 앱들의
서버함수는 전부 POST 라 미리 뜰 수가 없습니다(`405 Method Not Allowed`).
사용자가 입력을 넣어야 비로소 답을 만드는 구조이기 때문입니다.
그래서 방문자가 개발자 에러 메시지를 보지 않도록 `offline/notice.js` 가
"보관본이고 무엇이 안 되는지"를 화면 아래에 알립니다.

## 예시 질문 녹화 (lawfind)

AI 답변은 미리 만들어둘 수 없지만, **원본이 살아 있을 때 대표 질문을 실제로
물어보고 그 답을 저장해두면** 보관본에서 그 질문들에는 진짜 답이 나옵니다.

`tools/record.py` 가 질문 하나당 요청 하나를 보내 응답을 `offline/recorded.js`
에 모으고, `offline/replay.js` 가 보관본에서 그것을 되돌려줍니다.
녹화에 없는 질문에는 앱의 답변 자리에 "예시 질문만 답한다"는 안내와 질문 목록이
뜹니다 — 그냥 두면 방문자에게 개발자 에러가 그대로 보입니다.

`tools/patch_examples.py` 가 화면의 추천 질문 목록을 녹화한 질문으로 바꿉니다.
**번들과 HTML 양쪽 다** 바꿔야 합니다. 한쪽만 바꾸면 React 하이드레이션 오류가 납니다.

현재 lawfind 는 공공기관 실무에서 나올 만한 질문 10개를 녹화해 두었습니다
(`sites.json` 의 `record.questions`). 지도에서 영등포구 범위만 받아둔 것과
발상은 같지만 차이가 있습니다 — 지도는 받아둔 범위 **안이면 어디든** 되는 반면,
질문은 녹화한 10개라는 **점**만 되고 그 사이는 비어 있습니다.

## 왜 HTML 만 저장하면 안 되는가

lovable 앱은 정적 SPA 가 아니라 **TanStack Start 서버 앱**입니다.
화면 HTML 만 저장하면 첫 화면은 완벽하게 뜨지만 **아무거나 클릭하는 순간
`This page didn't load` 로 죽습니다.** 세 가지를 같이 떠야 합니다.

| 떠야 할 것 | 왜 |
|---|---|
| 라우트별 HTML | 서버가 렌더한 결과라 데이터가 여기 박혀 있음 |
| `assets/` js·css | 앱 코드 |
| `/_serverFn/<64자 hex>` | **이게 빠져서 클릭하면 죽던 것.** 화면 전환마다 호출됨 |

서버함수 응답을 **받을 때**는 요청에 `x-tsr-serverFn: true` 헤더가 필요합니다.
앱은 응답의 `x-tss-serialized: true` 헤더를 보고 본문을 해석하는데, 이게 없으면
`data is undefined` 로 죽습니다. 원래 서버가 붙여주던 것이라 처음에는 헤더 설정이
되는 호스팅이 필요했지만, `offline/serverfn.js` 가 fetch 를 가로채 직접 붙여주므로
**지금은 아무 정적 호스팅에나 올려도 됩니다** (GitHub Pages 포함).

## 지도는 어떻게 했는가

영등포구 대시보드는 구글 지도를 쓰는데, API 키가 lovable 도메인에 묶여 있어
다른 곳으로 옮기면 지도가 빈칸이 됩니다.

앱이 실제로 쓰는 구글 지도 API 는 `Map` · `InfoWindow` · `Polygon` · `Marker`
**네 가지뿐**이었습니다. 그만큼만 Leaflet 으로 흉내 내는 어댑터
(`offline-map/gmaps-shim.js`)를 끼워 넣었더니 **앱 코드를 한 줄도 고치지 않고**
지도 4개 화면(스코어링·인구구조·인프라·부동산)이 전부 그대로 동작합니다.
색칠·클릭 팝업·탭 전환까지 원본 로직이 그대로 굴러갑니다.

배경 지도는 OpenStreetMap 타일을 **영등포구 범위만** 미리 받아 함께 보관합니다
(708장 · 19MB · z13~16). 구 밖으로는 지도가 나가지 않지만, 영등포구 대시보드라
나갈 일이 없습니다. 화면에 출처를 표기했습니다.

## lovable 흔적 제거

정식 게시용이므로 원본 제작 도구의 흔적은 `tools/strip_lovable.py` 로 걷어냅니다 —
화면 오른쪽 아래 "Edit with Lovable" 배지, 분석용 `~flock.js`, 그리고 링크 미리보기
이미지가 가리키던 lovable 이미지 서버(내려받아 `offline/preview.png` 로 함께 보관).
바깥으로 나가는 요청을 없앤다는 보관 취지에도 맞습니다.

## 쓰는 법

새 산출물이 올라오면 **`/산출물 <원본주소>`** 를 쓰면 됩니다.
아래 절차를 순서대로 진행하고, 판단이 필요한 지점(지도 범위, AI 기능 처리)에서 물어봅니다.
절차서는 `.claude/commands/산출물.md` 에 있습니다.

도구를 직접 돌릴 수도 있습니다. 저장소 루트에서 실행하며, 표준 라이브러리만 쓰므로 따로 설치할 것이 없습니다.

```bash
uv run python output-archive/tools/mirror.py ydp-insight-hub   # 라우트·에셋·서버함수
uv run python output-archive/tools/tiles.py  ydp-insight-hub   # 지도 타일 (지도 있는 사이트만)
uv run python output-archive/tools/inject.py ydp-insight-hub   # 보정 스크립트 끼워넣기

uv run python output-archive/serve.py ydp-insight-hub          # http://127.0.0.1:8800

uv run python output-archive/tools/strip_lovable.py ydp-insight-hub   # lovable 흔적 제거
uv run python output-archive/tools/record.py lawfind                  # 예시 질문 답변 녹화
uv run python output-archive/tools/patch_examples.py lawfind          # 추천 질문 목록 교체
```

`docs/` 에 화면 확인 결과를 한 파일에 담은 단독 html 이 있습니다. 보고용으로 그대로 쓸 수 있습니다.

대상 사이트·라우트 목록·지도 범위는 `sites.json` 에 있습니다.

## 배포

`sites/<슬러그>/` 폴더를 그대로 정적 호스팅에 올리면 됩니다.
특별한 서버 설정이 필요 없습니다 — Vercel·Netlify·GitHub Pages·사내 웹서버 다 됩니다.
Vercel 이면 프로젝트의 **Root Directory 를 `output-archive/sites/<슬러그>`** 로 지정하세요.

**파일을 더블클릭해서는 열리지 않습니다.** 경로가 절대경로라 웹서버가 하나 필요합니다.

## 주의

- `sites/` 안의 파일은 **원본을 그대로 뜬 것**입니다. 손으로 고치지 마세요.
  고칠 일이 있으면 `tools/` 를 고치고 다시 뜨는 게 맞습니다.
- 다시 뜨면 **그 시점의 데이터로 갱신**됩니다. 원본이 살아 있는 동안에만 가능합니다.
- 배경 지도 타일은 OpenStreetMap 자료입니다. 정식 게시 전에 이용 약관을
  한 번 확인하세요. 출처 표기는 이미 들어가 있습니다.
