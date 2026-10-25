# 샘플 사진 수집 목록 — 기능별 필요 사진 · 질환 · 출처

Pro **분석/측정** 기능(`app/analysis/clinical.py`, `app/capture/cataract.py`, `app/analysis/tbut.py`,
`app/capture/analysis.py` — v1.7.0 통합 브랜치 `claude/quirky-feynman-yq854y`)의 기준값은 **합성 영상으로 잡은 초기값**이라,
코드 주석대로 **실제 슬릿램프 사진 약 30장(기능별)** 으로 확인·보정해야 합니다. 이 문서는 그 사진이 무엇이어야 하는지,
어떤 질환·등급이 필요한지, 어디서 구할 수 있는지를 정리한 것입니다.

- 수집 체크리스트(엑셀로 열 수 있음): [`sample_images/sample_photo_list.csv`](../sample_images/sample_photo_list.csv)
- 올릴 폴더: `sample_images/<번호_기능>/` (아래 표의 폴더 이름)
- 파일 이름 규칙: `<질환>_<등급>_<출처>_<번호>.jpg` — 예) `spk_oxford2_sustech_001.jpg`, `nuclear_nc4_mendeley_012.jpg`

> ⚠️ **라이선스 · 개인정보** — 외부 사진은 라이선스별로 쓸 수 있는 범위가 다릅니다(맨 아래 표).
> **CC BY-NC / NC-ND(비영리)** 사진은 *내부 테스트·보정용*으로만 쓰고, 설치파일·웹 데모·홍보물에 넣지 마세요.
> 자체 진료실 사진은 환자 동의 + 이름·차트번호가 없는 상태로(EXIF 포함) 올리세요. 저장소가 공개로 바뀔 수 있다면
> 사진 자체는 저장소 대신 Google Drive 등에 두고 이 목록만 저장소에 두는 것을 권장합니다.

---

## 한눈에 보기

| # | 폴더 | 쓰이는 기능 | 조명 | 필요한 사진(질환 · 등급) | 목표 수량 | 주요 출처 |
|:-:|------|------------|------|-------------------------|:--------:|-----------|
| 1 | `01_fluorescein` | 형광염색 면적 · Oxford 등급 근사 | 코발트블루 + 황색 필터 | 정상(염색 없음) · 건성안 점상각막염(SPK) Oxford 0~V · 각막찰과상 · 각막궤양 · 헤르페스 수지상궤양 | 30+ | SUSTech-SYSU, Wikimedia Commons |
| 2 | `02_hyperemia` | 결막 충혈 지수 · 참고 등급 0~4 | 디퓨즈(백색광) | 정상 · 경도~중증 충혈(알레르기/세균/바이러스 결막염, 건성안) · *대조군:* 결막하출혈 | 30+ | Commons, SLID, Efron 척도(참고) |
| 3 | `03_meibography` | 샘 면적 · 탈락 % · Meiboscore(Arita 0~3) | 적외선(IR) | 정상 · MGD Meiboscore 0/1/2/3 · 상안검/하안검 | 30+ | CAMG(Figshare), MGD-1K(요청) |
| 4 | `04_cataract_nuclear` | 핵 혼탁 지수 · LOCS III 입력 | 슬릿 광학 절편(45°) | 투명 수정체 · 핵경화 NO/NC 1~6 | 30+ | Mendeley 핵백내장 DB, Commons |
| 5 | `05_cataract_retro` | 피질 혼탁 지수 · 동공 직경 | 역조명(산동) | 투명 · 피질 백내장 · 후낭하 백내장(PSC) · 산동 부족(<5 mm) 예시 | 20+ | Commons(소수), **자체 촬영 권장** |
| 6 | `06_tbut_video` | TBUT 동영상 분석 | 코발트블루 동영상 | 정상(>10 s) · 경계(5~10 s) · 건성안(<5 s), 깜빡임 포함 10~20초 | 10+ 편 | **자체 촬영 필수**(공개 형광 동영상 없음) |
| 7 | `07_quality_illumination` | 영상 품질 · 조명 모드 태그 · Smart Capture | 디퓨즈/슬릿/코발트/IR | 정상 선명 · 흐림 · 반사광 · 노출 부족/과다 · 눈꺼풀 가림 · 깜빡임 | 30+ | **자체 장비 촬영 권장**, SLID |
| 8 | `08_anterior_misc` | 데모 환자·진단명 예시, 비교/정렬 | 디퓨즈/슬릿 | 익상편 · 검열반 · 결막하출혈 · 결막 색소모반 · 결막낭종 | 각 3~5 | SLID, Commons |

