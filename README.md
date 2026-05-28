# 슬릿램프 디지털 영상 시스템 (Slit-Lamp Imaging)

안과 슬릿램프(세극등 현미경)에 연결된 **HDMI 캡처 장비(UVC 웹캠으로 인식, 예: 에버미디어)** 의
실시간 영상을 받아 **사진 캡처 · 일시정지 · 동영상(mp4) 녹화**를 하고, 각 영상물을
**환자 데이터베이스에 연결 저장**함과 동시에 **지정한 폴더에도 저장**하는 진료실용
네이티브 데스크탑 앱입니다. 단일 PC에서 오프라인으로 동작합니다.

- 화면 좌측: 실시간 영상 + 컨트롤(안구 선택 / 일시정지 / 사진 캡처 / 녹화)
- 화면 우측: 선택한 환자의 캡처 사진을 작은 썸네일 세로줄로(최신이 위) 표시, 클릭 시 크게 보기
- 상단: 환자 검색/선택/신규/수정

## 기술 스택
- Python 3.11+, **PySide6**(Qt6), **OpenCV**(opencv-python), **SQLite**(stdlib)
- 동영상: **imageio-ffmpeg**(번들 ffmpeg, H.264/yuv420p) 우선, 실패 시 `cv2.VideoWriter(mp4v)` 폴백
- 대상 OS: **Windows**(캡처는 DirectShow 백엔드). 개발/CI는 Linux에서 합성·파일 소스로 가능

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

## 설정 / 저장 위치
설정 파일과 기본 데이터는 사용자 앱데이터 폴더에 저장됩니다.
- Windows: `%APPDATA%\SlitLampImaging\`
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

## 테스트
```bash
QT_QPA_PLATFORM=offscreen pytest
```
DB CRUD/FK, 설정 저장, 프레임 변환/썸네일, 캡처 3중 저장(기본·export·DB), 짧은 동영상 녹화를 검증합니다.

## Windows 패키징
```bash
pyinstaller build.spec
# 결과: dist/SlitLampImaging/SlitLampImaging.exe
```
번들 ffmpeg와 Qt 플러그인이 함께 포함됩니다.

## 실제 장비 검증(사용자 Windows PC 필수)
1. 슬릿램프 HDMI → 캡처 장비 → PC. 장치가 UVC 웹캠으로 인식되는지 확인
2. 설정에서 카메라 인덱스 선택 → 라이브 영상 확인(1080p)
3. 일시정지 / 사진 캡처(파일+export+DB+썸네일) / mp4 녹화 및 재생 확인
4. 장치 분리/재연결, 정상 종료 후 재오픈(카메라 잠김 없음) 확인
