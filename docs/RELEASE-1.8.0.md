# SlitLamp v1.8.0 통합판

2026-10-25의 효과음, 스마트 캡처 두 작업, 영상 분석, 데이터베이스·녹화 안정성 변경을 통합했습니다.

- Windows: SlitLampImaging-Setup-1.8.0.exe (기본), KeelerSlitLamp-Setup-1.8.0.exe (Keeler).
- Mac: 기본/Keeler 각각 arm64(Apple Silicon)·x86_64(Intel) DMG.
- 웹: SlitLamp-Web-1.8.0.zip을 풀고 web/ 폴더를 기존 Vercel 프로젝트에 배포하거나 로컬 실행합니다.
- 전체 소스: SlitLamp-Source-1.8.0.zip. 가상환경·환자 데이터는 포함하지 않습니다.
- SHA256SUMS.txt로 다운로드 파일의 무결성을 확인할 수 있습니다.

Pro에는 기존 스마트·분석 탭과 정밀 분석 탭을 함께 제공합니다. 데스크톱 전용 분석 기능은 웹에 포함되지 않습니다.

기존 데이터는 보존하며 DB 시작 시 손상 검사·일일 백업을 수행합니다. 설치 전 기존 DB와 미디어 폴더의 백업을 권합니다.
Mac 앱은 임시 서명이며 Apple 개발자 공증은 포함되지 않습니다. 카메라 실장비 연결과 분석 지표의 임상 검증은 별도로 확인해야 합니다.
