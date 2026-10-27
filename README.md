# 슬릿램프 디지털 영상 시스템 (Slit-Lamp Imaging)

안과 슬릿램프(세극등 현미경)에 연결된 **HDMI 캡처 장비(UVC 웹캠으로 인식, 예: 에버미디어)** 의
실시간 영상을 받아 **사진 캡처 · 일시정지 · 동영상(mp4) 녹화**를 하고, 각 영상물을
**환자 데이터베이스에 연결 저장**함과 동시에 **지정한 폴더에도 저장**하는 진료실용
네이티브 데스크탑 앱입니다. 단일 PC에서 오프라인으로 동작합니다.

- 화면 좌측: 실시간 영상 + 컨트롤(안구 선택 / 일시정지 / 사진 캡처 / 녹화)
- 화면 우측: 선택한 환자의 캡처 사진을 작은 썸네일 세로줄로(최신이 위) 표시, 클릭 시 크게 보기
- 상단: 환자 검색/선택/신규/수정, **라이트/다크 테마 전환**(설정에 저장)
- 전용 앱 아이콘(`assets/icons/app.ico`) — 실행파일·바로가기·설치 마법사에 적용

> 동일 기능의 **웹 버전**(FastAPI, 브라우저에서 사용)은 `web/` 폴더에 있습니다. 데스크탑 앱과
> 웹 앱 두 가지 버전을 모두 제공합니다. 웹 버전은 MedFix 처럼 **Render/Vercel 에 올려 인터넷 주소로** 쓸 수 있습니다
> (`render.yaml`, `web/vercel.json` — 방법은 `web/README.md` 의 "인터넷 주소로 쓰기").

## 기술 스택
- Python 3.11+, **PySide6**(Qt6), **OpenCV**(opencv-python), **SQLite**(stdlib)
- 동영상: **imageio-ffmpeg**(번들 ffmpeg, H.264/yuv420p) 우선, 실패 시 `cv2.VideoWriter(mp4v)` 폴백
- 대상 OS: **Windows**(캡처: DirectShow) · **macOS 11 이상**(캡처: AVFoundation, Apple Silicon·Intel). 개발/CI는 Linux에서 합성·파일 소스로 가능

## 설치
```bash
pip install -r requirements.txt          # 실행용
pip install -r requirements-dev.txt      # 개발/테스트 포함
```

## 실행
```bash
python run.py                     # 설정 기반(기본: 실제 장치 device)
python run.py --source synthetic  # 하드웨어 없이 합성 영상으로 동작 확인
python run.py --source file       # 설정의 test_file_path 동영상 재생
```
Linux(헤드리스)에서 GUI를 띄우려면 `QT_QPA_PLATFORM=offscreen` 또는 가상 디스플레이(xvfb)를 사용하세요.

## macOS (맥) 버전
같은 소스로 맥에서도 동작합니다. 캡처 장비는 맥에서 자동으로 **AVFoundation** 백엔드로 열리고,
데이터는 `~/Library/Application Support/SlitLampImaging/` 에 저장됩니다.

