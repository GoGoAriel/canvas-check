# webtoon-canvas-monitor

매일 새벽에 Reddit 의 r/webtoons · r/webtoon · r/WebtoonCanvas · r/LINEwebtoon
4개 서브레딧에서 신규 게시물을 RSS 로 가져와 `data/pending_posts.json` 으로
저장합니다. Webtoon 사내 Canvas 센티먼트 대시보드의 데이터 소스로 사용됩니다.

## 동작 방식

- GitHub Actions 가 매일 **00:30 UTC (= 09:30 KST)** 에 자동 실행
- Reddit 의 공개 RSS 피드 사용 (인증 불필요, 무료)
- 윈도우: 직전 PT 24시간 (전날 10am PT ~ 당일 10am PT)
- 결과를 `data/pending_posts.json` 으로 커밋

## 수동 실행

GitHub repo 의 **Actions** 탭 → **Daily Reddit Fetch** → **Run workflow** 버튼.

## 필요한 설정

없습니다. Secrets, API 키, Reddit 계정 — 아무것도 필요 없어요.
공개 RSS 피드만 사용합니다.

## RSS 의 한계

RSS 는 다음 정보를 제공합니다:
- 게시물 ID, 제목, 본문, 작성자, 작성시각, 링크

다음은 제공하지 않습니다:
- 좋아요 수, 댓글 수, upvote ratio

따라서 대시보드 카드에서 좋아요/댓글 숫자는 표시되지 않습니다 (시점 스냅샷이 아니라 "—" 로 표기).
