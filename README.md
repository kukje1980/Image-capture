# 안저 사진 뷰어 (Fundus Viewer)

Windows 10 / 11용 안저카메라 전용 뷰어입니다. **감시 폴더에 사진 파일이 떨어지면** 파일에서
환자 ID·이름 등 환자 정보를 추출해 뷰어 데이터베이스로 가져오고, 2D로 보거나 **광각 사진을
실제 안구처럼 입체(3D) 모델**로 돌려 볼 수 있습니다.

우선 회사 초광각 모델 **SYSEYE RetiCam 3100 Plus (1회 176° · 몽타주 220°)** 에 맞춰
만들었고, **Microclear APOLLO (WA 135° / UWA 165°)**, **Kowa VK-2 / VK-2s** (nonmyd·VX
시리즈) 출력과 일반 안저카메라 파일도 읽습니다.

| 2D 보기 | 3D 안구 — 절개 보기 |
|---|---|
| ![main](docs/main_2d.jpg) | ![3d](docs/3d_outside.jpg) |
| **3D 안구 — 닫힌 안구** | **3D 안구 — 내부(망막 시점)** |
| ![closed](docs/3d_closed.jpg) | ![inside](docs/3d_inside.jpg) |

> 화면의 사진과 환자는 모두 `fundusview/demo.py`가 만든 **합성(가상) 데이터**입니다.

## 빠른 시작

```bat
pip install -r requirements.txt
python run_viewer.py --demo
```

`--demo`는 빈 라이브러리에 가상 환자 사진(RetiCam·APOLLO·VK-2·DICOM 형식)을 넣어 바로 써 볼
수 있게 합니다. `--home D:\FundusViewer`를 주면 설정과 라이브러리를 그 폴더 하나에 둡니다(휴대용).

**설치 파일(exe) 만들기:** `build_windows.bat` 실행 → `dist\FundusViewer\FundusViewer.exe`
(폴더째 복사해 사용). GitHub Actions(`fundus-viewer` 워크플로)도 Windows exe를 빌드해
아티팩트로 올립니다.

## 사용 흐름

1. **설정 → 감시 폴더 → 폴더 추가**: 장비가 사진을 저장하는 폴더를 등록하고 카메라 프로필을
   고릅니다 (자동 감지 가능).
2. **▶ 폴더 감시 시작** (다음부터는 시작 시 자동). 새 파일은 쓰기가 끝날 때까지 기다린 뒤
   가져옵니다. 감시가 꺼져 있던 동안 들어온 파일도 시작할 때 찾아냅니다.
3. 왼쪽 환자 목록 → 썸네일 → **2D 보기 / 3D 안구 / 비교** 탭.
4. 환자 ID를 찾지 못한 사진은 **★ 미분류**로 들어갑니다. 사진을 고르고 **환자 지정/수정…**
   에서 환자를 지정합니다. 잘못된 환자로 잘못 들어가는 것보다 미분류가 안전하므로 추측하지
   않습니다.

창에 파일·폴더를 끌어다 놓아도 가져오며, 같은 내용의 파일(SHA-256)은 한 번만 들어갑니다.

| 장비 | 감시할 폴더 | 읽는 정보 |
|---|---|---|
| **SYSEYE RetiCam 3100 Plus** | 장비 PC의 저장 폴더, 예: `D:\reticam`(장비 PC에 설치) 또는 네트워크 공유 `\\<장비 IP>\D\reticam`(**폴링** 체크) | JPEG 안 APP15 JSON(`patientID`, `patientName`/`patientLastName`+`patientFirstName`, `patientBornDate`, `patientSex`, `eyeLaterality`, `modeID`, 몽타주 여부), 파일 이름 `<이름>-od-color-YYYYMMDD-HHMMSS-mmm` |
| **Microclear APOLLO** | 장비 공유 폴더 `…\PatientCapture` (SMB, **폴링** 체크) 또는 PC 뷰어 `MicroClearClient\ImageData` | 폴더 `<ID>_<이름>`, JPEG 주석 `Description:{JSON}`(검사 시각·Eye·FieldAngle·DevModel·ImgType), 케이스 내보내기 `<ID>.json`(생년월일·성별) |
| **Kowa VK-2 / VK-2s** | Kowa Export Tool 출력 폴더, VK-2 DICOM 로컬 저장 폴더 | 파일명 `ID_YYYYMMDD_HHMMSS_R_FUNDUS (COLOR)_1` (VK EXPORT / MDR / JOIA 형식), JOIA `.xml`, DICOM 태그 |
| VK-2 "폴더로 복사" | 그 폴더 (프로필: *파일명 = 환자 ID*) | 파일 이름 = 환자 ID |
| 기타 카메라 | 저장 폴더 | DICOM, EXIF/XMP/JPEG 주석, 같은 이름의 `.txt/.ini/.xml/.json/.csv`, 일반 파일명 규칙 |

**RetiCam 참고**
* 장비의 기본 환자(`#AnonymousID#` / Anonymous / 1980-01-01)로 찍은 사진은 등록되지 않은
  환자이므로 **미분류**로 들어옵니다.
