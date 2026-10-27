# SlitLamp v1.15.1

Explorer 판(SlitLampExplorer)을 고치고, Keeler 로고·색으로 만든 **Keeler Explorer 판(KeelerExplorer)** 을 추가했습니다.
기본판 · Keeler 판 · AI 에이전트 판은 v1.15.0 과 같습니다.

- **샘플 사진을 참조 영상으로**: '샘플 사진 가져오기'로 등록한 질환별 샘플 사진이 **참조 영상** 라이브러리의
  '샘플 사진' 아래 질환별(건성안 · 백내장 …)로 바로 보입니다. 사진을 복사하지 않고 원본을 그대로 보여 주며,
  원문 진단 · 출처 · 라이선스를 함께 표시하고 **현재 환자 영상과 나란히 비교**할 수 있습니다.
  라이브러리 왼쪽 아래 · 파일 메뉴 · 설정 창에서 **샘플 사진 가져오기**를 할 수 있습니다.
- **정지영상 · 분할 정지영상**: 촬영 막대와 툴바에 기본판과 같은 **정지영상**(누르면 멈춤 · 다시 누르면 라이브)과
  **분할**(2 · 4 · 6 · 8 · 16칸 — 정지영상으로 칸을 차례로 채우고, 칸을 누르면 그 칸만 다시, 다 차면 '처음부터')을 넣었습니다.
  **분할 저장**은 칸별 영상과 합성 영상을 선택한 검사에 저장합니다. 고른 칸 수는 기억합니다. 단축키: 정지영상 X · 분할 Q.
- **영상 목록 세로 배치**: **보기 → 영상 목록 세로 (오른쪽)** 을 켜거나 영상 목록 칸을 끌어 오른쪽에 놓으면
  썸네일이 오른쪽 세로 줄로 바뀝니다. 다음 실행에도 같은 배치로 열립니다.
- 정지영상 단축키(X)가 Explorer 판에서 동작하지 않던 문제를 고쳤습니다.
- **Keeler Explorer 판(새로)**: Explorer 판의 화면·기능 그대로에 Keeler 로고(툴바 오른쪽 끝, 밝은/어두운 테마별)와
  Keeler 네이비·파랑 색, Keeler 아이콘, "Keeler 슬릿램프 영상 보고서" 제목을 입혔습니다. 다른 판과 나란히 설치되고
  환자 DB·영상은 같은 데이터 폴더를 함께 씁니다.
  Keeler 홈페이지 색 역할에 맞춰 머리(메뉴바·툴바)는 밝은/어두운 테마와 상관없이 Keeler 네이비에 흰 글자 로고,
  그 아래 Keeler 파랑 선, 사진 캡처 셔터에는 로고 마크의 주황 링을 둘렀습니다 (Keeler 판 셔터도 같은 주황 링).

다운로드
- Windows: SlitLampImaging-Setup-1.15.1.exe (기본), KeelerSlitLamp-Setup-1.15.1.exe (Keeler),
  **SlitLampExplorer-Setup-1.15.1.exe (Explorer 판)**, **KeelerExplorer-Setup-1.15.1.exe (Keeler Explorer 판)**,
  SlitLampAgent-Setup-1.15.1.exe (AI 에이전트).
- Mac: 기본 / Keeler / Explorer / Keeler Explorer / 에이전트 각각 arm64(Apple Silicon) · x86_64(Intel) DMG.
- 웹: SlitLamp-Web-1.15.1.zip. 전체 소스: SlitLamp-Source-1.15.1.zip. SHA256SUMS.txt 로 무결성을 확인할 수 있습니다.

기존 데이터 · 설정은 그대로 씁니다.
