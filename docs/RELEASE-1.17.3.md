# SlitLamp v1.17.3

- **차트번호(아이디) 중복 안내**: 신규 환자를 등록할 때 이미 있는 차트번호를 넣으면, 예전처럼
  'UNIQUE constraint failed' 오류를 띄우지 않고 등록된 환자(이름 · 생년월일 · 성별 · 진단명)를 보여 줍니다.
  - 이름이 다르면 "차트번호가 중복됩니다 — 등록된 환자 / 입력한 이름" 을 경고로 알리고,
  - **기존 환자로 계속**: 새로 등록하지 않고 기존 환자를 선택해 이어서 촬영합니다 (기존 환자 정보는 그대로).
  - **차트번호 다시 입력**: 등록 창으로 돌아가 번호를 고칩니다.
  - 정보 수정에서 다른 환자가 쓰는 차트번호로 바꾸려 하면 막고 알려 줍니다.
  - 기본판 · Keeler 판 · AI 에이전트 판 · Explorer 판 · Pro 검토 모두 같습니다.
- **검사 기록: 사진 골라 저장**
  - 사진을 **한 번 누르면 선택**(노란 테두리 + 고른 순서 번호), 다시 누르면 해제, **두 번 누르면 크게 보기**.
  - **전체 선택 / 선택 해제**, **선택 저장 (N)** — 고른 사진 · 동영상 원본만 고른 폴더에 저장
    (이름: 차트번호_촬영시각_안구_번호, 같은 이름이 있으면 _2 … 로 덮어쓰지 않음).
  - **인쇄 · PDF** 도 고른 사진이 있으면 그 사진만(고른 순서대로) 넣습니다. 고르지 않으면 예전처럼 그날 사진 전부.
  - 창 폭에 맞춰 한 줄의 사진 수가 바뀌고(좁으면 2장), 좁은 창에서는 위쪽 버튼이 아이콘만 남습니다.

다운로드
- Windows: SlitLampImaging-Setup-1.17.3.exe (기본), KeelerSlitLamp-Setup-1.17.3.exe (Keeler),
  SlitLampExplorer-Setup-1.17.3.exe (Explorer 판), KeelerExplorer-Setup-1.17.3.exe (Keeler Explorer 판),
  SlitLampAgent-Setup-1.17.3.exe (AI 에이전트).
- Mac: 기본 / Keeler / Explorer / Keeler Explorer / 에이전트 각각 arm64(Apple Silicon) · x86_64(Intel) DMG.
- 웹: SlitLamp-Web-1.17.3.zip. 전체 소스: SlitLamp-Source-1.17.3.zip. SHA256SUMS.txt 로 무결성을 확인할 수 있습니다.

기존 데이터 · 설정은 그대로 씁니다.
