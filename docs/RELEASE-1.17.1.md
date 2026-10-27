# SlitLamp v1.17.1

v1.17.0 은 Windows 빌드의 새 테스트 기준(창 최소 폭)이 너무 빡빡해 게시되지 않았습니다. v1.17.1 은 v1.17.0 의 변경 전부와
Keeler 판 홈 화면 장비 사진을 함께 담은 첫 배포판입니다.

- **Keeler 판 홈 화면 장비 사진**: 시작 화면 왼쪽에 Keeler 슬릿램프 + 영상 시스템 장비 사진이 나옵니다.
  흰 배경을 떼어 내 **화면 바탕(다크 · 라이트 테마 그대로) 위에 장비만** 보이고, 사진 위 문구는 넣지 않습니다.
  - '홈 사진 바꾸기' 로 다른 사진을 넣을 수 있고, 흰 배경 제품 사진은 불러올 때 배경을 자동으로 떼어 같은 방식으로 보입니다.
    배경이 있는 사진은 둥근 칸을 꽉 채웁니다. '기본 사진으로 되돌리기' 로 Keeler 장비 사진으로 돌아갑니다.
- v1.17.0 의 변경 (자세한 내용: [RELEASE-1.17.0.md](RELEASE-1.17.0.md))
  - Keeler K 4색(하늘 · 파랑 · 네이비 · 주황) 디자인: 상단 줄무늬, OD 하늘 · OS 주황, 홈 타일 색, 'KEELER · SLIT LAMP IMAGING'.
  - 작은 화면 글자 · 아이콘 겹침 수정: 창 최소 폭 1455 → 약 1000~1110px, 좁으면 상단 메뉴 · 촬영 도크 아이콘만, Smart 안내 접기,
    긴 도구줄은 옆으로 밀기.
  - 촬영 도크: 분할 · 멀티 '저장' 을 정지영상 바로 옆으로 (셔터 위치 고정).
  - 분할: 처음 고른 칸 수를 기억해 다음부터 바로 시작 (오른쪽 클릭 · 설정 · Explorer 카메라 메뉴로 변경).
  - 참조 영상 비교 창 '화면 저장'(환자 기록) · '파일로 저장…', 라이브러리 참조 영상 '파일로 저장…'.

다운로드
- Windows: SlitLampImaging-Setup-1.17.1.exe (기본), KeelerSlitLamp-Setup-1.17.1.exe (Keeler),
  SlitLampExplorer-Setup-1.17.1.exe (Explorer 판), KeelerExplorer-Setup-1.17.1.exe (Keeler Explorer 판),
  SlitLampAgent-Setup-1.17.1.exe (AI 에이전트).
- Mac: 기본 / Keeler / Explorer / Keeler Explorer / 에이전트 각각 arm64(Apple Silicon) · x86_64(Intel) DMG.
- 웹: SlitLamp-Web-1.17.1.zip. 전체 소스: SlitLamp-Source-1.17.1.zip. SHA256SUMS.txt 로 무결성을 확인할 수 있습니다.

기존 데이터 · 설정은 그대로 씁니다. 분할 칸 수는 업데이트 뒤 처음 한 번 다시 고르면 그때부터 기억합니다.