---

## 1. 형광염색 (각막 손상) — `01_fluorescein`
**기능:** 녹황색 형광 화소 면적(mm²)·비율, 병변 수, Oxford 등급 근사(점 개수 0 / I 1~5 / II 6~15 / III 16~30 / IV 31~100 / V >100).

| 질환 · 소견 | 필요 등급/수량 | 확인할 점 |
|------------|----------------|-----------|
| 정상(염색 없음) | 5 | 오탐(위양성) 없는지 |
| 건성안 점상각막염(SPK) | Oxford 0~V 각 3~5 | 점 개수 → 등급 구간이 의사 판정과 맞는지 |
| 각막찰과상 | 3~5 | 큰 단일 병변 면적 |
| 세균성 각막궤양(편상) | 3~5 | 면적·가장 큰 병변 |
| 헤르페스 수지상궤양 | 2~3 | 가지 모양 병변을 여러 점으로 세지 않는지 |

**출처**
- **SUSTech-SYSU 각막궤양 데이터셋** — 형광염색 슬릿램프 712장, 점상/점편상/편상 패턴·중증도 라벨 + 분할 마스크
  ([논문 Sci Data 2020](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6971241/), [Figshare 메타데이터](https://figshare.com/articles/dataset/Metadata_record_for_The_SUSTech-SYSU_dataset_for_automatically_segmenting_and_classifying_corneal_ulcers/11371803/2)) — *라이선스 확인 필요*
- Wikimedia Commons: [Corneal Abrasion with Fluorescein Staining](https://commons.wikimedia.org/wiki/File:Corneal_Abrasion_with_Fluorescein_Staining.jpg) (CC BY-SA, James Heilman MD) ·
  [Dendritic corneal ulcer](https://commons.wikimedia.org/wiki/File:Dendritic_corneal_ulcer.jpg) ·
  [Category: Corneal ulcer](https://commons.wikimedia.org/wiki/Category:Corneal_ulcer) ·
  [Category: Corneal abrasion](https://commons.wikimedia.org/wiki/Category:Corneal_abrasion) ·
  [Category: Fluorescein](https://commons.wikimedia.org/wiki/Category:Fluorescein)
- [Infectious Keratitis Dataset (Multimodal Slit-Lamp, Figshare)](https://figshare.com/articles/figure/Infectious_Keratitis_Dataset_Based_on_Multimodal_Slit-Lamp_Images/28578860) — 감염성 각막염, *라이선스 확인 필요*
- ⚠️ Oxford 등급이 달린 **건성안 SPK 공개 데이터셋은 찾지 못함** → 자체 촬영 + 의사 Oxford 판정을 같이 기록하는 것이 가장 확실

## 2. 결막 충혈 — `02_hyperemia`
**기능:** 혈관 면적 %, 붉은기 지수 (R−G)/(R+G), 참고 등급 0~4 (경계 3 / 7 / 12 / 20 %).

| 질환 · 소견 | 필요 수량 | 확인할 점 |
|------------|----------|-----------|
| 정상 결막 (등급 0) | 5 | 기준선 |
| 경도~중증 충혈 (등급 1~4) | 각 5 | 등급 경계값이 Efron/CCLRU 판정과 맞는지 |
| 알레르기 / 세균 / 바이러스 결막염 | 섞어서 위 등급에 포함 | |
| *대조군:* 결막하출혈 | 3 | 출혈(면 형태)을 혈관 충혈로 과대평가하지 않는지 |

**출처**
- Wikimedia Commons: [Category: Conjunctivitis (35장)](https://commons.wikimedia.org/wiki/Category:Conjunctivitis) ·
  [ConjunctivitisRedEye.jpg](https://commons.wikimedia.org/wiki/File:ConjunctivitisRedEye.jpg) (CC BY-SA 2.0) ·
  [An eye with viral conjunctivitis](https://commons.wikimedia.org/wiki/File:An_eye_with_viral_conjunctivitis.jpg) ·
  [Chlamydial conjunctivitis](https://commons.wikimedia.org/wiki/File:Chlamydial-conjunctivitis.jpg) ·
  [Adenoviral conjunctivitis](https://commons.wikimedia.org/wiki/File:Adenoviral_conjunctivitis.png) ·
  [Category: Allergic conjunctivitis](https://commons.wikimedia.org/wiki/Category:Allergic_conjunctivitis) ·
  [Redeye photograph (결막하출혈)](https://commons.wikimedia.org/wiki/File:Redeye_photograph.JPG)
- **SLID** (아래 8번) — conjunctival injection, subconjunctival hemorrhage 클래스 포함
- [Mendeley 안질환 이미지(결막염·백내장·포도막염 등)](https://data.mendeley.com/datasets/n9zp473wfw) — 인터넷 수집 사진이라 *라이선스 개별 확인 필요*
- EyeRounds Atlas: [Allergic conjunctivitis](https://webeye.ophth.uiowa.edu/eyeforum/atlas/pages/allergic-conjunctivitis.html) (CC BY-NC-ND 3.0 → 내부 참고용)
- 등급 기준 참고(사진 배포 불가, 보기만): [Efron Grading Scale — CooperVision](https://coopervision.com/practitioner/tools-and-calculators/efron-grading-scale)
- ⚠️ 등급 라벨이 달린 공개 충혈 데이터셋은 없음 → 자체 사진에 의사 Efron 등급을 같이 기록

## 3. 마이봄샘 (IR meibography) — `03_meibography`
**기능:** 샘 면적 %, 탈락(dropout) %, Meiboscore(Arita: 0 / 1 <1/3 / 2 = 1/3~2/3 / 3 >2/3). **IR 영상 전용.**

| 소견 | 필요 수량 | 확인할 점 |
|------|----------|-----------|
| 정상 (Meiboscore 0) | 상·하안검 각 3 | |
| MGD Meiboscore 1 / 2 / 3 | 각 5 | 탈락 % 경계(10 / 33 / 67 %) |
| 반사광 많은 영상 | 3 | 반사를 샘으로 잘못 세지 않는지 |

**출처**
- **CAMG (Children and Adolescents Meibomian Gland)** — IR 상안검 1,114장, 분할 라벨·정량값 포함, 공개
  ([Figshare](https://figshare.com/articles/dataset/Children_and_Adolescents_Meibomian_Gland_CAMG_dataset/27601101), [논문](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12590672/)) — 소아라 **대부분 정상~경도**
- **MGD-1K** — LipiView II IR 1,000장(상 467 / 하 533), 샘·눈꺼풀 마스크 + Meiboscore, 여의도성모·고대안산병원
  ([arXiv 2205.15543](https://arxiv.org/pdf/2205.15543)) — 공개 다운로드 미확인 → 저자에게 요청. **성인 MGD 탈락 사진은 여기가 적합**
- ⚠️ 우리 장비는 NIR 광학계가 아직 없음(ROADMAP 22). 다른 장비(Keratograph 등) IR 사진으로 먼저 알고리즘만 검증

## 4. 백내장 — 핵 혼탁 (슬릿 광학 절편) — `04_cataract_nuclear`
**기능:** 각막 띠 대비 수정체 띠 밝기 비 → 핵 혼탁 지수 0~100, LOCS III(NO/NC) 의사 입력.

| 소견 | 필요 수량 | 확인할 점 |
|------|----------|-----------|
| 투명 수정체 (젊은 성인) | 5 | 지수 ≈ 0 근처인지 (RATIO_CLEAR 0.12) |
| 핵경화 NO/NC 1~6 | 각 4~5 | 지수가 등급 순서대로 증가하는지, RATIO_DENSE 0.95 적정성 |
| 성숙 백내장 | 2~3 | 상한 포화 |
| 각막 띠가 안 보이는 사진 | 2 | '절대 밝기 참고값' 경로 |

**출처**
- **Nuclear Cataract Database (Mendeley Data)** — Topcon DC-3 슬릿램프 1,437장, **LOCS III 등급 라벨**, 멕시코 Conde Valenciana 연구소
  ([Mendeley 6wv33nbcvv](https://data.mendeley.com/datasets/6wv33nbcvv)) — *라이선스 확인 필요*. **이 기능에 가장 적합**
- Wikimedia Commons: [Slit lamp view of Cataract in Human Eye](https://commons.wikimedia.org/wiki/File:Slit_lamp_view_of_Cataract_in_Human_Eye.png) (CC BY-SA 2.5) ·
  [Category: Human cataracts](https://commons.wikimedia.org/wiki/Category:Human_cataracts)
- EyeRounds Atlas: [Mature cataract](https://webeye.ophth.uiowa.edu/eyeforum/atlas/pages/Mature-Cataract-2.html) (CC BY-NC-ND)
- CatScreen (IIT Jodhpur, 슬릿램프 백내장 아형·중증도) — [소개](https://mlanthology.org/tmlr/2026/khurshid2026tmlr-catscreen/), 사용 동의서 필요

## 5. 백내장 — 피질 · 후낭하 (역조명) — `05_cataract_retro`
**기능:** 동공(붉은 반사) 안 어두운 얼룩 면적 % → 피질 혼탁 지수, 동공 직경(5 mm 미만이면 '산동 부족').

| 소견 | 필요 수량 |
|------|----------|
| 투명 (균일한 붉은 반사) | 5 |
| 피질 백내장 (바퀴살 모양) | 5~8 |
| 후낭하 백내장(PSC) | 5 |
| 산동 부족(동공 <5 mm) | 3 |

**출처**
- Wikimedia Commons: [Retro-illumination.jpg](https://commons.wikimedia.org/wiki/File:Retro-illumination.jpg) ·
  [Posterior Subcapsular Cataract.jpg](https://commons.wikimedia.org/wiki/File:Posterior_Subcapsular_Cataract.jpg)
- ⚠️ 역조명 공개 데이터셋(ACHIKO-Retro 등)은 비공개 → **자체 촬영 권장** (산동 후, 동일 배율)

## 6. TBUT 동영상 — `06_tbut_video`
**기능:** 형광 동영상에서 마지막 깜빡임 → 첫 건조 반점까지 시간(분석 영역: 중앙 50%).

| 소견 | 필요 수량 | 촬영 조건 |
|------|----------|-----------|
| 정상 TBUT >10 s | 3~4편 | 코발트블루+황색 필터, 플루오레세인 점안 후 깜빡임 2~3회 포함 15~20초 |
| 경계 5~10 s | 3편 | 같은 배율·조명 |
| 건성안 <5 s | 3~4편 | 의사가 스톱워치로 잰 TBUT 값을 파일명/CSV 에 기록 |

**출처**
- ⚠️ **공개 형광 TBUT 동영상 데이터셋 없음** → 자체 녹화 필수
- 참고: [TFM Dataset (arXiv 2510.05615)](https://arxiv.org/pdf/2510.05615) — 15편, *플라시도 링* 동영상이라 형광 분석과 조건이 다름

## 7. 영상 품질 · 조명 모드 · Smart Capture — `07_quality_illumination`
**기능:** 선명도(Tenengrad)·노출·반사광 판정, 조명 모드 태그(디퓨즈/슬릿/코발트/IR), Smart Freeze 기준값(ROADMAP 15).

| 종류 | 필요 수량 |
|------|----------|
| 선명한 정상 사진 — 디퓨즈 / 슬릿 / 코발트블루 / IR 각각 | 각 5 |
| 초점 흐림 | 5 |
| 반사광 과다 | 5 |
| 노출 부족 / 과다 | 각 3 |
| 눈꺼풀·속눈썹 가림, 깜빡임 순간 | 각 3 |
| 초점 맞추는 과정 동영상(흐림→선명→흐림) | 3~5편 |

**출처:** 우리 장비(슬릿램프 + 캡처보드/소니 카메라)의 해상도·색감이 기준값에 직접 영향을 주므로 **자체 촬영 권장**.
정상 슬릿 사진 비교용으로 SLID 사용 가능.

## 8. 기타 전안부 질환 (데모 · 진단명 예시) — `08_anterior_misc`
환자 DB 데모, Pro 비교/정렬, 보고서 예시용.

| 질환 | 수량 |
|------|------|
| 익상편 (pterygium) | 3~5 |
| 검열반 (pinguecula) | 3~5 |
| 결막하출혈 | 3~5 |
| 결막 색소모반 | 3 |
| 결막낭종 | 3 |

**출처**
- **SLID (Slit-Lamp Image Dataset)** — 저장대 부속 제2병원, 슬릿램프 2,617장(1,119명, Topcon SL-D701 + DC-4),
  해부 분할 + 병변 라벨(검열반·익상편·결막하출혈·결막충혈·결막낭종·색소모반·복합)
  ([Frontiers in Digital Health 2026](https://www.frontiersin.org/journals/digital-health/articles/10.3389/fdgth.2025.1716501/full), [PMC](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12832839/)) — 다운로드 위치·라이선스는 논문 Data availability 확인
- Wikimedia Commons: [Category: Disorders of conjunctiva](https://commons.wikimedia.org/wiki/Category:Disorders_of_conjunctiva)
- EyeRounds Atlas: [Nasal pterygium](https://webeye.ophth.uiowa.edu/eyeforum/atlas/pages/nasal-pterygium-partial-arcus-senilis-and-iridoschisis.html) (CC BY-NC-ND)

---

## 출처별 라이선스 요약

| 출처 | 라이선스 | 내부 테스트·보정 | 앱/웹 데모·홍보물 포함 |
|------|---------|:---:|:---:|
| Wikimedia Commons | 파일마다 다름 (대부분 CC BY / CC BY-SA / PD) | ✅ | ✅ 저작자·라이선스 표기 필수 (BY-SA 는 같은 라이선스 유지) |
| EyeRounds Atlas (Univ. Iowa) | CC BY-NC-ND 3.0 | ✅ | ❌ (비영리·변경 금지) |
| SUSTech-SYSU / SLID / CAMG / Mendeley 핵백내장 | 데이터셋 페이지에서 **개별 확인 필요** | 대체로 ✅ (연구용) | 확인 전 ❌ |
| MGD-1K / CatScreen | 저자 요청 · 사용 동의서 | 승인 후 | ❌ |
| Efron 척도 (CooperVision) | 열람용 | 참고만 | ❌ |
| 자체 진료실 사진 | 환자 동의 + 비식별화 | ✅ | 동의 범위 내 |

## 권장 진행 순서
1. **바로 받을 수 있는 공개 데이터셋**부터: Mendeley 핵백내장(4번) · CAMG(3번) · SUSTech-SYSU(1번) — 각 데이터셋 페이지에서 라이선스를 확인하고 CSV `license` 열에 적기
2. **Wikimedia Commons**에서 질환별 대표 사진(데모용, 재배포 가능)
3. 공개 자료가 없는 항목은 **자체 촬영**: TBUT 동영상(6), 역조명(5), 품질/조명(7), Oxford 등급 SPK(1), 충혈 등급(2)
4. 사진마다 **의사 판정값**(Oxford, Efron, Meiboscore, LOCS III, TBUT 초)을 CSV 에 함께 기록 → `clinical.py`·`cataract.py` 상단 상수 보정에 사용

---

## 외부 수집본 — 일반외래 슬릿램프 질환순 (26장, 2026-10-25)

전체 목록: [`sample_images/external_outpatient_catalog.csv`](../sample_images/external_outpatient_catalog.csv)
(파일·원문 진단·해상도·구분·라이선스·출처·Google Drive 링크·SHA-256·활용 기능)

- **원본 위치:** Google Drive `일반외래_슬릿램프_질환순/` (질환별 하위 폴더, `metadata.json`, `진료질환순_사진목록.html`)
- **사진 파일은 저장소에 올리지 않습니다.** 24장이 CC BY-NC-ND(비영리·변경 금지)라 재배포에 해당하는 저장소 커밋 대신 목록과 링크만 둡니다.
- **번호 순서**는 실제 진료 빈도 통계 순위가 아니라 사진 수집·학습 우선순위입니다(A > B > C 군 안의 우열은 정하지 않음).
- **원문 진단을 그대로** 유지합니다. 개별 환자 사진에 **LOCS 등급을 임의로 부여하지 않았습니다.**
- 26장 모두 `metadata.json` 의 SHA-256 과 일치함을 확인했습니다.

| 구분 | 장수 | 파일 |
|------|:---:|------|
| 저해상도 (긴 변 < 1000px, 참고용) | 9 | 마이봄샘질환_1·2, 안검염, 아데노바이러스결막염_1, 알레르기결막염, 검열반_2, 세균각막염_1, 후낭혼탁_1·2 |
| 중증 (원문 명시) | 3 | 리사민그린_건성각결막염_1·2 (severe KCS), 익상편_슬릿램프 (pupil 침범) |
| 외상 (원문 카테고리 Trauma) | 6 | 결막하출혈_1·2, 각막찰과상_1·2, 금속각막이물_1·2 |
| 참고 도표 (환자 원본 아님) | 1 | LOCS_III_핵1-6_피질1-5_후낭하1-5 |

| 라이선스 | 장수 | 이용 조건 |
|---------|:---:|----------|
| CC BY-NC-ND 3.0 (University of Iowa EyeRounds) | 24 | 출처 표시 · 비상업 · 변경 금지 → 내부 참고·학습용. 상업 제품 모델 학습은 법무 확인 |
| CC BY 3.0 (Wikimedia Commons, José Miguel Varas MD) | 1 | 출처 표시 시 상업 이용·수정 가능 → 데모·앱 포함 가능 |
| 논문 CC BY 4.0 + 제3자 LOCS III 도표 (Chylack et al.) | 1 | 도표 원저작권 확인 전 재배포 금지 |

**분석 기능 보정에 쓸 수 있는 사진은 적습니다.** 형광염색(각막찰과상 2·HSV 1·세균각막염 1), 역조명(후낭혼탁_2 — PCO 이며 피질 백내장 아님) 정도이고,
마이봄샘 사진은 적외선 영상이 아니며 핵경화 사진은 등급이 없어 기준값 보정에는 쓸 수 없습니다. 나머지는 진단명 데모(08)·영상 품질 정상 기준(07)용입니다.
위 체크리스트(`sample_photo_list.csv`)의 `collected_count` 에 해당 항목을 반영했습니다.