* 촬영 시각은 파일 이름의 시각을 씁니다. JSON의 `dateTime`은 시간대만큼 몇 시간 어긋난 경우가
  있습니다.
* 확장자가 `.jpg`인데 내용이 TIFF인 내보내기 파일도 읽습니다(TIFF 태그에서 JSON을 찾음).
* VK-2와 연동해 "파일 이름 앞 6자리 = 환자 ID"로 내보내도록 설정한 병원은 **설정 → 파일명
  규칙**에 `^(?P<pid>\d{6})`을 추가하세요.
* 사진 왼쪽 위에 이름·ID가 글자로 찍혀 있습니다(장비가 넣는 것). 3D에서는 촬영 원 밖이라
  보이지 않습니다.

VK-2 원본 저장소(`vk_3x\-000512\vk000005.jpg`)의 파일은 이름에 환자 정보가 없어
(환자 연결은 `vk3x.mde` DB에만 있음) **미분류**로 들어옵니다. VK-2 사진은 Export Tool 또는
DICOM 내보내기 폴더를 감시하세요.

### 환자 정보 추출 순서

앞선 출처가 채운 값은 뒤에서 바꾸지 않습니다. 각 값의 출처는 오른쪽 "영상 정보"에 표시됩니다.

1. **DICOM 태그**: PatientID, PatientName(한글 이름 그룹 우선; `Specific Character Set`이 없는
   VK-2 파일은 CP949 / ISO 2022 이스케이프를 직접 해석), BirthDate, Sex, Acquisition/Content
   Date·Time, Image Laterality(0020,0062)→Laterality(0020,0060), Horizontal FOV(0022,000C)
2. **장비 데이터**: RetiCam APP15 JSON, APOLLO 폴더·JSON (`Eye` 1=OD 0=OS, `FieldAngle`
   60/90/112 → 90/135/165°)
3. **부속 파일**(sidecar): JOIA XML의 `ID / LastName / FirstName / DOB / Sex / ImageLaterality` 등
4. **이미지 내장 텍스트**: EXIF(Make/Model, DateTimeOriginal, UserComment, Windows XP 태그),
   JPEG 주석, PNG 텍스트, XMP에서 `PatientID=…; Name: …` 형태의 키·값
