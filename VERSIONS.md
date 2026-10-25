# 슬릿램프 디지털 영상 시스템 — 버전 목록

각 버전은 아래 커밋 시점의 소스 전체(데스크탑 앱 + `web/` 웹 버전)입니다. "소스 다운로드" 로 해당 버전의 zip 을
바로 받을 수 있습니다(GitHub 로그인이 필요할 수 있음). 웹 버전만 필요하면 zip 안의 `web/` 폴더를 사용합니다.

| 버전 | 날짜 | 주요 변경 | 커밋 | 소스 다운로드 | 웹 버전 폴더 |
|---|---|---|---|---|---|
| v1.0 | 2026-10-24 | 초기 버전 — 캡처·녹화·정지영상·4분할·Pro 모드·영상 편집·Clinical Graphite 디자인·Keeler 브랜드·맥 지원·인터넷 배포 | `f3afbe0` | [zip](https://github.com/kukje1980/Image-capture/archive/f3afbe0f0ae4f1c0db753e75c5b8beb905b9e2c4.zip) | [web/](https://github.com/kukje1980/Image-capture/tree/f3afbe0f0ae4f1c0db753e75c5b8beb905b9e2c4/web) |
| v1.1 | 2026-10-24 | 촬영 저장 속도 개선, '이 PC에만 저장' 모드, Keeler 전용 데스크탑 버전(윈도우·맥) + 설치파일 자동 빌드 | `26a226a` | [zip](https://github.com/kukje1980/Image-capture/archive/26a226ab7d450a635ccf10f5f8e602d7894b3e07.zip) | [web/](https://github.com/kukje1980/Image-capture/tree/26a226ab7d450a635ccf10f5f8e602d7894b3e07/web) |
| v1.2 | 2026-10-24 | 웹 실시간 화면 확대 — 환자 정보 상단바 통합, 환자 목록(표), 전체 화면 | `b8d08f7` | [zip](https://github.com/kukje1980/Image-capture/archive/b8d08f7903868515e1dad0fde15456e46cd5b561.zip) | [web/](https://github.com/kukje1980/Image-capture/tree/b8d08f7903868515e1dad0fde15456e46cd5b561/web) |
| v1.3 | 2026-10-24 | 소니 카메라(ZV-E10 II · FX3) USB 스트리밍 연동 — 자동 인식·해상도 선택·연결 안내 | `150942c` | [zip](https://github.com/kukje1980/Image-capture/archive/150942ccfee5cd90ddd110b17d7880e6ac7c6654.zip) | [web/](https://github.com/kukje1980/Image-capture/tree/150942ccfee5cd90ddd110b17d7880e6ac7c6654/web) |
| v1.4 | 2026-10-24 | 단축키 사용자 지정 — 캡처·녹화·일시정지·정지영상·4분할·OD/OS/OU·전체 화면·모드·환자 | `1b93ab0` | [zip](https://github.com/kukje1980/Image-capture/archive/1b93ab00750a93704f7aed03aba2031c625225db.zip) | [web/](https://github.com/kukje1980/Image-capture/tree/1b93ab00750a93704f7aed03aba2031c625225db/web) |
| v1.5 | 2026-10-24 | 설정(톱니) 창으로 상단 정리 + 마이봄샘(meibography) 촬영·분석 모드 | `546db8d` | [zip](https://github.com/kukje1980/Image-capture/archive/546db8d7e65007686f5c2b1a2d0bd76dd388ce9b.zip) | [web/](https://github.com/kukje1980/Image-capture/tree/546db8d7e65007686f5c2b1a2d0bd76dd388ce9b/web) |
| v1.6 | 2026-10-24 | 전체 점검 버그 수정(웹·Pro·서버·데스크탑), 맥 dmg 생성 재시도, 녹화 길이 정확도 수정, 윈도우 설치파일 릴리스 자동 게시 | `f5c8cee` | [zip](https://github.com/kukje1980/Image-capture/archive/f5c8cee630621f4f9ecf100dc32545c27fcaa0fe.zip) | [web/](https://github.com/kukje1980/Image-capture/tree/f5c8cee630621f4f9ecf100dc32545c27fcaa0fe/web) |
| v1.7.0 | 2026-10-25 | **전체 통합판** — 촬영 효과음, 저장 안정성 강화(DB 트랜잭션·손상 감지·일일 백업), Smart Capture(초점 판정·Best Shot·자동 정지/저장·포커스 피킹), Pro 분석 탭(형광염색·TBUT·충혈·마이봄샘·수정체·품질·DICOM), Pro 스마트 탭, Pro 측정 탭(형광 면적·충혈·정렬·백내장 혼탁 지수·LOCS III·경과 그래프) — **최신** | 이 브랜치 | [릴리스](https://github.com/kukje1980/Image-capture/releases/tag/v1.7.0) | [web/](https://github.com/kukje1980/Image-capture/tree/main/web) |

- v1.7.0 부터는 main 에 반영될 때마다 **GitHub Release `v<버전>`** 에 윈도우 설치파일·맥 dmg·웹 게시용 zip 이 자동으로 올라갑니다 (`.github/workflows/release.yml`).
- 윈도우 설치파일(Setup.exe, 최신 main 빌드): https://github.com/kukje1980/Image-capture/releases/tag/windows-latest
- 터미널에서 특정 버전으로 되돌리기: `git checkout <커밋>` (예: `git checkout 150942c`)
