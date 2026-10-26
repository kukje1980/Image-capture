# 장면 분류 학습 데이터 — 공개 데이터셋(1단계) → 병원 데이터(2단계)

앱의 에이전트는 "지금 화면이 어떤 조명·부위인가"를 7가지로 인식합니다.
라벨: `diffuse`(확산광 전안부) · `slit`(슬릿 단면) · `retro`(후방조명) · `fluorescein`(코발트블루 형광염색) ·
`ir_meibo`(적외선 마이봄샘) · `external`(외안부·안검) · `unusable`(깜빡임·암전·백화).

학습 입력은 **라벨별 폴더** 하나면 됩니다:
```
data/
  diffuse/*.jpg   slit/*.jpg   retro/*.jpg   fluorescein/*.jpg   ir_meibo/*.jpg   external/*.jpg   unusable/*.jpg
  unlabeled/      ← 아직 분류 안 한 것 (학습에서 제외)
```

## 1단계 — 인터넷 공개 데이터로 시작

모델 없이도 규칙 기반 인식이 돌아가므로, 공개 데이터는 **규칙을 넘어서는 첫 모델**을 만드는 용도입니다.
아래는 슬릿램프·전안부 사진이 있는 것으로 알려진 공개 출처입니다. 각 사이트의 라이선스(연구용/비상업 여부)를
반드시 확인하고, 다운로드 후 위 폴더 구조로 **직접 분류**해 넣으세요 (대부분 '질환' 라벨이지 '조명' 라벨이 아닙니다).

| 출처 | 찾는 방법 | 참고 |
|------|-----------|------|
| Kaggle | 검색어 `slit lamp`, `anterior segment`, `cataract slit lamp`, `keratitis`, `pterygium`, `meibomian` | `pip install kaggle` 후 `kaggle datasets download -d <소유자/이름>` |
| Figshare · Zenodo · Mendeley Data | 검색어 `slit-lamp images`, `anterior segment photographs`, `meibography` | 논문 부록 데이터가 많음 |
| 논문 공개 데이터 (GitHub) | `slit lamp dataset github` | 각막염·백내장 분류 논문의 데이터 링크 |
| Wikimedia Commons | 카테고리 `Slit lamp photographs` | CC 라이선스 확인 |

- 슬릿 단면(`slit`)·후방조명(`retro`)·형광염색(`fluorescein`) 은 사진을 보면 바로 구분됩니다.
- 확산광 전안부(`diffuse`) 가 가장 많고, 외안부(`external`) 는 눈꺼풀·피부가 보이는 저배율 사진입니다.
- 어두운/하얗게 날아간 사진은 `unusable` 에 넣으면 깜빡임·암전 인식이 좋아집니다. 없으면 `synth.py` 가 만든 것으로 보충.
- 각 라벨 **50~200장**이면 규칙보다 나은 첫 모델이 나옵니다 (교차검증 정확도가 출력됩니다).

```bash
python tools/agent_train/train_scene.py --data data            # → assets/models/scene_model.json
```
앱을 다시 켜면 이 모델을 씁니다 (설정 `agent_model_path` 로 다른 경로 지정 가능). 모델의 확신이 낮은 프레임은
자동으로 규칙 기반 결과를 씁니다.

## 2단계 — 병원 설치본의 데이터로 재학습

에이전트 에디션은 쓰는 동안 **라벨이 자동으로 쌓입니다**:
- 자동 촬영 / 수동 촬영 때의 장면 라벨 (`agent_events` 테이블 + JSONL 로그)
- 의사가 추천 프레임을 **선택**(저장) 하거나 **닫은** 기록 → "좋은 사진" 라벨
- 코멘트의 조명 태그(형광·마이봄 등)

앱 메뉴 **에이전트 → 학습 데이터 내보내기** 를 누르면 위와 같은 라벨 폴더(환자 정보 없음, 파일명은 내용 해시)와
`manifest.csv`(라벨·눈·품질 점수·라벨 출처)가 만들어집니다. 공개 데이터와 합쳐 다시 학습합니다:
```bash
python tools/agent_train/train_scene.py --data data --data "C:\내보낸폴더"
```
`unlabeled/` 에 들어간 사진을 손으로 분류해 옮기면 그만큼 정확도가 오릅니다.

## 3단계 — CNN (수천 장 이상)
`train_cnn_onnx.py` 로 MobileNetV3 를 학습해 `assets/models/scene_model.onnx` 를 만들면, `onnxruntime` 이 설치된
앱에서 CNN 을 우선 씁니다. 이때도 품질(초점·노출) 판단은 기존 Smart Capture 가 맡고 CNN 은 장면만 맡습니다.

## 합성 데이터로 파이프라인만 확인
```bash
python tools/agent_train/synth.py /tmp/synth --per-class 60
python tools/agent_train/train_scene.py --data /tmp/synth --out /tmp/scene_model.json
```
실제 사진이 아니므로 이 모델을 배포에 쓰지는 마세요.
