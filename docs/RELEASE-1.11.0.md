# SlitLamp v1.11.0

데스크탑 앱(맥·윈도우)에 **질환별 샘플 사진 가져오기**를 추가했습니다.

- 상단 오른쪽 **샘플** 버튼 → 받아 둔 샘플 사진 폴더(예: `일반외래_슬릿램프_질환순`)를 고르면
  질환마다 `샘플 · 건성안 (SAMPLE-01)` 같은 환자가 생기고, 환자를 고르면 사진이 썸네일·Pro 화면에 바로 보입니다. PC마다 한 번만 하면 됩니다.
- 사진은 원본 그대로 복사합니다(색·크기·워터마크 변경 없음). 원문 진단·출처·라이선스와 저해상도·외상 여부는 각 영상 코멘트에 남깁니다.
  등급(LOCS 등)은 붙이지 않으며, 샘플 환자는 실제 환자가 아닙니다.
- 같은 폴더를 다시 가져와도 이미 등록된 사진은 건너뛰고, `metadata.json` 의 SHA-256 과 다른 파일은 등록하지 않습니다.
- 샘플 사진은 설치파일에 들어 있지 않습니다(대부분 CC BY-NC-ND — 비영리·변경 금지). 수집 목록과 이용 조건은 `docs/SAMPLE_PHOTOS.md` 를 보세요.
- 웹 버전은 v1.10.0 과 같습니다.

다운로드
- Windows: SlitLampImaging-Setup-1.11.0.exe (기본), KeelerSlitLamp-Setup-1.11.0.exe (Keeler).
- Mac: 기본/Keeler 각각 arm64(Apple Silicon)·x86_64(Intel) DMG.
- 웹: Vercel·Render 는 main 에서 자동 배포. 직접 올릴 때는 SlitLamp-Web-1.11.0.zip.
- 전체 소스: SlitLamp-Source-1.11.0.zip. SHA256SUMS.txt 로 무결성을 확인할 수 있습니다.

기존 데이터는 그대로 사용합니다.
