# 슬릿램프 영상 시스템 — 웹앱

안과 슬릿램프 HDMI 캡처 장비(브라우저에서 UVC 웹캠으로 인식)의 실시간 영상을 받아
**사진 캡처 · 일시정지 · 동영상 녹화**를 하고, 각 영상물을 **환자 DB + 서버 미디어 폴더에 저장**함과
**동시에 브라우저가 지정한 로컬 폴더에도 저장**하는 웹 애플리케이션입니다.

클리닉 PC에서 로컬 서버(uvicorn)로 실행하며, 브라우저(Chrome/Edge 권장)로 `localhost` 접속해 사용합니다.
동일 시스템의 **데스크탑 앱(Windows·macOS)**은 이 저장소 상위 폴더(`../app`)에 별도로 있습니다.

## 기술 스택
- **FastAPI** + **Jinja2** + **바닐라 JS** (빌드 도구 없음)
- **SQLite** (stdlib), **uvicorn**
- 캡처: 브라우저 `getUserMedia`, 사진 `canvas.toBlob`, 동영상 `MediaRecorder`(mp4 우선/webm 폴백)
- 지정 폴더 저장: **File System Access API** (`showDirectoryPicker`, Chrome/Edge)

## 설치 & 실행 (내 PC에서)

### 원클릭 실행 (권장)
준비물: **Python 3.11 이상**([python.org](https://www.python.org/downloads/)), 브라우저 **Chrome 또는 Edge**

- **Windows**: `web\run_web.bat` 더블클릭
- **macOS**: Finder 에서 `web/run_web.command` 더블클릭
  (처음 한 번 "확인되지 않은 개발자" 경고가 뜨면 Control-클릭 → 열기)
- **Linux**: 터미널에서 `./web/run_web.sh`

처음 실행 때만 필요한 패키지를 자동 설치(1~2분)하고, 서버가 준비되면 브라우저가
**http://127.0.0.1:8000** 으로 자동으로 열립니다. 실행 창(검은 창/터미널)을 닫거나 Ctrl+C 를 누르면 종료됩니다.

#### 브라우저에서 "사이트에 연결할 수 없음"이 뜰 때
1. 주소를 **http://127.0.0.1:8000** 으로 입력해 보세요 (`localhost` 가 IPv6 로 연결되는 PC가 있음).
2. 검은 창에 `Uvicorn running on http://127.0.0.1:8000` 이 보일 때까지 기다리세요 (첫 실행은 설치 때문에 1~2분).
3. 검은 창에 **[오류]** 가 보이면 그 메시지대로 조치 후 다시 실행 — 설치가 중간에 실패했으면 다음 실행 때 자동으로 다시 설치합니다.
4. `address already in use` 가 보이면 이미 다른 창에서 실행 중이므로 그 주소를 그냥 열면 됩니다.

### 수동 실행
```bash
cd web
python -m venv .venv
# Windows:  .venv\Scripts\activate   /  macOS·Linux:  source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```
브라우저에서 **http://localhost:8000** 접속.

> 카메라(getUserMedia)와 폴더 저장(File System Access)은 **localhost 또는 HTTPS**에서만 동작합니다.
> `127.0.0.1`/`localhost` 는 보안 컨텍스트로 취급되어 그대로 사용 가능합니다.

## 인터넷 주소로 쓰기 (MedFix 처럼 — 설치 없이 브라우저로 접속)
PC마다 프로그램을 설치하지 않고 **https://주소** 하나로 어느 컴퓨터에서나 접속합니다.
HTTPS 주소라서 카메라·저장 폴더 기능도 그대로 동작합니다.

### Render (권장 — 사진·동영상 모두 저장)
1. [render.com](https://render.com) 에 GitHub 계정으로 로그인
2. **New → Blueprint** → 저장소 `Image-capture` 선택 → 브랜치 `claude/slit-lamp-imaging-system-ecM9y` (병합 후에는 `main`)
3. 저장소의 `render.yaml` 이 자동으로 읽힙니다. **SLITLAMP_PASSWORD**(접속 비밀번호) 입력란에 비밀번호를 넣고 **Apply**
4. 몇 분 뒤 `https://slitlamp-imaging.onrender.com` 같은 주소가 생깁니다 → 접속 → 비밀번호 입력

> **무료 플랜 주의:** 15분간 사용이 없으면 잠들어 첫 접속이 30초~1분 걸리고, 재시작·재배포 때
> 서버에 저장된 환자 DB·영상이 지워집니다. 촬영 화면 상단 **저장 폴더**를 지정해 두면 촬영본은 PC 폴더에 그대로 남습니다.
> 서버에 영구 보관하려면 `render.yaml` 의 안내대로 유료 플랜 + 디스크를 붙이세요.

### Vercel (MedFix 와 같은 서비스)
1. [vercel.com](https://vercel.com) → **Add New → Project** → `Image-capture` 가져오기
2. **Root Directory 를 `web`** 으로 지정 (중요), Environment Variables 에 `SLITLAMP_PASSWORD` 추가 → **Deploy**

> **Vercel 제약:** 저장 공간이 임시(수시로 초기화)이고 업로드가 약 4.5MB로 제한되어 **긴 동영상은 저장되지 않습니다**
> (큰 사진은 자동으로 고화질 JPEG로 줄여 올림). 화면 확인·사진 위주 사용에 적합하며, 실사용은 Render 를 권장합니다.

### 접속 비밀번호
`SLITLAMP_PASSWORD` 환경변수를 주면 로그인 화면이 켜집니다(브라우저당 30일 유지, `/logout` 으로 로그아웃).
환자 정보가 인터넷에 노출되지 않도록 **배포할 때는 반드시 설정**하세요. 로컬(내 PC) 실행에서는 설정하지 않아도 됩니다.

## 브랜드 버전 (Keeler 전용 등)
같은 코드로 회사별 전용 화면을 만듭니다. 환경변수 **`SLITLAMP_BRAND`** 로 고릅니다.

| 값 | 화면 |
|----|------|
| (없음) | 기본 슬릿램프 영상 시스템 (티얼 색) |
| `keeler` | **Keeler 전용** — Keeler 공식 로고·브랜드 색(네이비 #052133 · 파랑 #1981b7 · 주황 #ed6f1e), 보고서 머리말 "Keeler 슬릿램프 영상 보고서" |

**바로 쓰기:** 이미 배포된 주소 뒤에 **`/keeler`** 를 붙이면 Keeler 화면이 열립니다
(예: `https://image-capture-web.vercel.app/keeler`). 같은 서버·같은 환자 DB 를 씁니다.

**Keeler 전용 주소를 따로 만들기 (Vercel, 2~3분 — 데이터도 분리)**
1. vercel.com → **Add New → Project** → 같은 `Image-capture` 저장소 **Import** (프로젝트 이름 예: `keeler-slitlamp`)
2. **Root Directory = `web`**
3. Environment Variables: `SLITLAMP_PASSWORD` = 접속 비밀번호 → **Deploy**
   (프로젝트 이름에 `keeler` 가 들어가면 주소로 자동 인식해 Keeler 화면이 됩니다. 다른 이름이면 `SLITLAMP_BRAND` = `keeler` 도 추가)

**로고 · 색 바꾸기** — `web/static/brand/keeler/`
- `logo.svg`(또는 `.png`): 밝은 화면용 공식 로고, `logo-dark.svg`(선택): 어두운 화면용(흰색) 로고
  → 파일을 넣고 저장소에 올리면 상단·로그인·인쇄 보고서에 자동 표시됩니다(없으면 글자 'Keeler'로 표시).
- `theme.css`: 맨 위 `--keeler-navy`, `--keeler-blue` 두 값이 브랜드 색입니다. 공식 색 코드로 바꾸면 전체에 반영됩니다.

> 회사 로고·상표는 해당 회사의 사용 허락을 받은 범위에서 사용하세요.

## 저장 방식 — 서버 / 이 PC에만
상단 **저장: 서버** 버튼으로 고릅니다.

| 방식 | 환자 정보·사진·동영상 보관 위치 | 특징 |
|------|------|------|
| **서버에 저장** (기본) | 웹 서버(DB + 미디어 폴더) | 여러 PC에서 같은 기록. 무료 인터넷 서버는 재시작 때 지워질 수 있음 |
| **이 PC에만 저장** | 지금 PC 브라우저 저장소(IndexedDB) + 지정한 저장 폴더 | **인터넷 서버로 아무것도 보내지 않음**. 다른 PC에선 안 보임. 브라우저 사이트 데이터 삭제 시 지워지므로 **저장 폴더 지정 필수** |

- 배포할 때 `SLITLAMP_STORAGE=local` 로 두면 그 사이트는 항상 '이 PC에만 저장'으로 고정됩니다(`server` 로 두면 서버 고정).
- 두 방식의 기록은 서로 옮겨지지 않습니다.

## 사용 흐름
1. **신규 환자** 등록 → 환자 선택(선택해야 캡처 버튼 활성화)
2. **카메라 시작** → 권한 허용 → 라이브 영상
3. (선택) 상단 **저장 폴더 지정** → 한 번 권한 부여 시 이후 캡처가 그 폴더에도 동시 저장
4. 안구(OD/OS) 선택 → **사진 캡처** 또는 **녹화 시작/중지**
5. 우측 세로 썸네일(최신이 위)에서 클릭 → 크게 보기 / 다운로드

단축키: `Space`(일시정지) · `C`(사진) · `R`(녹화)

## 화면 디자인 (Clinical Graphite)
안과 영상 프로그램(VK-2, EyeSuite, IMAGEnet 등)처럼 **어두운 그래파이트 작업 공간**을 기본으로 해 영상에 시선이 모이게 했습니다(상단 테마 버튼으로 밝은 테마 전환).

- **상단바**: 브랜드 · **촬영 / Pro 검토** 전환 스위치 · 카메라·설정·테마
- **환자 배너**: 검색·선택, 이니셜 아바타, 차트번호, 성별·나이, 생년월일, **진단명**, 담당의
- **영상 HUD**: 영상 위에 환자 · 안구(OD 파랑 / OS 주황 / OU 보라) · LIVE / 정지 / REC 표시
- **촬영 도크**: OD/OS/OU 안구 스위치, 4분할 · 일시정지, 정지영상 · **셔터형 사진 캡처** · 녹화
- **썸네일**: 촬영일별 묶음, 안구 색 배지, 시각·코멘트 오버레이, 전체 / OD / OS / 동영상 필터

## Pro 모드 (전문가용 영상 검토)
상단 **촬영 / Pro 검토** 전환 스위치로 기본 촬영 화면과 전문가용 검토 화면을 전환합니다(기본 화면은 그대로 유지).
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
| **인쇄·PDF** | 브라우저 인쇄 창 → 'PDF로 저장'으로 A4 보고서: 제목·출력일시, 환자·진단명·담당의, 영상(1/2/4장 배치)·캡션, **소견란**, 확인자 서명·쪽번호 |

> 보정·편집 기능은 VK-2 Image Process(밝기·대비·감마·NEGA·채널·필터·측정)와 일반 세극등 영상 프로그램의 구성을 참고했습니다. 눈금 보정값은 브라우저(localStorage)에 저장됩니다.

> 진단명·담당의 컬럼은 기존 DB에도 실행 시 자동으로 추가됩니다(데이터 보존).

## 저장 위치
- 서버 DB: `web/data/slitlamp.db` (환경변수 `SLITLAMP_DB_PATH`로 변경)
- 서버 미디어: `web/data/media/<차트번호>_<환자ID>/<날짜>/...` (`SLITLAMP_MEDIA_DIR`)
- 지정 로컬 폴더: 브라우저에서 선택한 폴더 (동시 저장)

## API
- `GET/POST /api/v1/patients`, `GET/PUT/DELETE /api/v1/patients/{id}`
- `GET/POST /api/v1/captures`, `PATCH /api/v1/captures/{id}` (코멘트), `DELETE /api/v1/captures/{id}`
- `GET /media/...` 저장된 이미지/영상 제공

## 테스트
```bash
cd web
pip install -r requirements-dev.txt
pytest
```
환자 CRUD, 차트번호 중복, 캡처 업로드/조회/삭제, 환자 삭제 시 캡처 cascade, 미디어 제공을 검증합니다.

## 참고 — 브라우저 지원
- **Chrome / Edge**: 전 기능 (카메라 + mp4 녹화 + 지정 폴더 저장)
- **Firefox / Safari**: 카메라·녹화는 되나 `showDirectoryPicker` 미지원 → 지정 폴더 저장 비활성(서버 저장은 정상)
