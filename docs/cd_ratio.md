# C/D 비 측정 — 방법과 근거

녹내장 분석 창의 **디스크 C/D** 탭이 컵/디스크 비(C/D ratio)를 어떻게 재는지, 왜 그렇게 재는지를 정리한 문서입니다.
(0.13.3 기준 · 코드: `fundusview/glaucoma.py`, `fundusview/disc3d.py`, `fundusview/ui/glaucoma_dialog.py`)

> **요약** — C/D 비 자체는 두 경계선(디스크 · 컵)만 정해지면 정확히 계산됩니다. 어려운 것은 **컵 경계를 어디로 볼
> 것인가**이고, 사진 한 장으로는 전문가끼리도 최대 0.2까지 차이가 납니다. 그래서 이 탭은 ① 사진에서 찾은 경계를
> **출발점**으로 놓고, ② 임상에서 쓰는 단서(혈관 꺾임 · 등고선)를 사진 위에 보여 주며, ③ 검사자가 **점 8개씩**으로
> 다듬은 선을 측정값으로 삼고, ④ 추정 방식에 따른 값의 차이를 그대로 보여 줍니다.

## 1. 무엇을 재는가 — 문헌의 정의

| 항목 | 정의 | 근거 |
|---|---|---|
| 디스크 경계 | **공막 고리(Elschnig) 안쪽 가장자리**. 유두 둘레 위축(PPA)의 바깥 가장자리가 아님 | [1][2] |
| 컵 경계 | 표면이 꺼지기 시작하는 **윤곽** — 작은 혈관이 림을 넘으며 **꺾이는 곳**. 색(창백함)이 아님 | [1][2][3] |
| 수직 C/D | 컵의 수직 지름 ÷ 디스크의 수직 지름 (사진 위 면적 측정법, planimetry) | [4][5] |
| 림 | 디스크 경계와 컵 경계 사이. 정상은 대개 하측 ≥ 상측 ≥ 비측 ≥ 이측 (ISNT) | [1] |

* **색이 아니라 윤곽** — "컵의 윤곽이 색보다 중요하다", "혈관이 정하는 컵 경계는 창백한 바닥과 분홍 테두리의 경계와
  다르며, 색의 차이에 맞추면 틀린다"[1][2]. 녹내장에서는 창백한 부분이 실제 컵보다 늦게 넓어져(pallor/cup discrepancy)
  **창백한 곳만 따라 그리면 컵을 작게** 보게 됩니다[3]. 정상안에서는 둘이 대체로 맞습니다.
* **디스크 크기에 따라 정상 범위가 다릅니다** — 정상안 88안의 스테레오 사진 면적 측정에서 수직 컵 지름은 수직 디스크
  지름(DD, mm)에 비례했습니다: **C/D = (−1.31 + 1.194 × DD) ÷ DD** (R² = 0.42)[4]. 큰 디스크는 정상에서도 컵이 크고,
  고정된 한 기준(예: 0.7)만 쓰면 **작은 디스크의 녹내장을 놓칩니다**(작은 디스크에서 민감도 33% 대 디스크 크기를 반영하면
  80%)[4]. 인구 기반 연구(Blue Mountains Eye Study, 3,654명)에서도 수직 C/D의 중앙값과 95 · 97.5 · 99 백분위가 수직 디스크
  지름에 따라 직선적으로 커졌습니다[5].
* **비율 하나보다 림** — DDLS(Disc Damage Likelihood Scale)는 **가장 얇은 림의 폭 ÷ 그 방향의 디스크 지름**, 림이 없으면
  **없는 범위(각도)** 로 1~10단계를 매기고 디스크 크기로 한 단계 보정합니다(작은 디스크 +1, 큰 디스크 −1)[6][7].
  관찰자 간 재현성이 C/D보다 좋았고(85% 대 74%)[6], 진단 정확도도 C/D와 같거나 조금 높게 보고됩니다[7].
* 역학 조사의 기준(ISGEO)은 정상 인구의 **97.5 백분위 이상의 수직 C/D 또는 양안 C/D 차이**(여러 인구에서 약 0.7 · 0.2)에
  시야 결손을 더한 것입니다[8]. C/D만으로 진단하지 않습니다.

## 2. 사진 한 장의 한계 — 알려진 오차

