# daeasy 교육산출물 보관소

데이지 홈페이지 교육산출물의 lovable 프로토타입을 외부 의존 없는 정적 파일로 떠서 보관한다.
배경과 방법은 `README.md` 에 있다. 여기는 작업할 때 걸리는 것만 적는다.

## 구조
```
sites.json                사이트별 원본 주소 · 라우트 목록 · 지도 범위
tools/mirror.py           라우트 HTML · assets · _serverFn 응답 내려받기
tools/tiles.py            OpenStreetMap 타일 내려받기 (지역 범위만)
tools/inject.py           각 HTML 에 보정 <script> 끼워넣기
tools/record.py           원본이 살아 있을 때 예시 질문 답변 녹화
tools/patch_examples.py   화면의 추천 질문 목록을 녹화한 질문으로 교체
tools/strip_lovable.py    lovable 배지·추적 스크립트 제거, 미리보기 이미지 내려받기
docs/                     보고용 확인 문서 (화면 캡처를 한 파일에 담은 단독 html)
sites/<슬러그>/            결과물. 원본을 뜬 것이므로 손으로 고치지 않는다
  offline/serverfn.js         서버함수 응답에 x-tss-serialized 헤더를 붙인다 (모든 사이트)
  offline/gmaps.js            구글지도 → Leaflet 어댑터 (지도 있는 사이트만)
  offline/notice.js           보관본 안내 띠 (sites.json 에 notice 가 있는 사이트만)
  offline/recorded.js         녹화한 답변 (record.py 가 만든다)
  offline/replay.js           녹화 답변 되돌려주기 (record 가 있는 사이트만)
serve.py                  로컬 확인용 (헤더·라우팅을 배포와 똑같이 맞춰준다)
```

## 반드시 지킬 것

- **`_serverFn` 응답에 `x-tss-serialized: true` 헤더가 없으면 앱이 죽는다.**
  `data is undefined` 가 나오면 십중팔구 이것이다. `offline/serverfn.js` 가
  fetch 를 가로채 붙여주므로 호스팅 설정은 필요 없다. 이 파일을 빼면 안 된다.
- **보정 스크립트는 앱 번들보다 먼저 실행돼야 한다.** 앱이 `window.fetch` /
  `window.google?.maps` 를 쓰기 전에 올라와야 하므로 일반 `<script>` 로
  `</head>` 앞에 넣는다. 모듈 스크립트(`type="module"`)로 바꾸면 defer 라 늦게 실행돼 죽는다.
- **`offline/gmaps.js` 의 `BOUNDS` 와 `sites.json` 의 `map.bounds` 는 같은 값이어야 한다.**
  어긋나면 받아둔 타일 밖으로 지도가 나가 회색 여백이 생긴다.
- `sites/` 안을 직접 수정하지 않는다. `tools/` 를 고치고 다시 뜬다.

## 새 산출물을 추가할 때

1. `sites.json` 에 항목 추가 (원본 주소 · 라우트 목록)
2. `tools/mirror.py` 실행 → `serve.py` 로 띄워 클릭해본다
3. `tools/inject.py` 로 보정 스크립트를 넣는다. 지도가 있으면 `sites.json` 에
   `map` 범위를 먼저 정하고 `tools/tiles.py` 로 타일을 받는다.
   `offline/` 폴더(serverfn.js·leaflet·gmaps.js)는 기존 사이트에서 복사해 쓴다.
4. 라우트 목록은 원본 HTML 의 `"/xxx"` 패턴이나 사이드바 링크에서 찾는다

## 알아둘 것

- 앱이 쓰는 구글 지도 API 는 `Map` · `InfoWindow` · `Polygon` · `Marker` 넷뿐이다.
  다른 산출물이 `Data` 레이어나 `DirectionsService` 를 쓰면 어댑터를 늘려야 한다.
- 행정동 경계(GeoJSON)는 원본 번들 안에 이미 들어 있었다. 따로 구할 필요 없다.
- **LLM 을 부르는 산출물(`singoai`·`lawfind`)은 AI 기능이 죽는다 (확인함).**
  이 앱들의 서버함수는 전부 POST 라 미리 뜰 수 없다 — `mirror.py` 가 405 를 받고
  `_serverFn/NEEDS-INPUT.txt` 에 목록만 남긴다. 화면·데이터·이동은 전부 정상이다.
  `sites.json` 의 `notice` 로 방문자에게 안내를 띄운다.
- POST 서버함수는 원본에서 녹화해 되돌려주는 수밖에 없다. `lawfind` 는 질문 10개를
  녹화해 시연 모드로 만들었다 (`tools/record.py`). `singoai` 는 PDF 업로드가 얽혀
  있어 아직 하지 않았다.
- **추천 질문을 바꿀 때는 번들과 HTML 을 같이 바꾼다.** 한쪽만 바꾸면 React 가
  하이드레이션 오류(#418)를 낸다. `tools/patch_examples.py` 가 둘 다 처리한다.
- 브라우저에 남은 이전 대화(localStorage)가 있으면 #418 이 뜨는데 이건 원본에도
  있는 현상이다. 판단할 때는 localStorage 를 비우고 확인한다.
- **화면이 이상하면 브라우저 캐시부터 의심한다.** 파일을 고쳤는데 그대로면
  `?v=2` 를 붙여 다시 불러 확인한다. 배지 제거 확인 때 이걸로 헷갈렸다.
- `singoai` 완료함 아래 "AI 처리 트렌드 분석" 차트는 **원본도 비어 있다.**
  축과 각주만 있고 그래프가 없다. 보관 과정에서 깨진 것이 아니니 고치려 들지 않는다.