### 방법 1 — 설치용 dmg 만들기 (권장)
1. 맥에 **Python 3.11 이상** 설치 ([python.org](https://www.python.org/downloads/macos/) 설치본 권장 — 맥 기본 python3 는 3.9 인 경우가 많음)
2. 터미널에서 저장소 폴더로 이동 후 `./build_mac.sh`
3. `dist/SlitLampImaging-<버전>-mac-<arm64|x86_64>.dmg` 를 열고 앱을 **Applications** 로 끌어다 놓기

> 맥이 없어도 GitHub **Actions → "Build macOS app" → Run workflow** 로 Apple Silicon(arm64)·Intel(x86_64)용
> dmg 를 각각 만들 수 있습니다(실행 결과 화면의 *Artifacts* 에서 내려받기).

### 방법 2 — 소스에서 바로 실행
Finder 에서 `run_mac.command` 더블클릭(처음 한 번 자동 설치). 하드웨어 없이 확인: 터미널에서 `./run_mac.command --source synthetic`

### 처음 실행할 때 (보안 · 권한)
- 앱은 Apple 개발자 인증서로 서명·공증되지 않았으므로, 처음에는 **앱 아이콘을 Control-클릭(우클릭) → 열기 → 열기**로 실행합니다.
  (macOS 15 이상: 한 번 실행 시도 후 **시스템 설정 → 개인정보 보호 및 보안 → "그래도 열기"**)
- **카메라 권한** 요청이 뜨면 **허용**. 거부했다면 *시스템 설정 → 개인정보 보호 및 보안 → 카메라*에서 켠 뒤
  상단 **카메라 재연결**을 누르세요(소스 실행 시에는 '터미널'에 권한을 줍니다).
- 단축키는 맥 관례대로 Ctrl 대신 **⌘(Command)** 를 씁니다(⌘Z 실행 취소, ⌘Y 다시 실행). 촬영/Pro 전환은 F2(fn+F2).

## 소니 카메라 (ZV-E10 II · FX3 — MicroREC Ultra 등)
소니 카메라의 **USB 스트리밍**(UVC) 기능으로 **USB 케이블 하나**에 웹캠처럼 연결합니다. 캡처보드·드라이버가 필요 없습니다.

1. 카메라: MENU → **설정(Setup)** → **USB** → **USB 연결 모드** → **USB 스트리밍** (또는 '연결 시 선택')
   — FX3 는 펌웨어 Ver.2.00 이상
2. 같은 메뉴의 **USB 스트리밍 출력 해상도/프레임** → **4K(2160p)** 또는 **HD(1080p)**
3. 카메라 **USB-C** ↔ PC 연결 (4K 는 USB 3 케이블·포트 권장)
4. 프로그램이 소니 카메라를 **자동으로 찾아 선택**합니다 (목록에 ★ 표시)
   - 웹: 상단 카메라 목록 옆에서 **4K / 1080p / 720p** 선택 (기억됨), ⓘ 버튼에 연결 안내
   - 윈도우·맥 앱: 처음 실행 때 자동 선택, **설정**의 카메라 목록에 이름으로 표시 (4K 는 해상도 3840×2160)

> 카메라 자체 셔터로 고해상도 원본(2,400만 화소)을 찍는 **원격 제어**는 소니 Camera Remote SDK 로 데스크탑 앱에 추가할 예정입니다
> (SDK 는 소니 사이트에서 약관 동의 후 내려받아야 합니다).

## 단축키 (사용자 지정)
상단 **⌨ 단축키** 버튼에서 동작마다 원하는 키를 지정합니다. F1~F12, 숫자패드, Ctrl/Alt/Shift 조합,
**USB 발판 스위치**처럼 키를 보내는 장치도 지정할 수 있습니다. 웹은 브라우저에, 윈도우·맥 앱은 `config.json` 에 저장됩니다.

| 동작 | 기본 키 | 적용 |
|------|------|------|
| 사진 캡처 | C | 촬영 화면 |
| 녹화 시작/중지 | R | 촬영 화면 |
| 일시정지/재개 | Space | 촬영 화면 |
| 정지영상 (4분할 칸 채우기) | X | 촬영 화면 |
| 4분할 켜기/끄기 | Q | 촬영 화면 |
| 안구 OD / OS / OU / 미지정 | 1 / 2 / 3 / 0 | 모든 화면 |
| 전체 화면 | F | 모든 화면 |
| 촬영 ↔ Pro 검토 | P (웹) · F2 (앱) | 모든 화면 |
| 환자 목록(검색) / 신규 환자 | L / N | 모든 화면 |

> 웹은 물리 키 기준이라 **한글 입력 상태에서도** 그대로 동작합니다. Pro 화면의 ←/→(이동), Ctrl+Z/Y(실행 취소), Esc 는 고정입니다.

## Keeler 전용 버전 (윈도우 · 맥)
같은 프로그램을 Keeler 공식 로고·브랜드 색(네이비 #052133 · 파랑 #1981b7 · 주황 #ed6f1e)으로 만든 전용판입니다.
상단은 로고만, 창 제목·인쇄 보고서는 "Keeler 슬릿램프 영상 시스템 / 보고서", 아이콘은 로고 마크로 바뀝니다.
기본판과 이름·설치 위치가 달라 **한 PC에 나란히 설치**할 수 있습니다.

| 받는 곳 (GitHub → Actions) | 파일 |
|------|------|
| **Build Windows installer** → Artifacts | `KeelerSlitLamp-windows` (설치파일 `KeelerSlitLamp-Setup-0.1.0.exe`) |
| **Build macOS app** → Artifacts | `KeelerSlitLamp-mac-arm64`(M1/M2/M3) · `KeelerSlitLamp-mac-x86_64`(Intel) |

직접 만들기: 윈도우 `build_installer.bat keeler` · 맥 `./build_mac.sh keeler`
기존 설치본을 Keeler 화면으로 쓰기: 실행 옵션 `--brand keeler` 또는 `config.json` 에 `"brand": "keeler"`

## 화면 디자인 (Clinical Graphite)
안과 영상 프로그램(VK-2, EyeSuite, IMAGEnet 등)처럼 **어두운 그래파이트 작업 공간**을 기본으로 해 영상에 시선이 모이게 했습니다(상단 테마 버튼으로 밝은 테마 전환).

- **상단바**: 브랜드 · **촬영 / Pro 검토** 전환 스위치 · 카메라·설정·테마
- **환자 배너**: 검색·선택, 이니셜 아바타, 차트번호, 성별·나이, 생년월일, **진단명**, 담당의
- **영상 HUD**: 영상 위에 환자 · 안구(OD 파랑 / OS 주황 / OU 보라) · LIVE / 정지 / REC 표시
- **촬영 도크**: OD/OS/OU 안구 스위치, 4분할 · 일시정지, 정지영상 · **셔터형 사진 캡처** · 녹화
- **썸네일**: 촬영일별 묶음, 안구 색 배지, 시각·코멘트 오버레이, 전체 / OD / OS / 동영상 필터

## Pro 모드 (전문가용 영상 검토)
상단 **촬영 / Pro 검토** 전환 스위치(F2)로 기본 촬영 화면과 전문가용 검토 화면을 전환합니다(기본 화면은 그대로 유지).
안과 디지털 영상 시스템(예: Kowa VK-2)의 표준 워크플로를 참고해 구성했습니다.

| 기능 | 설명 |
|------|------|
| **LIVE** | 실시간 영상. **CAPTURE**(Space)로 정지/재개, 안구 선택 후 **SAVE**로 환자 DB 저장 |
| **1화면** | 단일 영상. **PREV/NEXT**(←/→)로 이동, 휠 확대·드래그 이동, 화면 맞춤 |
| **MULTI** | 한 환자의 영상을 **16장(4×4) / 36장(6×6)** 그리드로. 클릭 = 비교 선택(최대 2장), 더블클릭 = 1화면 |
| **비교** | 선택한 2장을 좌우로 비교. 확대·이동 **동기화**, 보정 동일 적용 |
| **이미지 보정** (보정 탭) | 밝기·대비·감마·채도·**RGB 색균형**·**레벨(흑·백점)**·**자동 대비**, 채널(컬러 / **Red-free 녹색** / 적색 / 청색 / 흑백)·**네거티브(NEGA)**, 실시간 **히스토그램**. 원본은 보존 |
| **필터** (필터 탭) | 노이즈 제거(Median / 평균 3×3)·**선명하게**(언샤프 마스크 약/중/강)·**국소 대비 향상**(CLAHE — 혼탁·부종 등 미세 밝기 차 강조) |
| **편집** (편집 탭) | **회전**(90°)·**반전**(좌우/상하)·**자르기**, 주석(텍스트·화살표·원), **길이·각도 측정**(📐 눈금 보정 시 mm 단위), **돋보기**(누르는 동안 2.5배 렌즈), **실행 취소/다시 실행**(20단계, Ctrl+Z / Ctrl+Y)·**원본 복원**. 주석 좌표는 회전·반전·자르기를 따라 변환 |
| **편집본 저장** | 보정·편집·주석·측정이 반영된 새 영상으로 저장(원본 보존). 코멘트 자동 기록: `측정` / `주석` / `편집본` / `보정본` |
| **코멘트 · 환자정보** | 영상별 코멘트 편집, 환자 **진단명·담당의** 편집 |
| **인쇄 / PDF** | A4 보고서: 제목·출력일시, 환자·진단명·담당의, 영상(1/2/4장 배치)·캡션, **소견란**, 확인자 서명·쪽번호 |

> 보정·편집 기능은 VK-2 Image Process(밝기·대비·감마·NEGA·채널·필터·측정)와 일반 세극등 영상 프로그램의 구성을 참고했습니다. 눈금 보정값은 설정(`px_per_mm`)에 저장됩니다.

> 진단명·담당의 컬럼은 기존 DB에도 실행 시 자동으로 추가됩니다(데이터 보존).

윈도우 앱 전용: 인쇄 보고서 머리말의 기관명은 `config.json`의 `clinic_name`으로 지정합니다.

## 설정 / 저장 위치
설정 파일과 기본 데이터는 사용자 앱데이터 폴더에 저장됩니다.
- Windows: `%APPDATA%\SlitLampImaging\`
- macOS: `~/Library/Application Support/SlitLampImaging/`
- 기타(개발): `~/.local/share/SlitLampImaging/`

`config.json` 주요 항목: `camera_index`, `source_mode`(device|file|synthetic),
`capture_width/height`, `photo_format`(png|jpg), `media_root`(기본 저장),
`export_root`(동시 저장 폴더), `db_path`, `subfolder_template`.

저장 경로 규칙(기본): `<root>/<차트번호>_<환자ID>/YYYY-MM-DD/<HHMMSS>_<OD|OS|NA>.<확장자>`
(`export_root`에도 동일 구조로 복사)

앱 실행 후 상단 **설정** 버튼에서 카메라 인덱스, 해상도, 저장 폴더를 변경할 수 있습니다.

## 데이터베이스
SQLite 2개 테이블:
- `patients`: 차트번호, 환자ID, 이름, 생년월일, 성별, 연락처, 메모, 증상
- `captures`: 환자FK, 종류(photo/video), 파일경로, export경로, 썸네일경로, 촬영시각, 안구, 길이(ms)

환자 삭제 시 `ON DELETE CASCADE`로 캡처 레코드도 함께 삭제됩니다(디스크 파일은 보존).

### 튼튼하게 (손상 · 백업 · 잠금)
- **WAL 저널 + synchronous=FULL**: 전원이 갑자기 꺼져도 DB 파일이 깨지지 않고, 저장이 끝난 기록은 남습니다.
- **자동 백업**: 실행할 때 하루 한 번, 종료할 때 그날 기록까지 `backups/slitlamp-YYYYMMDD.db` 로 온라인 백업(최근 14개 보관).
- **손상 자동 복구**: 시작할 때 `quick_check` 로 검사해 손상돼 있으면 `slitlamp.db.corrupt-<시각>` 으로 치워 두고
  가장 최근 백업에서 복원합니다(안내창 표시). 사진·동영상 파일은 영향이 없습니다.
- **잠금 대기 5초**: 백업 도구 등이 잠깐 잠가도 "database is locked" 로 멈추지 않습니다.
- **실패한 쓰기는 롤백**: 차트번호 중복 같은 오류가 다음 작업을 막지 않습니다.
- **한 번만 실행**: 프로그램을 두 번 열면 안내 후 종료합니다(카메라·DB 를 서로 뺏지 않게).

## 끊기지 않게 (영상 · 녹화)
- **화면 프레임은 한 장만 대기**: GUI 가 바쁘면 표시용 프레임은 건너뛰고 최신 프레임만 보여 줍니다 (프레임이 큐에 쌓여 메모리·지연이 늘어나는 일 없음).
  녹화기는 캡처 스레드에서 모든 프레임을 직접 받으므로 녹화는 빠짐없이 됩니다.
- **표시용 축소**: 4K 프레임도 위젯 크기로 먼저 줄인 뒤 변환해 GUI 부하를 줄입니다.
- **녹화 중지는 백그라운드**: 인코더가 파일을 닫는 동안(수 초) 화면이 멈추지 않고, 끝나면 썸네일·DB 에 기록됩니다.
- **카메라 자동 재연결**: USB 캡처 장비가 끊기면 3초(5회 뒤 10초) 간격으로 자동 재연결하고, 복구되면 상태줄에 알립니다.
- **창이 먼저 뜸**: 장치 검색·카메라 열기는 창이 뜬 뒤 백그라운드에서 합니다.
- **예외가 나도 꺼지지 않음**: 처리되지 않은 오류는 `logs/app.log` 에 기록되고 작은 안내창으로만 알립니다.

## 테스트
```bash
QT_QPA_PLATFORM=offscreen pytest
```
DB CRUD/FK, 설정 저장, 프레임 변환/썸네일, 캡처 3중 저장(기본·export·DB), 짧은 동영상 녹화를 검증합니다.

## Windows 실행파일(.exe) 만들기
```bat
pyinstaller --noconfirm build.spec
:: 결과: dist\SlitLampImaging\SlitLampImaging.exe
```
번들 ffmpeg와 Qt 플러그인, 앱 아이콘이 함께 포함됩니다.

> 아이콘(`assets/icons/app.ico`, `app.png`)은 이미 저장소에 포함되어 있습니다.
> 디자인을 바꾸려면 `app/ui/theme.py`의 `_render_icon()` 을 수정한 뒤
> `python tools/generate_icon.py` 로 다시 생성하세요.

## Windows 설치파일(Setup.exe) 만들기 — 일반 프로그램처럼 설치/제거
설치 마법사가 있는 `Setup.exe`를 만들어 시작메뉴/바탕화면 바로가기 등록과 제거(프로그램 추가/제거)를 지원합니다.

**준비:** [Inno Setup 6](https://jrsoftware.org/isdl.php) 설치 (무료)

**원클릭 빌드 (권장):** repo 루트에서 `build_installer.bat` 더블클릭 또는 실행
```bat
build_installer.bat
```
→ 의존성 설치 → PyInstaller 번들 → Inno Setup 컴파일을 한 번에 수행하고
`dist\installer\SlitLampImaging-Setup-0.1.0.exe` 가 생성됩니다.

**수동 빌드:**
```bat
pyinstaller --noconfirm build.spec
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\slitlamp.iss
```

생성된 `Setup.exe`를 클리닉 PC에서 실행하면 설치 마법사가 뜹니다.
- 기본은 **관리자 권한 없이 사용자 폴더에 설치**되며, 마법사에서 "모든 사용자(관리자)" 설치도 선택할 수 있습니다.
- 프로그램 파일과 무관하게 환자 DB·이미지는 항상 `%APPDATA%\SlitLampImaging\` 에 저장되므로, 재설치/업데이트해도 데이터는 보존됩니다.
- 설치 항목 구성: 설치 경로/제거는 `installer\slitlamp.iss`, 표시 이름·버전·게시자는 파일 상단 `#define` 값에서 수정.

## 실제 장비 검증(사용자 Windows PC 필수)
1. 슬릿램프 HDMI → 캡처 장비 → PC. 장치가 UVC 웹캠으로 인식되는지 확인
2. 설정에서 카메라 인덱스 선택 → 라이브 영상 확인(1080p)
3. 일시정지 / 사진 캡처(파일+export+DB+썸네일) / mp4 녹화 및 재생 확인
4. 장치 분리/재연결, 정상 종료 후 재오픈(카메라 잠김 없음) 확인

## 슬릿램프 조이스틱 버튼(캡처 버튼) 연결 — 진단
Keeler 디지털 슬릿램프의 조이스틱 캡처 버튼은 내부 USB 허브 보드를 거쳐 PC 로 오지만 **키보드가 아니라서**
메모장에는 아무것도 찍히지 않습니다. 어떤 형식(사용자 정의 HID / 시리얼)으로 오는지 아래 도구로 확인합니다.
```bash
pip install hidapi pyserial
python tools/usb_buttons_probe.py          # 장치 목록을 보여 준 뒤, 버튼을 누르면 오는 신호를 그대로 출력 (Ctrl+C 종료)
python tools/usb_buttons_probe.py --diff   # USB 를 뽑았다 꽂으면서 '새로 나타난 장치' 만 찾기
```
슬릿램프 전원을 켠 상태에서 연결해야 보드에 전원이 들어옵니다. 출력 전체를 보내 주면 버튼을 '단축키 설정' 의 동작(사진 캡처·녹화 등)에 연결합니다.