| 무엇 | 크기 | 근거 |
|---|---|---|
| 전문가 사이의 차이 (같은 사진) | 단안 사진에서 최대 **0.2 DD**, 스테레오에서 0.16 DD · 가중 κ 약 0.67 | [9] |
| 단안 대 스테레오 | 단안으로 읽은 C/D가 **더 작음** (평균 0.57–0.66 대 0.64–0.69), 일치도 ICC 0.74 → 0.80 | [10] |
| 단안 카메라 대 스테레오 카메라 | 스테레오에서 기준을 넘은 눈의 2/3에서 단안 값이 **0.1 이상** 달랐음 | [11] |
| 자동 측정 — 딥러닝 (REFUGE2 대회 최고) | 전문가 표시 대비 수직 C/D 평균 절대 오차 **약 0.04–0.06** | [12] |
| 자동 측정 — 혈관 꺾임 + 창백 (고전적 방법) | C/D 평균 오차 정상 0.03, **녹내장 0.12** | [3] |
| 초광각 사진 | 수직 C/D는 스테레오 유두 사진과 비슷하게 읽힘 (판독자 재현성 높음) | [14] |

즉 **사진 한 장에서 ±0.1 안쪽이면 전문가 수준**이고, 그보다 정확하려면 입체 정보(스테레오 쌍 · OCT)나 전문가 표시로
학습 · 검증한 모델이 필요합니다. 이 프로그램의 자동 맞춤은 학습 모델이 아니라 영상 처리 추정이므로 **출발점**입니다.

## 3. 프로그램이 재는 순서

1. **디스크 경계 (초록 선) — 자동**: 유두 주변을 잘라 혈관을 지운 밝기(빨강 위주 — 디스크가 망막과 가장 뚜렷이 구분됨)를
   유두 중심에서 사방으로 펼치고, **밝기가 망막 쪽으로 꺾이는 곳**을 둘레 전체에서 이어지는 한 줄로 찾은 뒤(동적
   계획법) 매끈한 닫힌 곡선으로 고릅니다 (`glaucoma.find_disc_margin`). 뚜렷한 경계가 없으면 찾지 못했다고 알리고 기본
   크기로 둡니다. **유두 둘레 위축의 밝은 고리를 디스크로 잡을 수 있으니** 초록 선이 공막 고리 안쪽인지 확인하세요.
2. **컵 경계 (노란 선) — 등고선**: 사진 한 장에서 추정한 유두의 모양(깊이)에서, 디스크 안쪽 가장 깊은 곳까지의 깊이 중
   **컵 기준 깊이**(처음 30%)의 **등고선**을 컵으로 봅니다 (`disc3d.cup_from_surface`). 모양 추정은 3D 입체 탭과 같은
   세 가지입니다 — **밝기**(창백한 곳 = 깊은 곳) · **혈관 꺾임**(꺾이는 곳 = 컵 벽) · **하이브리드**(꺾임이 있는 쪽은 그
   경계, 없는 쪽은 밝기 · 처음 설정). 등고선은 매끈한 닫힌 곡선으로 고릅니다(타원은 그대로, 혈관을 따라 삐져나온 좁은
   돌기는 따르지 않음) — 컵 경계를 혈관 꺾임과 창백함에서 매끈한 닫힌 곡선으로 그리는 문헌의 방식[3][13]과 같은 생각입니다.
3. **단서를 사진 위에**: 등고선(10%마다, 기준 깊이는 점선)과 **혈관 꺾임 점**(하늘색 = 혈관마다 가장 바깥 꺾임 = 컵 벽의
   위쪽)을 겹쳐 보여 줍니다. 컵 기준 깊이를 움직이면 노란 선이 그 등고선으로 옮겨 갑니다.
4. **다듬기**: 선마다 **점 8개**(상 · 하 · 비 · 이측과 그 사이 — 녹내장에서 먼저 얇아지는 하이측 · 상이측 포함)를 끄는 대로
   옮깁니다. 선은 점들을 지나는 매끈한 닫힌 곡선이고, 가운데 표시는 선의 중심을 따라갑니다(바깥 고리 = 디스크,
   안쪽 점 = 컵 — 끌면 통째로 이동, 선을 끌어도 같음). **다듬은 선이 측정값입니다.**
