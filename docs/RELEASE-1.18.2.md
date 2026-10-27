# SlitLamp v1.18.2

멀티 화면 정리와 작은 화면 수정입니다. 그 밖의 기능(USB 버튼 포함)은 v1.18.1 과 같습니다.

- **멀티 화면에서 '영상 정보' 칸 없앰**: 오른쪽 메뉴(보정 · 필터 · 편집 · 스마트 · 분석 · 정밀 분석)가 맨 위부터 보입니다 (Pro 검토 화면의 '영상 정보' 는 그대로).
- **멀티 화면에서 '참조' 를 열면 창 크기가 이상해지던 문제**: 참조 줄을 열면 창 최소 높이가 719px 로 늘어, 작은 화면(1920×1080 · 150% 배율 등)에서는
  창이 화면보다 커졌습니다. 영상 칸 최소 높이를 360 → 270px(16:9), 참조 줄을 90 → 72px 로 낮춰 참조 줄을 열어도 약 610px 이 되게 했습니다.
- 웹 버전은 v1.18.1 과 같습니다.

다운로드
- Windows: SlitLampImaging-Setup-1.18.2.exe (기본), KeelerSlitLamp-Setup-1.18.2.exe (Keeler),
  SlitLampExplorer-Setup-1.18.2.exe (Explorer 판), KeelerExplorer-Setup-1.18.2.exe (Keeler Explorer 판),
  SlitLampAgent-Setup-1.18.2.exe (AI 에이전트).
- Mac: 기본 / Keeler / Explorer / Keeler Explorer / 에이전트 각각 arm64(Apple Silicon) · x86_64(Intel) DMG.
- 웹: SlitLamp-Web-1.18.2.zip. 전체 소스: SlitLamp-Source-1.18.2.zip. SHA256SUMS.txt 로 무결성을 확인할 수 있습니다.

기존 데이터 · 설정은 그대로 씁니다.
