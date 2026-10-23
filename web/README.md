# 슬릿램프 영상 시스템 — 웹앱

안과 슬릿램프 HDMI 캡처 장비(브라우저에서 UVC 웹캠으로 인식)의 실시간 영상을 받아
**사진 캡처 · 일시정지 · 동영상 녹화**를 하고, 각 영상물을 **환자 DB + 서버 미디어 폴더에 저장**함과
**동시에 브라우저가 지정한 로컬 폴더에도 저장**하는 웹 애플리케이션입니다.

클리닉 PC에서 로컬 서버(uvicorn)로 실행하며, 브라우저(Chrome/Edge 권장)로 `localhost` 접속해 사용합니다.
동일 시스템의 **Windows 네이티브 데스크탑 앱**은 이 저장소 상위 폴더(`../app`)에 별도로 있습니다.

## 기술 스택
- **FastAPI** + **Jinja2** + **바닐라 JS** (빌드 도구 없음)
- **SQLite** (stdlib), **uvicorn**
- 캡처: 브라우저 `getUserMedia`, 사진 `canvas.toBlob`, 동영상 `MediaRecorder`(mp4 우선/webm 폴백)
- 지정 폴더 저장: **File System Access API** (`showDirectoryPicker`, Chrome/Edge)

## 설치 & 실행

### 원클릭 실행 (권장)
- **Windows**: `web\run_web.bat` 더블클릭 → 최초 1회 자동 설치 후 서버 시작 + 브라우저 자동 열림
- **macOS/Linux**: `./web/run_web.sh`

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

## 사용 흐름
1. **신규 환자** 등록 → 환자 선택(선택해야 캡처 버튼 활성화)
2. **카메라 시작** → 권한 허용 → 라이브 영상
3. (선택) 상단 **저장 폴더 지정** → 한 번 권한 부여 시 이후 캡처가 그 폴더에도 동시 저장
4. 안구(OD/OS) 선택 → **사진 캡처** 또는 **녹화 시작/중지**
5. 우측 세로 썸네일(최신이 위)에서 클릭 → 크게 보기 / 다운로드

단축키: `Space`(일시정지) · `C`(사진) · `R`(녹화)

## 저장 위치
- 서버 DB: `web/data/slitlamp.db` (환경변수 `SLITLAMP_DB_PATH`로 변경)
- 서버 미디어: `web/data/media/<차트번호>_<환자ID>/<날짜>/...` (`SLITLAMP_MEDIA_DIR`)
- 지정 로컬 폴더: 브라우저에서 선택한 폴더 (동시 저장)

## API
- `GET/POST /api/v1/patients`, `GET/PUT/DELETE /api/v1/patients/{id}`
- `GET/POST /api/v1/captures`, `DELETE /api/v1/captures/{id}`
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