5. **측정** (`glaucoma.cdr_metrics`):

   | 값 | 계산 |
   |---|---|
   | 수직 · 수평 C/D | 컵 곡선의 높이 · 너비 ÷ 디스크 곡선의 높이 · 너비 |
   | 면적 C/D · 림 면적 | 두 곡선이 둘러싼 면적의 비 |
   | 림 두께 (8방향) | 디스크 중심에서 각 방향으로 (디스크 경계까지 − 컵 경계까지) ÷ 디스크 수직 지름 |
   | ISNT | 하 ≥ 상 ≥ 비 ≥ 이측 순서가 어긋난 곳 |
   | 가장 얇은 림 | 둘레 360°를 1° 간격으로: 림 폭 ÷ 그 방향 디스크 지름(림/디스크 비), 시계 방향, 림이 없는 범위(°) |
   | DDLS | 위 값으로 1~10단계 — 평균 크기 디스크(1.5–2.0 mm)의 표[6], 작은 디스크 +1 · 큰 디스크 −1 |
   | 디스크 수직 지름 (mm) | 사진의 화각 · 투영으로 계산한 축척 × 초록 선의 높이 (안축 24 mm 가정 — **추정**) |
   | 이 크기의 정상 평균 C/D | (−1.31 + 1.194 × DD) ÷ DD [4] — 흩어짐이 큰 평균이므로 기준선이 아니라 참고 |

6. **불확실성 표시**: 세 추정 방식 각각의 수직 C/D를 함께 보여 주고, 서로 0.1 넘게 다르면 "사진만으로는 컵 경계가
   뚜렷하지 않다"고 알립니다. 스테레오 쌍(같은 날 같은 눈 두 장)이 있으면 3D 입체 탭의 **시차로 계산한 깊이**의 컵을
   **[디스크 C/D 탭에 적용]** 으로 가져올 수 있습니다 — 단안 추정보다 근거가 강합니다[10].

## 4. 확인한 정확도

* **계산 자체**: 타원 · 점 8개 곡선 · 손으로 옮긴 모양에 대해 수직 · 수평 · 면적 C/D, 림 두께, DDLS가 해석값과 일치
  (`tests/test_glaucoma.py`). 점 8개를 지나는 곡선은 타원 면적과 0.1% 안에서 일치합니다.
* **정답을 아는 합성 유두** (디스크 · 컵 크기를 정해 그린 그림, 혈관 · 잡음 포함): 자동 맞춤의 수직 C/D 평균 절대 오차
  **0.024** (최대 0.08, 정답 0.30–0.85), 디스크 지름 오차 평균 1.4%. 컵이 창백한 부분보다 넓고 혈관이 컵 벽에서 꺾이는
  녹내장형 그림(정답 0.6 · 0.7 · 0.8)에서는 하이브리드가 0.58 · 0.68 · 0.78, **밝기만으로는 0.41 · 0.45 · 0.54**로 작게
  나왔습니다 — 1절의 문헌과 같은 방향입니다.
* **실제 사진** (프로그램 기본 샘플의 정상 · 녹내장 의심 · 고혈압 망막병증 유두): 디스크 경계는 경계가 뚜렷한 유두에서
  잘 맞았고, 신생혈관이 덮인 유두 · 넓은 위축이 있는 근시 유두에서는 어긋났습니다. 컵은 정상 유두에서 밝기 추정이
  그럴듯했고, 녹내장 의심 유두에서는 혈관 꺾임을 충분히 찾지 못해 밝기 수준(작게)으로 나왔습니다. **실제 사진에 대한
  정답(전문가 표시)과의 비교는 하지 않았습니다** — 이 문서의 수치를 임상 정확도로 읽으면 안 됩니다.

## 5. 더 정확하게 재려면

* 디스크는 **공막 고리 안쪽**, 컵은 **혈관이 꺾이는 곳**에 점을 놓으세요. 창백한 곳의 가장자리가 아닙니다.
* 같은 눈을 조금 다른 위치에서 찍은 **두 장(스테레오)** 이 있으면 3D 입체 · 스테레오 보기로 깊이를 확인하세요.
* 경과는 같은 방법 · 같은 기준 깊이로 잰 값끼리 비교하세요(시간별 비교 · 경과 비교 탭의 깜빡임과 함께).
* 자동 값을 임상 수준(±0.05)으로 올리려면 **전문가가 표시한 사진으로 학습 · 검증한 분할 모델**이 필요합니다[12].
  회사 카메라(초광각 포함)의 사진과 판독의 표시가 있어야 하고, 그 검증 없이 정확도를 말할 수 없습니다.

## 참고 문헌