5. **파일·폴더 이름**: 프로필 규칙 → 사용자 규칙(설정 → 파일명 규칙, 정규식, 즉석 시험 가능)
   → 일반 규칙(`ID_이름_YYYYMMDD_OD`, `12345678_홍길동` …) → 상위 폴더(`12345_홍길동\20240305\`)
6. 그래도 없으면: 화각은 프로필 기본값, 검사일은 파일 시각, 눈은 시신경 유두 위치로 추정
   (OD는 유두가 오른쪽)

이미 등록된 환자의 이름·생년월일은 가져오기로 덮어쓰지 않습니다(빈 칸만 채움).

## 3D 안구 모델

반지름 1(≈12 mm)인 구를 안구로 봅니다. 사진은 메시에 붙이지 않고 프래그먼트 셰이더가
망막 표면의 점마다 **안구 중심에서 잰 후극으로부터의 각도 θ**와 방위각 φ를 구해 사진에서 색을
찾습니다. 그래서 화각·투영·회전을 바꾸면 바로 반영되고 확대해도 정확합니다.

* **화각 기준**: 광각 장비는 안구 중심각(내부각)으로, 일반 안저카메라(45°/50°)는 동공에서 잰
  외부각으로 표시합니다. 변환은 동공(절점) 위치 `d = 0.58`(안구 반지름 단위)인 원근 모델로 하며,
  이 값은 "내부 200° ≈ 외부 135°" 관례와 맞습니다. Microclear 규칙(외부각 × 1.5 = 안구 중심각)과도
  일치합니다.
* **투영**: 카메라마다 다음을 기본으로 씁니다. 스테레오그래픽과 정사영도 고를 수 있습니다.
  * **RetiCam 3100 Plus**: **광각 보정(중심 확대)**. 식은 `θ = θmax·((1−c)·ρ + c·ρ³)`,
    `c = 0.2545`, `θmax = 88°`입니다. 같은 176°라도 등거리로 펴면 실제 사진에서 시신경 유두
    (중심에서 영상 반경의 0.32)가 중심와에서 28°에 놓여, 해부학적 위치(약 22°)와 맞지 않습니다.
    이 식은 유두가 22°에 오도록 중심부를 확대합니다. 몽타주는 220°로 둡니다. 2023년형 50°급
    RetiCam 파일은 일반 카메라 원근으로 처리합니다.
  * **APOLLO**(SLO 스캔): 스캔각이 영상 반경에 비례하므로 **등거리(각도 비례)**를 씁니다.
  * **일반 카메라**: **카메라 원근(동공 시점)**, 즉 `tan α = sin θ / (cos θ + d)`를 씁니다.
  검증: 공급사 UWA 샘플에서 유두가 중심에서 약 250 px(반경 1023 px) 떨어져 있고, 등거리 165°로
  바꾸면 약 20°입니다. 이는 해부학적 중심와–유두 거리(약 4.5 mm / 12 mm)와 일치합니다.
* **외부 모드**: 공막·각막·홍채와 시신경을 그립니다. 시신경은 검출된(또는 2D 화면에서 우클릭으로
  지정한) 유두 뒤에 붙습니다. "앞쪽 절개" 슬라이더로 앞부분을 잘라 안쪽 망막을 봅니다.
  오른쪽 끝(100)으로 밀면 닫힌 안구가 됩니다.
* **내부 모드**: 안구 안에서 망막을 바라봅니다. 드래그로 시선 이동, 휠로 시야를 넓히거나 좁힙니다.
* **각도 격자**: 후극에서 10°마다 링을 그립니다(30°마다 진하게).
* 사진 밖의 망막은 맥락막 색으로 채웁니다. 45° 사진은 망막의 작은 부분만, UWA 165° 사진은
  대부분을 덮는 것이 정상입니다.
* "화각·투영 저장"을 누르면 그 영상의 매핑 값을 DB에 저장합니다.

3D는 OpenGL 2.1이 필요합니다. 그래픽 드라이버가 오래된 PC에서는 **설정 → 일반 → 3D 렌더링 →
소프트웨어 렌더링**을 고르고 다시 시작합니다(PySide6에 포함된 Mesa `opengl32sw.dll` 사용).

## 구조

```
fundusview/
  app.py            진입점 (OpenGL 모드, 스타일, --demo / --home)
  config.py         설정 JSON (%APPDATA%\FundusViewer\settings.json)
  db.py             SQLite: patients / images / seen_files / import_log
  profiles.py       카메라 프로필 (RetiCam, APOLLO, VK-2, VK-2 ID 폴더, 일반)
  extract/          메타데이터 추출 (dicom / reticam / apollo / embedded+sidecar / filename / normalize)
  importer.py       안정화 대기 → 중복 검사 → 추출 → 분석 → 라이브러리 저장 → DB
  watcher.py        watchdog 감시(또는 폴링) + 재검사 + 가져오기 작업 스레드
  imaging.py        영상 읽기(DICOM 포함), 촬영 원·시신경 검출, 표시 조정(LUT)
  projection.py     안구 기하 (θ↔영상 반경, 내부각↔외부각) — 셰이더와 동일한 식
  demo.py           합성 안저 사진 + 장비별 형식 데모 폴더
  ui/               main_window, eye3d(OpenGL), image_view, dialogs, style.qss
tests/              pytest (추출·투영·영상·가져오기·감시·GUI)
```

라이브러리 폴더(기본: `문서\FundusViewerLibrary`)에는 `fundus.db`, `images\<환자ID>\<검사일>\`
사본, `thumbs\`, `display\`(DICOM을 PNG로 바꾼 사본)가 들어갑니다. 처리 방식은 폴더마다
**복사**(기본, 원본 유지) / 이동 / 원본 위치 참조 중에서 고릅니다. 장비 공유 폴더는 반드시 복사나
참조로 두세요.

## 테스트

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q tests
```

## 알려진 한계와 다음 단계

* **RetiCam 투영 보정은 잠정값**입니다. 근거는 몽타주 샘플 한 장의 측정과 해부학적 유두 위치뿐입니다.
  보정을 확정하려면 둘 중 하나가 필요합니다.
  * SYSEYE에서 투영·왜곡 자료나 DICOM 적합성 문서를 받기
  * 격자 시험판을 찍은 사진으로 맞추기
  그때까지 3D 화면에서 투영을 "등거리"로 바꿔 비교할 수 있고, 영상별 "화각·투영 저장"도 됩니다.
  주변부 고정 촬영(fixation) 사진의 회전 정보는 아직 쓰지 않습니다.
* **VK-2 원본 DB 연동**: `vk3x.mde`(Access) 스키마가 문서화되어 있지 않아, 원본 저장소
  사진의 환자 연결은 아직 하지 않습니다. 샘플 `.mde`로 테이블 구조를 확인한 뒤 읽기 전용
  커넥터를 추가할 수 있습니다. VK-2 전용 무손실 형식 `.dlt`는 읽지 못합니다.
* **APOLLO 단일 모드 파일**(IR / RF / FFA / AF / ICGA+FFA)의 JSON에는 환자 경로가 없습니다. 이런
  파일은 `PatientCapture\<ID>_<이름>` 폴더 구조에서 환자를 찾습니다. ICGA 단독의 `ImgType` 값은 아직
  확인하지 못했습니다. PNG 내보내기의 바이너리 헤더는 SKY 샘플 하나로만 확인했습니다.
* 3D 매핑은 1차 광학 모델입니다(카메라 왜곡과 안축장 차이는 반영하지 않음). 측정·진단용이 아닌
  시각화 용도입니다.
* 이 뷰어는 의료기기 인증을 받은 소프트웨어가 아닙니다. DB에는 환자 이름이 저장되므로 PC 접근
  권한을 관리하세요.