1. Bourne RRA. The optic nerve head in glaucoma. *Community Eye Health* 2012. <https://pmc.ncbi.nlm.nih.gov/articles/PMC3588134/>
2. Gandhi M, Dubey S. Evaluation of the optic nerve head in glaucoma. *J Curr Glaucoma Pract* 2013. <https://pmc.ncbi.nlm.nih.gov/articles/PMC4741153/>
3. Joshi GD, Sivaswamy J, Karan K, Krishnadas SR. Vessel bend-based cup segmentation in retinal images. *ICPR* 2010. <https://cvit.iiit.ac.in/images/ConferencePapers/2010/Gopal10Vessel.pdf> · 요약(오차 수치): <https://cvit.iiit.ac.in/mip/research/odocseg.html>
4. Garway-Heath DF, Ruben ST, Viswanathan A, Hitchings RA. Vertical cup/disc ratio in relation to optic disc size: its value in the assessment of the glaucoma suspect. *Br J Ophthalmol* 1998;82:1118–24. <https://pubmed.ncbi.nlm.nih.gov/9924296/>
5. Crowston JG, Hopley CR, Healey PR, et al. The effect of optic disc diameter on vertical cup to disc ratio percentiles in a population based cohort: the Blue Mountains Eye Study. *Br J Ophthalmol* 2004;88:766–70. <https://pubmed.ncbi.nlm.nih.gov/15148209/>
6. Spaeth GL, Henderer J, Liu C, et al. The disc damage likelihood scale: reproducibility of a new method of estimating the amount of optic nerve damage caused by glaucoma. *Trans Am Ophthalmol Soc* 2002. 표: <https://www.sign.ac.uk/assets/sign144_disc_chart_colour.pdf> · 개관: <https://www.dovepress.com/spotlight-on-the-disc-damage-likelihood-scale-ddls-peer-reviewed-fulltext-article-OPTH>
7. Kara-José AC, Melo LAS Jr, Esporcatte BLB, et al. The disc damage likelihood scale: diagnostic accuracy and correlations with cup-to-disc ratio, structural tests and standard automated perimetry. *PLoS ONE* 2017. <https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0181428>
8. Foster PJ, Buhrmann R, Quigley HA, Johnson GJ. The definition and classification of glaucoma in prevalence surveys. *Br J Ophthalmol* 2002;86:238–42. <https://pmc.ncbi.nlm.nih.gov/articles/PMC1771026>
9. Varma R, Steinmann WC, Scott IU. Expert agreement in evaluating the optic disc for glaucoma. *Ophthalmology* 1992. <https://pure.psu.edu/en/publications/expert-agreement-in-evaluating-the-optic-disc-for-glaucoma/>
10. Morgan JE, Sheen NJL, North RV, Choong Y, Ansari E. Digital imaging of the optic nerve head: monoscopic and stereoscopic analysis. *Br J Ophthalmol* 2005. <https://pmc.ncbi.nlm.nih.gov/articles/PMC1772709>
11. Comparison of vertical cup-to-disc ratio estimates using stereoscopic and monoscopic cameras. *Eye* 2021. <https://pmc.ncbi.nlm.nih.gov/articles/PMC8602644/>
12. Orlando JI, Fu H, Breda JB, et al. REFUGE Challenge: a unified framework for evaluating automated methods for glaucoma assessment from fundus photographs. *Med Image Anal* 2020. <https://arxiv.org/abs/1910.03667> · REFUGE2: <https://arxiv.org/abs/2202.08994>
13. Joshi GD, Sivaswamy J, Krishnadas SR. Optic disk and cup segmentation from monocular color retinal images for glaucoma assessment. *IEEE Trans Med Imaging* 2011;30:1192–205.
14. Optic nerve assessment with stereo photographs and ultra-widefield scanning laser ophthalmoscope images. 2024. <https://pubmed.ncbi.nlm.nih.gov/39697170/> · Can ultra-wide field retinal imaging replace colour digital stereoscopy for glaucoma detection? *Ophthalmic Epidemiol* 2018. <https://doi.org/10.1080/09286586.2017.1351998>

> 문헌의 수치는 검색으로 확인한 초록 · 요약에서 옮겼습니다 — 원문 사이트는 작성 환경에서 열리지 않아 본문과 대조하지
> 못했고, 저자 · 권호 같은 서지 사항도 원문 확인이 필요합니다. 인용하기 전에 원문을 확인하세요.
