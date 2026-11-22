"""질환 설명: what each retinal disease of the sample library is, stage by stage — the words to say to a
patient and the pictures to show (drawn by disease_art.py, put together in ui/disease_view.py).

For every disease of ``samples.DEFAULT_DISEASES`` there is a :class:`Disease` (what it is, the symptoms,
what is done about it, its stages) and a recipe that draws, for a stage,

* a schematic fundus of a right eye with numbered findings,
* the retina cut through (the layers, and what the disease does to them),
* what the patient sees (a street scene; an Amsler grid as well for diseases of the macula).

They are models for talking with the patient, not findings of a patient — the window and the saved
picture say so. Glaucoma keeps the stages and the visual field of the glaucoma window's 환자 설명.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache

import cv2
import numpy as np

from . import disease_art as A
from . import glaucoma as G
from .disease_art import DISC, DISC_R, FOVEA, Fundus, Look, Section, Sight

NOTE_MODEL = "설명용 모형입니다. 이 환자의 실제 소견이나 진행 단계를 뜻하지 않습니다."


@dataclass(frozen=True)
class Stage:
    name: str
    text: str


@dataclass(frozen=True)
class Disease:
    name: str                    # as in the sample library (samples.DEFAULT_DISEASES)
    english: str
    about: str                   # 어떤 병인가
    symptoms: str                # 증상
    care: str                    # 치료 · 관리
    stages: tuple[Stage, ...]
    amsler: tuple[int, ...] = ()            # stages that also show an Amsler grid
    aliases: tuple[str, ...] = ()           # other names it may go by in a library (lower case)


@dataclass(frozen=True)
class Step:
    """One step of how a disease comes about (기전): a short title, the words, and the picture to draw
    (``ui/mechanism_view.py``: ``"vessel:sugar"``, ``"eye:iop"``, ``"nerve:lost"``, ``"section:drusen"``, ``"cells:rods"`` …)."""
    title: str
    text: str
    art: str


@dataclass
class Picture:
    """The parts of one explanation picture (``ui/disease_view.compose`` lays them out)."""
    disease: Disease
    stage: int
    fundus: np.ndarray
    fundus_marks: list
    section: np.ndarray
    section_marks: list
    section_title: str
    sight: np.ndarray
    amsler: np.ndarray | None = None
    layer_marks: list = field(default_factory=list)
    inset: np.ndarray | None = None          # a close-up of the disc (glaucoma, papilledema)
    inset_box: tuple | None = None           # where it is on the fundus (x, y, w, h pixels)
    inset_marks: list = field(default_factory=list)

    @property
    def stage_name(self) -> str:
        return self.disease.stages[self.stage].name

    @property
    def stage_text(self) -> str:
        return self.disease.stages[self.stage].text


# -------------------------------------------------------------------------------------------------
# the words
# -------------------------------------------------------------------------------------------------
DISEASES: tuple[Disease, ...] = (
    Disease(
        "정상 안저", "Normal fundus",
        "동공을 통해 눈 속 맨 안쪽의 망막을 찍은 사진입니다. 망막은 카메라의 필름처럼 빛을 받아 시신경을 거쳐 뇌로 "
        "보냅니다. 가운데의 황반으로 글자와 얼굴처럼 자세한 것을 봅니다.",
        "—",
        "40세 이후, 또는 당뇨 · 고혈압이 있거나 근시가 심하면 1년에 한 번 안저 검사를 권합니다.",
        (Stage("정상", "시신경 유두는 경계가 또렷하고 가운데 함몰(컵)이 작습니다. 혈관은 유두에서 나와 위 · 아래로 활 모양으로 "
                       "뻗고, 황반 가운데(중심와)에는 혈관이 없어 가장 선명하게 봅니다."),),
        aliases=("정상", "normal"),
    ),
    Disease(
        "당뇨망막병증", "Diabetic retinopathy",
        "높은 혈당이 오래가면 망막의 가는 혈관이 약해져 꽈리처럼 부풀고(미세혈관류) 새거나 막힙니다. 막힌 곳에 산소가 "
        "모자라면 약한 새 혈관(신생혈관)이 자라 쉽게 터집니다.",
        "초기에는 증상이 없습니다. 황반부종이 생기면 흐리고 휘어 보이고, 유리체 출혈이 생기면 갑자기 검은 점 · 연기 같은 것이 보입니다.",
        "혈당 · 혈압 · 콜레스테롤 조절과 금연. 당뇨가 있으면 증상이 없어도 1년에 한 번(진행된 단계면 더 자주) 안저 검사를 받습니다. "
        "레이저 광응고술, 항VEGF 주사, 유리체절제술로 치료합니다.",
        (Stage("경도 비증식성", "미세혈관류(작은 빨간 점)만 몇 개 보입니다. 시력은 대개 정상입니다. 혈당 · 혈압 관리와 정기 검진이 중요합니다."),
         Stage("중등도 비증식성", "점 · 얼룩 모양 출혈, 혈액 성분이 새어 나와 쌓인 노란 경성 삼출물, 신경섬유가 부어 생긴 하얀 면화반이 "
                             "보입니다. 황반에 미치지 않으면 시력은 아직 괜찮을 수 있습니다."),
         Stage("중증 비증식성", "출혈이 네 방향 모두에 많고, 정맥이 구슬을 꿴 것처럼 굵어지거나(정맥 염주) 망막 안에 비정상 혈관(IRMA)이 "
                             "보입니다. 1년 안에 증식성으로 진행할 위험이 높아 레이저 치료를 고려합니다."),
         Stage("증식성", "시신경 유두와 망막에 약한 신생혈관이 자랍니다. 터지면 유리체 출혈로 갑자기 날파리 · 시력 저하가 생기고, "
                        "섬유막이 망막을 당기면 견인 망막박리가 생길 수 있습니다. 범망막 레이저 광응고술, 항VEGF 주사, 유리체절제술로 치료합니다."),
         Stage("당뇨황반부종", "황반이 붓고 그 주변에 경성 삼출물이 고리 모양으로 쌓입니다. 어느 단계에서나 생길 수 있고 가운데가 흐리고 "
                            "휘어 보입니다. 항VEGF 주사 · 스테로이드 · 레이저로 치료합니다.")),
        amsler=(4,), aliases=("당뇨", "diabetic", "dr"),
    ),
    Disease(
        "나이관련 황반변성", "Age-related macular degeneration",
        "나이가 들면서 황반 아래 망막색소상피에 노폐물(드루젠)이 쌓이고 세포가 약해지는 병입니다. 건성은 천천히 위축되고, "
        "습성은 맥락막에서 비정상 혈관(신생혈관)이 자라 출혈 · 부종을 일으켜 빠르게 시력이 떨어집니다.",
        "가운데가 흐리거나 어둡게 비어 보임, 직선이 휘어 보임(변시증), 글자 사이가 빠져 보임.",
        "금연, 녹색 채소 · 생선 섭취, 의사가 권하면 AREDS2 영양제. 한쪽 눈씩 암슬러 격자를 보고 선이 휘거나 비면 바로 진료를 받습니다. "
        "습성은 항VEGF 주사로 치료합니다.",
        (Stage("초기 (드루젠)", "황반 주변에 노란 드루젠이 흩어져 있습니다. 시력은 대개 정상이지만 일부는 진행하므로 정기 검진과 "
                             "암슬러 격자 자가 검사를 합니다."),
         Stage("건성 (지도모양 위축)", "망막색소상피와 시세포가 지도 모양으로 없어져 그 자리가 창백하고, 아래의 맥락막 혈관이 비칩니다. "
                                  "가운데의 어둡게 비는 곳이 천천히 넓어집니다."),
         Stage("습성 (신생혈관)", "황반 아래에 맥락막 신생혈관이 자라 피와 액체가 새어 나옵니다. 가운데가 어둡게 가려지고 직선이 휘어 "
                              "보입니다. 서둘러 항VEGF 주사를 맞을수록 시력을 지키기 좋습니다.")),
        amsler=(0, 1, 2), aliases=("황반변성", "amd", "macular degeneration"),
    ),
    Disease(
        "녹내장 (시신경 유두)", "Glaucoma",
        "시신경이 서서히 손상되어 시야가 바깥부터 좁아지는 병입니다. 안압이 높으면 위험이 커지지만 안압이 정상이어도 생깁니다"
        "(한국인에게 흔한 정상안압녹내장).",
        "초기 · 중기에는 거의 느끼지 못합니다. 말기에는 가운데만 남아 터널 속에서 보는 것 같습니다.",
        "안약으로 안압을 낮추는 것이 기본이며 레이저 · 수술도 있습니다. 손상된 시신경은 되돌릴 수 없어 꾸준히 점안하고 정기적으로 "
        "시야 · 시신경 검사를 받습니다.",
        tuple(Stage(n, t.split(": ", 1)[-1]) for n, t in zip(G.STAGES, G.STAGE_TEXT)),
        aliases=("녹내장", "glaucoma"),
    ),
    Disease(
        "망막정맥폐쇄", "Retinal vein occlusion",
        "망막의 정맥이 막혀 피가 빠져나가지 못해 망막에 출혈과 부종이 생기는 병입니다. 고혈압 · 동맥경화로 굳은 동맥이 정맥을 "
        "누르는 교차 부위에서 잘 생깁니다.",
        "한쪽 눈이 통증 없이 갑자기 흐려지거나 시야 일부가 가려집니다.",
        "황반부종에는 항VEGF 주사 · 스테로이드, 혈관이 막혀 허혈이 생긴 곳에는 레이저. 혈압 · 당뇨 · 고지혈증 관리가 함께 중요합니다.",
        (Stage("분지 정맥폐쇄", "동맥과 정맥이 교차하는 곳에서 정맥 가지가 막혀, 그 가지가 맡은 부분에만 불꽃 모양 출혈과 면화반이 "
                             "생깁니다. 황반이 부으면 시력이 떨어집니다."),
         Stage("중심 정맥폐쇄", "시신경 안에서 중심 정맥이 막혀 망막 전체에 출혈이 퍼지고 정맥이 굵고 구불구불해집니다. 황반부종이 흔하고, "
                             "허혈이 심하면 신생혈관 녹내장이 생길 수 있어 자주 검사합니다.")),
        aliases=("정맥폐쇄", "rvo", "brvo", "crvo"),
    ),
    Disease(
        "망막동맥폐쇄", "Retinal artery occlusion",
        "망막의 동맥이 혈전이나 색전(혈관 벽에서 떨어진 찌꺼기 조각)으로 막혀 망막에 피가 가지 않는 병입니다. '눈의 뇌졸중'으로, "
        "뇌졸중 · 심장질환의 경고 신호일 수 있습니다.",
        "통증 없이 갑자기 한쪽 눈이 안 보이거나 시야 일부가 검게 가려집니다.",
        "응급입니다. 증상이 생기면 바로 응급실 · 안과로 가야 합니다. 뇌졸중 위험 평가(경동맥 · 심장 검사)가 필요합니다.",
        (Stage("분지 동맥폐쇄", "동맥 가지가 막혀 그 가지가 맡은 망막이 하얗게 붓습니다. 갈림길에 반짝이는 색전이 보이기도 합니다. "
                             "막힌 쪽 시야가 갑자기 가려집니다."),
         Stage("중심 동맥폐쇄", "망막 전체가 우윳빛으로 창백해지고, 망막이 가장 얇은 황반 가운데만 맥락막의 붉은색이 비쳐 체리빛 반점이 "
                             "보입니다. 동맥이 가늘어지고 혈류가 토막토막 끊겨 보입니다. 시력이 갑자기 심하게 떨어집니다.")),
        aliases=("동맥폐쇄", "rao", "crao", "brao"),
    ),
    Disease(
        "고혈압망막병증", "Hypertensive retinopathy",
        "높은 혈압이 오래가면 망막 동맥의 벽이 두꺼워지고 좁아집니다. 혈압이 갑자기 아주 높아지면 출혈 · 부종이 생기고 시신경까지 "
        "붓습니다. 망막의 혈관은 몸 전체 혈관 상태를 보여 줍니다.",
        "대부분 증상이 없습니다. 심하면 흐려 보이고 두통이 생깁니다.",
        "혈압 조절이 치료입니다. 혈압이 잡히면 출혈 · 부종은 대개 좋아집니다. 심장 · 신장 · 뇌혈관도 함께 확인합니다.",
        (Stage("1단계", "동맥이 전체적으로 가늘어집니다. 증상은 없습니다."),
         Stage("2단계", "동맥 벽이 두꺼워져 빛을 구리 · 은빛으로 반사하고(구리선 · 은선 동맥), 동맥이 정맥을 누르는 교차 부위에서 "
                       "정맥이 끊겨 보입니다(동정맥 교차 현상)."),
         Stage("3단계", "불꽃 모양 출혈, 면화반, 경성 삼출물이 생깁니다."),
         Stage("4단계", "시신경 유두가 붓고 황반에 별 모양 삼출물이 생깁니다. 악성 고혈압으로 즉시 내과 치료가 필요합니다.")),
        aliases=("고혈압", "hypertensive"),
    ),
    Disease(
        "망막박리", "Retinal detachment",
        "망막에 생긴 구멍(열공)으로 유리체의 물이 들어가 망막이 벽지처럼 들뜨는 병입니다. 고도근시, 외상, 백내장 수술 뒤, 나이가 들어 "
        "유리체가 망막에서 떨어질 때 잘 생깁니다.",
        "번쩍임(광시증), 갑자기 늘어난 날파리, 시야 한쪽이 커튼처럼 가려짐.",
        "응급 수술이 필요할 수 있습니다. 위 증상이 생기면 바로 산동 안저 검사를 받습니다. 공막돌륭술 · 유리체절제술 · 가스 주입으로 "
        "망막을 붙입니다.",
        (Stage("망막 열공", "주변부 망막에 말굽 모양 열공이 생겼습니다. 빛이 번쩍이고 날파리가 갑자기 많아집니다. 이때 레이저로 열공 "
                          "둘레를 막으면 박리를 막을 수 있습니다."),
         Stage("박리 (황반 붙음)", "열공으로 들어간 물이 망막을 들어 올려 그 부분이 회색으로 주름져 보입니다. 시야 한쪽에서 커튼이 "
                               "내려오듯 가려집니다. 황반이 떨어지기 전에 수술하면 시력을 지키기 좋습니다."),
         Stage("박리 (황반 떨어짐)", "박리가 황반까지 퍼져 가운데 시력이 크게 떨어집니다. 서둘러 수술로 망막을 붙입니다.")),
        aliases=("박리", "detachment", "rd"),
    ),
    Disease(
        "황반원공", "Macular hole",
        "황반 가운데(중심와)에 구멍이 생기는 병입니다. 나이가 들며 유리체가 황반에서 떨어질 때 당기는 힘으로 생기며 60대 여성에게 "
        "흔합니다.",
        "가운데 작은 점이 빠지거나 흐림, 직선이 가운데에서 꺾여 보임.",
        "유리체절제술과 가스 주입으로 구멍을 닫습니다. 수술 뒤 며칠 엎드린 자세를 유지하기도 합니다. 일찍 수술할수록 닫힐 가능성이 높습니다.",
        (Stage("초기 (부분 원공)", "유리체가 중심와를 당겨 망막 안쪽이 갈라지기 시작합니다. 약간 흐리고 휘어 보입니다. 저절로 좋아지기도 "
                                "해 경과를 봅니다."),
         Stage("전층 원공", "망막 전체 두께에 둥근 구멍이 뚫려 가운데가 비어 보이고 선이 가운데로 끌려 들어가 보입니다.")),
        amsler=(0, 1), aliases=("원공", "macular hole"),
    ),
    Disease(
        "황반전막", "Epiretinal membrane",
        "황반 표면에 얇은 막이 생겨 쪼그라들면서 망막을 주름지게 하는 병입니다. 나이와 관련해 흔하고, 망막 수술 · 염증 뒤에도 생깁니다.",
        "흐림, 직선이 물결처럼 휘어 보임(변시증), 두 눈으로 본 크기가 다르게 보임.",
        "증상이 가벼우면 경과를 보고, 불편이 크면 막을 벗겨 내는 유리체절제술을 합니다. 암슬러 격자로 변화를 확인합니다.",
        (Stage("경도 (셀로판 반사)", "황반 표면이 셀로판처럼 번쩍입니다. 대부분 증상이 없거나 가볍게 흐립니다."),
         Stage("진행 (황반 주름)", "막이 수축해 망막이 주름지고 두꺼워지며 혈관이 가운데로 끌려 구불구불해집니다. 직선이 휘어 보이고 "
                               "물체 크기가 달라 보입니다.")),
        amsler=(0, 1), aliases=("전막", "erm", "epiretinal", "pucker"),
    ),
    Disease(
        "중심장액맥락망막병증", "Central serous chorioretinopathy",
        "맥락막에서 새어 나온 맑은 액체가 황반 아래에 고여 망막이 물집처럼 들뜨는 병입니다. 30 ~ 50대 남성, 스트레스, 스테로이드 약 "
        "사용과 관련이 있습니다.",
        "가운데가 흐리거나 어둡게 보임, 물체가 작게 보임(소시증), 색이 바래 보임.",
        "스트레스 줄이기, 충분한 수면, 스테로이드(바르는 약 · 흡입제 포함) 사용 여부를 의사에게 알리기. 오래가면 레이저 · 광역학치료를 "
        "고려합니다.",
        (Stage("급성", "황반에 둥근 물집 모양의 장액성 망막박리가 생기고, 그 안에 액체가 새는 작은 점이 있습니다. 대부분 3 ~ 4개월 안에 "
                      "저절로 흡수됩니다."),
         Stage("만성 · 재발", "액체가 오래 남거나 되풀이되어 망막색소상피가 얼룩덜룩해지고 시세포가 약해집니다.")),
        amsler=(0, 1), aliases=("중심장액", "csc", "cscr", "central serous"),
    ),
    Disease(
        "병적 근시", "Pathologic myopia",
        "눈의 앞뒤 길이가 지나치게 길어져(대개 -6디옵터 이상의 고도근시) 망막과 맥락막이 얇게 늘어나는 병입니다. 안경으로 교정해도 "
        "망막이 상해 시력이 떨어질 수 있습니다.",
        "안경을 써도 흐림, 직선이 휘어 보임. 망막박리 · 녹내장 위험도 높습니다.",
        "근시성 신생혈관에는 항VEGF 주사. 정기적인 안저 검사를 받고, 번쩍임 · 날파리 · 커튼 증상이 생기면 바로 진료를 받습니다.",
        (Stage("근시성 안저", "맥락막이 얇아져 그 아래 혈관 무늬가 호피처럼 비치고(호피 무늬 안저), 시신경 유두가 기울고 옆에 하얀 "
                            "근시성 반월(유두 주위 위축)이 생깁니다."),
         Stage("근시성 황반변성", "늘어난 망막에 금(래커 균열)이 가고 군데군데 위축되어 하얗게 보이며, 신생혈관이 자라 출혈 · 검은 반점"
                               "(푹스 반점)이 생길 수 있습니다. 가운데가 휘거나 어둡게 보입니다.")),
        amsler=(1,), aliases=("근시", "myopia", "myopic"),
    ),
    Disease(
        "시신경 유두부종", "Papilledema",
        "뇌 안의 압력(두개내압)이 올라가 시신경 유두가 붓는 상태입니다. 뇌종양 · 출혈 · 특발성 두개내압 상승 등이 원인일 수 있어 "
        "원인을 꼭 찾아야 합니다.",
        "두통, 구역, 몇 초씩 시야가 어두워짐, 겹쳐 보임. 초기에는 시력이 정상인 경우가 많습니다.",
        "응급으로 뇌 영상(CT · MRI)과 원인 치료가 필요합니다. 두개내압을 낮추는 약 · 시술을 합니다.",
        (Stage("초기", "유두 경계가 흐려지고 붉어지며 가장자리 신경섬유가 부옇게 보입니다. 시력은 대개 정상이고 맹점이 조금 커집니다."),
         Stage("진행", "유두가 크게 부풀어 솟아오르고, 경계를 지나는 혈관이 부종에 가려지며 둘레에 불꽃 모양 출혈과 면화반이 생깁니다. "
                      "맹점이 커지고 잠깐씩 시야가 어두워집니다."),
         Stage("만성 (위축)", "부종이 오래가면 시신경이 위축되어 유두가 창백해지고 시야가 좁아집니다.")),
        aliases=("유두부종", "papilledema", "papilloedema"),
    ),
    Disease(
        "망막색소변성", "Retinitis pigmentosa",
        "빛을 받는 시세포(먼저 막대세포)가 유전적으로 서서히 줄어드는 병입니다. 밤에 잘 안 보이는 것부터 시작해 시야가 바깥에서 "
        "안쪽으로 좁아집니다.",
        "야맹증, 시야가 좁아짐, 눈부심. 백내장 · 황반부종이 함께 생기기도 합니다.",
        "유전 상담과 유전자 검사(일부 유전자형은 유전자 치료가 있습니다), 자외선 차단, 저시력 보조기구. 백내장 · 황반부종은 치료할 수 "
        "있습니다.",
        (Stage("초기", "중간 주변부에 뼈 조각 모양 색소가 조금 생기고 동맥이 약간 가늘어집니다. 어두운 곳에서 잘 안 보입니다(야맹증)."),
         Stage("중기", "색소가 고리 모양으로 많아지고 혈관이 가늘어집니다. 고리 모양으로 시야가 비어 옆의 물체에 부딪힙니다."),
         Stage("말기", "시신경 유두가 밀랍처럼 창백해지고 색소가 넓게 퍼집니다. 가운데만 남아 터널 속에서 보는 것 같습니다.")),
        aliases=("색소변성", "retinitis", "rp"),
    ),
)
BY_NAME = {d.name: d for d in DISEASES}

# 기전: how each disease comes about, step by step (for the normal fundus: how the eye sees)
MECHANISMS: dict[str, tuple[Step, ...]] = {
    "정상 안저": (
        Step("빛이 망막에 맺힘", "빛이 각막과 수정체를 지나며 굽어 눈 안쪽 망막, 특히 황반의 중심와에 초점이 맺힙니다.", "eye:light"),
        Step("시세포가 빛을 신호로", "망막의 시세포(막대세포 · 원뿔세포)가 빛을 전기 신호로 바꿉니다. 그 아래 색소상피가 시세포를 돌봅니다.",
             "cells:healthy"),
        Step("시신경을 따라 뇌로", "신호는 신경섬유를 따라 시신경 유두로 모이고, 시신경을 타고 뇌로 가서 보는 것이 됩니다.", "nerve:healthy"),
    ),
    "당뇨망막병증": (
        Step("높은 혈당이 혈관을 상하게 함", "혈당이 오래 높으면 가는 혈관을 받치는 세포(혈관주위세포)가 줄고 혈관 벽이 약해집니다.",
             "vessel:sugar"),
        Step("부풀고 새는 혈관", "약해진 벽이 꽈리처럼 부풀고(미세혈관류) 피와 혈장이 새어 출혈 · 경성 삼출물 · 부종이 생깁니다.",
             "vessel:leak"),
        Step("막힌 혈관, 산소 부족", "가는 혈관이 막히면 그 너머 망막에 피가 가지 않아 산소가 모자랍니다(허혈). 면화반이 생깁니다.",
             "vessel:blocked"),
        Step("신생혈관이 자람", "산소가 모자란 망막이 VEGF를 내보내 약한 신생혈관이 자랍니다. 쉽게 터져 유리체 출혈을 일으킵니다. "
             "항VEGF 주사는 이 신호를 막습니다.", "vessel:vegf"),
    ),
    "나이관련 황반변성": (
        Step("노폐물이 쌓임", "나이 · 흡연 · 유전으로 색소상피가 시세포의 찌꺼기를 다 치우지 못해 색소상피와 브루크막 사이에 "
             "드루젠이 쌓입니다.", "section:drusen"),
        Step("세포가 없어짐 (건성)", "드루젠 위의 색소상피와 시세포가 영양을 잘 받지 못해 서서히 없어집니다. 그 자리가 지도모양 위축입니다.",
             "section:ga"),
        Step("신생혈관이 자람 (습성)", "VEGF 신호로 맥락막의 신생혈관이 브루크막을 뚫고 자라 피와 액체를 흘립니다. 항VEGF 주사가 "
             "이것을 막습니다.", "section:cnv"),
    ),
    "녹내장 (시신경 유두)": (
        Step("안압이 오름", "눈 속 물(방수)이 배출구로 잘 빠지지 못하면 안압이 오릅니다. 안압이 정상이어도 시신경이 약하거나 "
             "혈류가 부족하면 생깁니다.", "eye:iop"),
        Step("시신경이 눌림", "압력이 시신경 유두의 체 모양 판(사상판)을 뒤로 밀고 신경섬유와 혈관을 눌러 영양이 잘 가지 못합니다.",
             "nerve:pressed"),
        Step("신경섬유가 줄어듦", "신경섬유가 하나둘 죽어 유두의 함몰(컵)이 커지고, 그 섬유가 맡은 시야가 바깥부터 사라집니다. "
             "되살아나지 않으므로 안압을 낮춰 진행을 늦춥니다.", "nerve:lost"),
    ),
    "망막정맥폐쇄": (
        Step("굳은 동맥이 정맥을 누름", "망막의 동맥과 정맥은 교차하는 곳에서 같은 막에 싸여 있습니다. 고혈압 · 동맥경화로 굳은 동맥이 "
             "그 아래 정맥을 누릅니다.", "vessel:crossing"),
        Step("정맥이 막혀 피가 고임", "눌린 곳에 혈전이 생겨 정맥이 막히면 피가 빠져나가지 못해 정맥이 부풀고, 벽 밖으로 피가 새어 "
             "출혈이 됩니다.", "vessel:backup"),
        Step("황반부종 · 허혈", "새어 나온 물이 황반에 고여 붓고(황반부종) 시력이 떨어집니다. 허혈이 넓으면 VEGF로 신생혈관이 생길 수 "
             "있습니다.", "section:edema"),
    ),
    "망막동맥폐쇄": (
        Step("색전이 떨어져 나옴", "경동맥 벽의 죽상경화 찌꺼기나 심장(부정맥 · 판막)에서 생긴 혈전이 떨어져 피를 타고 눈으로 옵니다.",
             "vessel:source"),
        Step("망막 동맥이 막힘", "가는 망막 동맥에 걸려 막으면 그 너머 망막에 피가 가지 않습니다.", "vessel:embolus"),
        Step("망막이 하얗게 붓고 기능을 잃음", "피를 받지 못한 망막 안쪽 층이 하얗게 붓고 몇 시간 안에 되돌릴 수 없게 상합니다. "
             "응급 진료가 필요한 이유입니다.", "section:ischemic"),
    ),
    "고혈압망막병증": (
        Step("동맥 벽이 두꺼워짐", "높은 혈압을 오래 받으면 동맥 벽이 두꺼워지고 굳어 혈관 통로가 좁아집니다(가늘어진 동맥, 구리선 · 은선).",
             "vessel:thick"),
        Step("교차 부위에서 정맥을 누름", "두꺼워진 동맥이 교차하는 정맥을 눌러 정맥이 끊겨 보입니다. 정맥폐쇄의 원인이 되기도 합니다.",
             "vessel:crossing"),
        Step("혈관이 새고 터짐", "혈압이 갑자기 아주 높아지면 혈관 벽이 견디지 못해 피와 혈장이 새어 출혈 · 경성 삼출물 · 면화반 · "
             "시신경 부종이 생깁니다.", "vessel:burst"),
    ),
    "망막박리": (
        Step("유리체가 떨어짐", "나이가 들면 젤 같은 유리체가 묽어지고 줄어들어 망막에서 떨어집니다(후유리체박리). 이때 날파리 · "
             "번쩍임이 생깁니다.", "eye:pvd"),
        Step("망막이 찢어짐", "망막에 단단히 붙어 있던 곳을 유리체가 당기면 망막이 말굽 모양으로 찢어집니다(열공).", "section:tear"),
        Step("물이 들어가 망막이 들뜸", "묽어진 유리체 물이 열공으로 들어가 망막을 색소상피에서 떼어 냅니다. 떨어진 망막은 영양을 받지 "
             "못해 기능을 잃습니다.", "eye:rdfluid"),
    ),
    "황반원공": (
        Step("유리체가 중심와를 당김", "유리체가 줄어들며 황반 가운데에 붙어 있던 곳을 앞으로 당깁니다(유리체황반견인).", "section:vmt"),
        Step("중심와가 갈라짐", "당기는 힘으로 중심와 안쪽이 갈라지고 물주머니가 생깁니다.", "section:split"),
        Step("구멍이 뚫림", "망막 전체 두께가 끊어져 구멍이 생기고 가장자리가 벌어집니다. 수술로 유리체를 없애고 가스로 받쳐 구멍을 "
             "닫습니다.", "section:hole"),
    ),
    "황반전막": (
        Step("표면에 막이 생김", "유리체가 떨어진 뒤 망막 표면에 세포가 자라 투명하고 얇은 막을 만듭니다. 망막 수술 · 염증 뒤에도 "
             "생깁니다.", "section:erm_cells"),
        Step("막이 쪼그라듦", "막이 수축하며 망막 표면을 가운데로 끌어당깁니다.", "section:erm_pull"),
        Step("망막이 주름짐", "망막이 주름지고 두꺼워져 시세포의 배열이 흐트러지므로 직선이 휘고 크기가 달라 보입니다.",
             "section:erm_wrinkle"),
    ),
    "중심장액맥락망막병증": (
        Step("맥락막 혈관이 넓어짐", "스트레스 호르몬 · 스테로이드 등으로 맥락막 혈관이 넓어지고 새기 쉬워져 맥락막이 두꺼워집니다.",
             "section:pachy"),
        Step("색소상피로 액체가 샘", "압력이 높아진 맥락막의 액체가 색소상피의 약한 곳을 지나 망막 쪽으로 샙니다.", "section:leak"),
        Step("망막 밑에 물집", "액체가 시세포 아래에 고여 망막이 물집처럼 들뜹니다. 상이 흐리고 작게 보이며, 새는 곳이 아물면 "
             "흡수됩니다.", "section:csc"),
    ),
    "병적 근시": (
        Step("눈이 길어짐", "눈의 앞뒤 길이가 길어지면 초점이 망막 앞에 맺혀 먼 곳이 흐립니다(근시). 고도근시에서는 어른이 되어서도 "
             "조금씩 길어지기도 합니다.", "eye:long"),
        Step("망막 · 맥락막이 얇아짐", "늘어난 눈벽에서 맥락막과 망막이 얇아져 맥락막 혈관이 비치고(호피 무늬), 유두 옆이 위축됩니다"
             "(반월).", "section:thin"),
        Step("금이 가고 신생혈관이 자람", "더 늘어나면 브루크막에 금(래커 균열)이 가고, 그 틈으로 신생혈관이 자라 출혈 · 위축"
             "(푹스 반점)이 생깁니다.", "section:crack"),
    ),
    "시신경 유두부종": (
        Step("뇌압이 오름", "뇌종양 · 뇌출혈 · 뇌척수액 흐름 장애 · 특발성 두개내압 상승 등으로 머릿속 압력이 오릅니다.", "eye:brain"),
        Step("시신경을 따라 전해진 압력", "시신경을 싼 집 안의 뇌척수액으로 압력이 전해져, 신경섬유 안의 물질 흐름(축삭 수송)이 "
             "유두에서 막힙니다.", "nerve:stasis"),
        Step("유두가 붓고 솟아오름", "막힌 물질이 쌓여 신경섬유가 붓고 유두가 솟으며 혈관이 가려지고 출혈이 생깁니다. 오래가면 "
             "신경섬유가 죽어 위축됩니다.", "nerve:swollen"),
    ),
    "망막색소변성": (
        Step("시세포 유전자의 이상", "시세포에 필요한 단백질을 만드는 여러 유전자 가운데 하나에 이상이 있습니다. 부모에게서 물려받거나 "
             "새로 생깁니다.", "cells:gene"),
        Step("막대세포가 먼저 줄어듦", "어두운 곳과 주변을 보는 막대세포가 먼저 죽어 야맹증과 고리 모양 시야 결손이 생깁니다.",
             "cells:rods"),
        Step("원뿔세포까지 줄어듦", "남은 원뿔세포도 차츰 줄고, 색소상피의 색소가 망막으로 옮겨 가 뼈 조각 모양 색소가 됩니다. "
             "시야가 터널처럼 좁아집니다.", "cells:late"),
    ),
}


def find(name: str | None) -> Disease | None:
    """The disease a sample-library name means (its own name, or a name that contains one of its aliases)."""
    if not name:
        return None
    if name in BY_NAME:
        return BY_NAME[name]
    low = name.lower()
    for d in DISEASES:
        if d.name in name or any(a in low for a in d.aliases):
            return d
    return None


# -------------------------------------------------------------------------------------------------
# the pictures
# -------------------------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _scene() -> np.ndarray:
    return G.sample_scene(600)


def _sector_mask(f: Fundus, about, lo, hi, rmin=0.0, rmax=2.0, soft=0.03) -> np.ndarray:
    ang = f.angle_from(about)
    inside = ((ang >= lo) & (ang <= hi)) if lo <= hi else ((ang >= lo) | (ang <= hi))
    d = f.dist(about)
    m = (inside & (d >= rmin) & (d <= rmax)).astype(np.float32)
    return cv2.GaussianBlur(m, (0, 0), soft * f.R)


def _in_retina(img, sec: Section, pts, color, layer=("surface", "outer_top"), size=(0.012, 0.03)) -> None:
    """Spots inside the retina, ``pts`` = [(x, depth 0 … 1 between the two levels)] (section extras)."""
    lv = sec.levels
    W, H = sec.W, sec.H
    for x, t in pts:
        i = int(np.clip(x, 0, 1) * (W - 1))
        y = lv[layer[0]][i] + (lv[layer[1]][i] - lv[layer[0]][i]) * t
        cv2.ellipse(img, (int(x * W), int(y * H)), (int(size[0] * W), max(1, int(size[1] * H * 0.5))), 0, 0, 360,
                    color, -1, cv2.LINE_AA)


def _gauss(x, c, w):
    return np.exp(-((x - c) / w) ** 2).astype(np.float32)


# -- 정상 -------------------------------------------------------------------------------------------
def _normal(stage):
    f = Fundus(look=Look())
    f.mark(DISC[0] + 0.02, DISC[1] - 0.09, "시신경 유두")
    f.mark(DISC[0] - 0.01, DISC[1] + 0.01, "함몰 (컵)")
    f.mark(FOVEA[0] + 0.09, FOVEA[1] - 0.10, "황반")
    f.mark(*FOVEA, "중심와")
    f.mark(*f.vessel_point("STA", 0.62), "망막 동맥")
    f.mark(*f.vessel_point("ITV", 0.62), "망막 정맥")
    s = Section()
    s.mark(0.5, ("surface", 0.0), "중심와 (가장 선명하게 보는 곳)")
    return f, s, Sight()


# -- 당뇨망막병증 ---------------------------------------------------------------------------------------
def _dr(stage):
    look = Look(seed=7)
    if stage == 2:
        look.vein_w, look.tortuous = 1.15, 0.35
    f = Fundus(look=look)
    s = Section()
    sight = Sight()
    ma = f.scatter([10, 14, 22, 18, 14][stage], FOVEA, 0.48, avoid=FOVEA, avoid_r=0.06)
    f.microaneurysms(ma)
    f.mark(*ma[0], "미세혈관류")
    sec_dots = []
    if stage in (1, 2, 3):
        blots = f.scatter((10, 34, 16)[stage - 1], (0.0, 0.0), 0.62 if stage == 1 else 0.88, avoid=FOVEA, avoid_r=0.07)
        f.blots(blots)
        fl = f.near_vessels((4, 10, 5)[stage - 1], ("STV", "ITV", "SNV", "INV"), 0.05, 0.2, 0.8)
        f.flames(fl)
        f.mark(*blots[1], "점 · 얼룩 출혈")
        sec_dots.append(("heme", 0.30))
    if stage in (1, 2):
        ex = []
        for c in ((-0.36, -0.14), (0.02, 0.22))[: 2]:
            ex += f.scatter(14, c, 0.06)
        f.exudates(ex)
        f.mark(*ex[3], "경성 삼출물")
        cws = [f.vessel_point("STA", 0.30), f.vessel_point("ITV", 0.38)] + ([f.vessel_point("SNV", 0.4),
                                                                              f.vessel_point("ITA", 0.6)] if stage == 2 else [])
        cws = [(u + 0.03, v + 0.02) for u, v in cws]
        f.cotton_wool(cws, 0.032)
        f.mark(*cws[0], "면화반")
    if stage == 2:
        beads = []
        for name in ("STV", "ITV"):
            for frac in (0.32, 0.36, 0.40, 0.55, 0.59):
                beads.append(f.vessel_point(name, frac))
        f.spots(beads, 0.016, A.VEIN, 0.9, blur=0.003)
        f.mark(*f.vessel_point("STV", 0.36), "정맥 염주")
        irma = (-0.05, 0.30)
        f.nv_tuft(irma, 0.04, (150, 30, 30), n=9)
        f.mark(*irma, "망막 안 비정상 혈관 (IRMA)")
    if stage == 3:
        f.nv_tuft((DISC[0] - 0.02, DISC[1] + 0.01), 0.10, n=22)
        f.mark(DISC[0] - 0.08, DISC[1] - 0.06, "유두 신생혈관")
        nve = f.vessel_point("STV", 0.45)
        f.nv_tuft((nve[0], nve[1] + 0.01), 0.06, n=14)
        f.mark(*nve, "망막 신생혈관")
        m = f.mask()                                   # a boat-shaped haemorrhage in front of the retina
        f.ellipse(m, -0.08, 0.54, 0.16, 0.10)
        cv2.rectangle(m, f.px(-0.26, 0.38), f.px(0.10, 0.52), 0, -1)
        f.paint(m, A.HEME_DARK, 0.95, blur=0.006)
        f.mark(-0.08, 0.58, "망막앞 출혈")
        fib = f.mask()
        f.polyline(fib, f.paths["STA"][12:60], 0.05)
        f.paint(fib, (236, 222, 206), 0.42, blur=0.012)
        f.mark(*f.vessel_point("STA", 0.28), "섬유혈관막")
    if stage == 4:
        ring = f.ring_points((-0.31, -0.06), 0.085, 46, 0.012) + f.scatter(16, (-0.12, 0.05), 0.07)
        f.exudates(ring, 0.009)
        f.mark(-0.31 + 0.085, -0.06, "고리 모양 경성 삼출물")
        m = f.mask()
        f.ellipse(m, FOVEA[0] - 0.04, FOVEA[1] - 0.03, 0.15, 0.12)
        f.paint(m, (232, 170, 120), 0.18, blur=0.04)
        f.mark(FOVEA[0], FOVEA[1] + 0.02, "황반부종 (부은 곳)")
        f.look.fovea_reflex = False
        f.blots(f.scatter(8, FOVEA, 0.35, avoid=FOVEA, avoid_r=0.1))
    # the section
    if stage == 0:
        s.extras.append(lambda img, sec: _in_retina(img, sec, [(0.30, 0.55)], (176, 30, 30), size=(0.008, 0.05)))
        s.mark(0.30, ("surface", 0.04), "미세혈관류")
    if stage in (1, 2):
        s.extras.append(lambda img, sec: _in_retina(img, sec, [(0.27, 0.45), (0.70, 0.5), (0.80, 0.35)] +
                                                    ([(0.16, 0.5), (0.88, 0.45)] if stage == 2 else []),
                                                    A.HEME, size=(0.012, 0.09)))
        s.extras.append(lambda img, sec: _in_retina(img, sec, [(0.36 + 0.012 * k, 0.86 + 0.04 * (k % 2)) for k in range(6)],
                                                    A.EXUDATE, layer=("inner_top", "pr_top"), size=(0.005, 0.035)))
        s.extras.append(lambda img, sec: _in_retina(img, sec, [(0.76, 0.05), (0.775, 0.12)], A.CWS, size=(0.02, 0.10)))
        s.mark(0.27, ("surface", 0.06), "출혈")
        s.mark(0.39, ("pr_top", -0.01), "경성 삼출물")
        s.mark(0.77, ("surface", -0.02), "면화반")
    if stage == 3:
        def nv(img, sec):
            lv = sec.levels
            W, H = sec.W, sec.H
            rng = np.random.default_rng(4)
            for x0 in (0.70, 0.74, 0.78):
                i = int(x0 * (W - 1))
                y0 = lv["surface"][i] * H
                pts = [(x0 * W, y0)]
                for k in range(6):
                    pts.append((pts[-1][0] + rng.normal(0, 6 * A.SS), pts[-1][1] - (8 + 2 * k) * A.SS))
                cv2.polylines(img, [np.int32(pts)], False, (210, 50, 50), 2 * A.SS, cv2.LINE_AA)
            haze = np.zeros(img.shape[:2], np.float32)
            cv2.ellipse(haze, (int(0.62 * W), int(0.12 * H)), (int(0.22 * W), int(0.10 * H)), 0, 0, 360, 1, -1)
            haze = cv2.GaussianBlur(haze, (0, 0), 14 * A.SS)[..., None] * 0.8
            img[:] = img * (1 - haze) + np.float32([120, 20, 22]) * haze
            mem = np.int32([(x * W, (lv["surface"][int(x * (W - 1))] - 0.04 - 0.05 * math.sin((x - 0.55) / 0.3 * math.pi)) * H)
                            for x in np.linspace(0.55, 0.95, 30)])
            cv2.polylines(img, [mem], False, (238, 226, 210), 2 * A.SS, cv2.LINE_AA)
        s.extras.append(nv)
        s.mark(0.74, ("surface", -0.12), "신생혈관")
        s.mark(0.62, 0.12, "유리체 출혈")
        s.mark(0.90, ("surface", -0.05), "섬유막 (망막을 당김)")
    if stage == 4:
        s.inner_t = s.inner_t + 0.12 * _gauss(s.x, 0.48, 0.13)
        s.outer_t = s.outer_t + 0.03 * _gauss(s.x, 0.5, 0.1)
        s.cysts = [(0.42, 0.55, 0.025, 0.05), (0.47, 0.45, 0.02, 0.06), (0.52, 0.6, 0.028, 0.05),
                   (0.57, 0.5, 0.018, 0.04), (0.38, 0.62, 0.015, 0.035)]
        s.extras.append(lambda img, sec: _in_retina(img, sec, [(0.32 + 0.01 * k, 0.95) for k in range(4)] +
                                                    [(0.62 + 0.01 * k, 0.95) for k in range(4)],
                                                    A.EXUDATE, layer=("inner_top", "pr_top"), size=(0.005, 0.035)))
        s.mark(0.47, ("surface", 0.1), "부종 (물주머니)")
        s.mark(0.64, ("pr_top", -0.02), "경성 삼출물")
    sight = (Sight(), Sight(blur=0.6), Sight(blur=1.1),
             Sight(haze=0.35, spots=8, spot_size=0.06, spot_color=(70, 14, 12), blur=2.0),
             Sight(center_blur=7, center_dark=0.4, center_r=0.15, center_tint=(78, 66, 54), warp=0.55))[stage]
    return f, s, sight


# -- 나이관련 황반변성 ---------------------------------------------------------------------------------
def _amd(stage):
    f = Fundus(look=Look(seed=11, fovea_reflex=stage == 0))
    s = Section()
    dr = f.scatter((34, 22, 18)[stage], FOVEA, 0.24, avoid=FOVEA, avoid_r=0.025 if stage == 0 else 0.14)
    f.drusen(dr, 0.015)
    f.mark(*dr[0], "드루젠")
    if stage == 0:
        pig = f.scatter(6, FOVEA, 0.10, avoid=FOVEA, avoid_r=0.02)
        f.spots(pig, 0.006, A.PIGMENT, 0.7, blur=0.002)
        f.mark(*pig[0], "색소 변화")
        s.sub_rpe = (0.03 * _gauss(s.x, 0.40, 0.02) + 0.04 * _gauss(s.x, 0.46, 0.025) + 0.025 * _gauss(s.x, 0.56, 0.018)
                     + 0.035 * _gauss(s.x, 0.62, 0.022))
        s.mark(0.46, ("rpe_top", 0.0), "드루젠 (색소상피 아래 노폐물)")
        sight = Sight(warp=0.15, center_blur=2.0)
    elif stage == 1:
        m = f.mask()
        for du, dv, a, b in ((0.0, 0.0, 0.10, 0.08), (0.06, -0.04, 0.06, 0.05), (-0.06, 0.05, 0.07, 0.05), (0.03, 0.07, 0.05, 0.04)):
            f.ellipse(m, FOVEA[0] + du, FOVEA[1] + dv, a, b)
        f.paint(m, (230, 190, 140), 0.88, blur=0.004)
        ch = f.mask()                                  # large choroidal vessels show through
        rng = np.random.default_rng(3)
        for k in range(7):
            u0, v0 = FOVEA[0] + rng.uniform(-0.12, 0.1), FOVEA[1] + rng.uniform(-0.1, 0.1)
            pts = [(u0, v0)]
            for _ in range(5):
                pts.append((pts[-1][0] + rng.normal(0.03, 0.02), pts[-1][1] + rng.normal(0, 0.03)))
            f.polyline(ch, pts, 0.008)
        f.paint(ch * cv2.erode(m, np.ones((5, 5), np.uint8)), (204, 108, 70), 0.75, blur=0.003)
        f.mark(FOVEA[0] - 0.04, FOVEA[1] - 0.02, "지도모양 위축")
        f.mark(FOVEA[0] + 0.06, FOVEA[1] + 0.03, "비치는 맥락막 혈관")
        loss = np.clip((0.15 - np.abs(s.x - 0.5)) / 0.03, 0, 1)
        s.pr_loss = loss.astype(np.float32)
        s.rpe_loss = loss.astype(np.float32)
        s.outer_t = s.outer_t * (1 - 0.3 * loss)
        s.sub_rpe = (0.02 * _gauss(s.x, 0.28, 0.02) + 0.025 * _gauss(s.x, 0.72, 0.02)).astype(np.float32)
        s.mark(0.5, ("pr_top", 0.0), "시세포 · 색소상피가 없어진 곳")
        s.mark(0.72, ("rpe_top", 0.0), "드루젠")
        sight = Sight(center_dark=0.88, center_r=0.10, center_blur=4, center_tint=(28, 26, 24))
    else:
        m = f.mask()
        f.ellipse(m, FOVEA[0] + 0.02, FOVEA[1] + 0.01, 0.15, 0.12)
        f.paint(m, A.HEME, 0.9, blur=0.012)
        f.mark(FOVEA[0] + 0.12, FOVEA[1] + 0.07, "망막 밑 출혈")
        c = f.mask()
        f.ellipse(c, FOVEA[0] - 0.01, FOVEA[1] - 0.005, 0.07, 0.06)
        f.paint(c, (128, 130, 96), 0.85, blur=0.01)
        f.mark(FOVEA[0] - 0.02, FOVEA[1] - 0.02, "맥락막 신생혈관")
        ex = f.ring_points((FOVEA[0] + 0.02, FOVEA[1] + 0.01), 0.19, 30, 0.012)
        ex = [p for p in ex if p[0] < FOVEA[0] + 0.12]
        f.exudates(ex, 0.009)
        f.mark(*ex[len(ex) // 2], "경성 삼출물")

        def cnv(img, sec):
            lv = sec.levels
            W, H = sec.W, sec.H
            rng = np.random.default_rng(9)
            for k in range(14):                        # tangled new vessels in the lifted RPE
                x = rng.uniform(0.45, 0.58)
                i = int(x * (W - 1))
                y = (lv["rpe_top"][i] + 0.025 + rng.uniform(0, 0.04)) * H
                cv2.ellipse(img, (int(x * W), int(y)), (int(rng.uniform(4, 9) * A.SS), int(2 * A.SS)), rng.uniform(0, 180), 0, 360,
                            (200, 46, 46), A.SS, cv2.LINE_AA)
            i = int(0.66 * (W - 1))
            cv2.ellipse(img, (int(0.66 * W), int((lv["pr_bot"][i] + lv["rpe_top"][i]) / 2 * H)),
                        (int(0.035 * W), max(2, int((lv["rpe_top"][i] - lv["pr_bot"][i]) / 2 * H))), 0, 0, 360,
                        A.HEME, -1, cv2.LINE_AA)
        s.sub_rpe = (0.07 * np.clip(1 - ((s.x - 0.515) / 0.075) ** 2, 0, 1) ** 0.6).astype(np.float32)
        s.sub_rpe_color = (150, 140, 110)
        s.sub_ret = (0.06 * np.clip(1 - ((s.x - 0.52) / 0.19) ** 2, 0, 1) ** 0.7).astype(np.float32)
        s.cysts = [(0.44, 0.65, 0.02, 0.05), (0.58, 0.6, 0.018, 0.045)]
        s.extras.append(cnv)
        s.mark(0.515, ("rpe_top", 0.04), "신생혈관")
        s.mark(0.38, ("pr_bot", 0.012), "망막 밑 액체")
        s.mark(0.66, ("pr_bot", 0.0), "출혈")
        sight = Sight(center_dark=0.92, center_r=0.13, warp=0.9, center_blur=5, center_tint=(44, 30, 28))
    return f, s, sight


# -- 녹내장 -------------------------------------------------------------------------------------------
def _glaucoma(stage):
    cup = G.STAGE_CUP[stage]
    f = Fundus(look=Look(seed=13, cup=cup, notch=(0, 0.6, 0.8, 0.3)[stage], disc_pale=(0, 0, 0.15, 0.4)[stage]))
    if stage >= 1:
        for lo, hi, gain in ((212, 238, 0.78), (122, 146, 0.80))[: 1 if stage == 1 else 2]:
            m = _sector_mask(f, DISC, lo, hi, DISC_R * 1.1, 0.85, 0.02)
            f.tone(m * np.clip(1 - f.dist(DISC) / 0.9, 0, 1) ** 0.3, gain)
        f.mark(*(np.array(DISC) + 0.42 * np.array([math.cos(math.radians(225)), -math.sin(math.radians(225))])),
               "신경섬유층 결손")
    if stage == 1:
        p = (DISC[0] - 0.05, DISC[1] + 0.12)
        f.flames([p], 0.03)
        f.mark(*p, "유두 출혈")
    f.mark(DISC[0] - 0.01, DISC[1] - 0.01, "커진 함몰 (컵)" if stage else "함몰 (컵)")
    f.mark(DISC[0] + 0.03, DISC[1] - 0.12, "림 (신경 조직)" if stage < 2 else "얇아진 림")
    s = Section(through="disc")
    s.disc_cup = cup
    s.nfl_scale = (1.0, 0.75, 0.5, 0.28)[stage]
    s.mark(0.5, ("surface", 0.0), "함몰 (컵)")
    s.mark(0.30, ("surface", 0.0), "신경섬유층" if stage < 2 else "얇아진 신경섬유층")
    s.mark(0.5, 0.92, "시신경 (뇌로)")
    return f, s, G.field_simulation(stage, 600, _scene())


# -- 망막정맥폐쇄 --------------------------------------------------------------------------------------
def _rvo(stage):
    if stage == 0:
        f = Fundus(look=Look(seed=17, tortuous=0.7, tortuous_only=("STV",), vein_w=1.35, vein_wide_only=("STV",)))
        cross = f.crossing("STA", "STV")
        at = cross[0] if cross else f.vessel_point("STV", 0.3)
        p = f.paths["STV"]
        k0 = int(np.argmin(np.hypot(p[:, 0] - at[0], p[:, 1] - at[1])))
        frac0 = k0 / (len(p) - 1)
        fl = f.near_vessels(46, ("STV",), 0.07, frac0 + 0.02, 0.95)
        fl += f.scatter(26, (-0.35, -0.42), 0.32, sector=(95, 175), about=DISC)
        f.flames(fl, 0.034)
        f.blots(f.scatter(10, (-0.3, -0.35), 0.3, sector=(95, 175), about=DISC))
        cws = [f.vessel_point("STV", min(0.95, frac0 + 0.15)), f.vessel_point("STA", 0.55)]
        cws = [(u, v + 0.05) for u, v in cws]
        f.cotton_wool(cws, 0.03)
        ex = f.scatter(12, (FOVEA[0] + 0.02, FOVEA[1] - 0.09), 0.05)
        f.exudates(ex, 0.007)
        f.mark(*at, "막힌 곳 (동정맥 교차)")
        f.mark(*fl[3], "불꽃 모양 출혈")
        f.mark(*cws[0], "면화반")
        f.mark(*f.vessel_point("STV", min(0.9, frac0 + 0.3)), "굵고 구불구불한 정맥")
        f.mark(*ex[0], "황반부종 · 삼출물")
        sight = Sight(sector=(185, 345, 0.6, 0.06), center_blur=3.5, center_off=(0, 0.04))
    else:
        f = Fundus(look=Look(seed=19, tortuous=0.85, vein_w=1.45, disc_swell=0.4, cup=0.12))
        rng = f.rng
        fl = []
        for _ in range(150):
            a = rng.uniform(0, 2 * math.pi)
            r = DISC_R * 1.3 + abs(rng.normal(0, 0.45))
            u, v = DISC[0] + r * math.cos(a) * 1.25, DISC[1] + r * math.sin(a)
            if math.hypot(u, v) < 0.93 and math.hypot(u - FOVEA[0], v - FOVEA[1]) > 0.05:
                fl.append((u, v))
        f.flames(fl, 0.036)
        f.blots(f.scatter(30, (0.0, 0.0), 0.9, avoid=FOVEA, avoid_r=0.06), 0.02)
        cws = f.near_vessels(7, ("STA", "ITA", "SNA", "INA"), 0.04, 0.15, 0.5)
        f.cotton_wool(cws, 0.03)
        m = f.mask()
        f.ellipse(m, *FOVEA, 0.12, 0.10)
        f.paint(m, (232, 168, 120), 0.2, blur=0.03)
        f.mark(*fl[5], "사방으로 퍼진 출혈")
        f.mark(DISC[0] + 0.02, DISC[1] - 0.10, "부은 시신경 유두")
        f.mark(*cws[0], "면화반")
        f.mark(*f.vessel_point("ITV", 0.6), "굵고 구불구불한 정맥")
        f.mark(FOVEA[0], FOVEA[1] + 0.04, "황반부종")
        sight = Sight(blur=3.0, center_dark=0.45, center_r=0.2, center_tint=(70, 44, 40), dim=0.12, center_blur=5)
    s = Section()
    s.inner_t = s.inner_t + 0.09 * _gauss(s.x, 0.5, 0.15)
    s.cysts = [(0.44, 0.55, 0.022, 0.05), (0.5, 0.45, 0.02, 0.06), (0.56, 0.6, 0.025, 0.05)]
    s.extras.append(lambda img, sec: _in_retina(img, sec, [(0.18, 0.2), (0.25, 0.35), (0.30, 0.15), (0.72, 0.25), (0.80, 0.3),
                                                          (0.86, 0.18)] if stage else [(0.18, 0.2), (0.25, 0.35), (0.30, 0.15)],
                                                A.HEME, size=(0.02, 0.12)))
    s.mark(0.25, ("surface", 0.03), "망막 출혈")
    s.mark(0.5, ("surface", 0.08), "황반부종")
    return f, s, sight


# -- 망막동맥폐쇄 --------------------------------------------------------------------------------------
def _rao(stage):
    s = Section()
    if stage == 0:
        f = Fundus(look=Look(seed=23))
        m = _sector_mask(f, DISC, 100, 172, DISC_R * 1.25, 1.2, 0.04)
        f.paint(m * np.clip(1.15 - f.dist(FOVEA) * 0.9, 0, 1), (238, 228, 214), 0.62, under_vessels=True)
        emb = f.vessel_point("STA", 0.20)
        f.spots([emb], 0.011, (255, 246, 196), 1.0, blur=0.002)
        f.mark(*emb, "색전 (막힌 곳)")
        f.mark(-0.30, -0.38, "하얗게 부은 망막")
        f.mark(*f.vessel_point("STA", 0.6), "피가 가지 않는 동맥")
        side = s.x < 0.47
        sight = Sight(sector=(178, 300, 0.92, 0.03))
    else:
        f = Fundus(look=Look(seed=29, artery_w=0.5, fovea_reflex=False))
        whit = np.exp(-(f.dist((FOVEA[0] + 0.1, FOVEA[1])) / 0.55) ** 2) + 0.6 * np.exp(-(f.dist(DISC) / 0.35) ** 2)
        f.paint(np.clip(whit, 0, 1).astype(np.float32), (238, 230, 218), 0.66, under_vessels=True)
        m = f.mask()
        f.ellipse(m, *FOVEA, 0.045)
        f.paint(m, (196, 46, 34), 0.95, blur=0.008)
        gaps = []                                       # the blood column broken up (box-carring)
        for name in ("STV", "ITV", "STA"):
            for frac in np.linspace(0.25, 0.75, 9):
                gaps.append(f.vessel_point(name, frac))
        f.spots(gaps, 0.007, (236, 196, 170), 0.85, blur=0.002, jitter=0.1)
        f.mark(*FOVEA, "체리빛 반점")
        f.mark(-0.45, 0.12, "창백하게 부은 망막")
        f.mark(*f.vessel_point("ITA", 0.4), "가늘어진 동맥")
        f.mark(*f.vessel_point("STV", 0.5), "토막 난 혈류")
        side = np.ones_like(s.x, bool)
        sight = Sight(all_dark=0.9, blur=6)

    def pale(img, sec):
        lv = sec.levels
        H = sec.H
        yy = (np.arange(H, dtype=np.float32) / H)[:, None]
        m = ((yy >= lv["surface"][None, :]) & (yy < lv["outer_top"][None, :]) & side[None, :]).astype(np.float32)
        m = cv2.GaussianBlur(m, (0, 0), 3 * A.SS)[..., None] * 0.75
        img[:] = img * (1 - m) + np.float32([246, 240, 232]) * m
    s.inner_t = s.inner_t * np.where(side, 1.35, 1.0).astype(np.float32)
    s.extras.append(pale)
    s.mark(0.3 if stage == 0 else 0.25, ("surface", 0.05), "부어 하얘진 망막 안쪽 층")
    if stage == 1:
        s.mark(0.5, ("pr_top", 0.0), "중심와는 얇아 붉은 맥락막이 비침")
    return f, s, sight


# -- 고혈압망막병증 ------------------------------------------------------------------------------------
def _htn(stage):
    look = Look(seed=31, artery_w=(0.68, 0.6, 0.58, 0.55)[stage], wiring=(0.0, 0.65, 0.75, 0.8)[stage])
    if stage == 3:
        look.disc_swell, look.cup = 0.75, 0.0
    f = Fundus(look=look)
    f.mark(*f.vessel_point("ITA", 0.5), "가늘어진 동맥")
    if stage >= 1:
        for a, v in (("STA", "STV"), ("ITA", "ITV")):
            c = f.crossing(a, v)
            if c:
                f.nick(*c, size=0.032)
                if a == "STA":
                    f.mark(*c[0], "동정맥 교차 현상")
        f.mark(*f.vessel_point("STA", 0.75), "구리선 · 은선 동맥")
    if stage >= 2:
        fl = f.near_vessels(12, ("STV", "ITV", "SNV", "INV"), 0.04, 0.05, 0.4)
        f.flames(fl, 0.032)
        cws = f.near_vessels(6, ("STA", "ITA", "SNA"), 0.04, 0.08, 0.4)
        f.cotton_wool(cws, 0.03)
        ex = f.scatter(10, (-0.05, 0.18), 0.06)
        f.exudates(ex)
        f.mark(*fl[0], "불꽃 모양 출혈")
        f.mark(*cws[0], "면화반")
        if stage == 2:
            f.mark(*ex[0], "경성 삼출물")
    if stage == 3:
        f.star(FOVEA, 0.12, 110)
        f.mark(FOVEA[0] - 0.09, FOVEA[1] + 0.06, "황반 별 모양 삼출물")
        f.mark(DISC[0] + 0.02, DISC[1] - 0.12, "부은 시신경 유두")
    s = Section()

    def crossing(img, sec):                            # an artery with a thick wall pressing on a vein
        lv = sec.levels
        W, H = sec.W, sec.H
        x = 0.24
        i = int(x * (W - 1))
        top = lv["surface"][i] * H
        r = 0.012 * W
        cv2.ellipse(img, (int(x * W), int(top + r * 1.1)), (int(r * 1.3), int(r * (0.9 if stage else 1.1))), 0, 0, 360,
                    A.VEIN, -1, cv2.LINE_AA)
        wall = 1.0 + (0.9 if stage else 0.3)
        cv2.circle(img, (int((x + 0.02) * W), int(top - r * 0.2)), int(r * wall), (236, 196, 176), -1, cv2.LINE_AA)
        cv2.circle(img, (int((x + 0.02) * W), int(top - r * 0.2)), int(r * 0.75 * (0.75 if stage else 1)), A.ARTERY, -1, cv2.LINE_AA)
    s.extras.append(crossing)
    s.mark(0.26, ("surface", -0.07), "두꺼워진 동맥 벽")
    s.mark(0.21, ("surface", 0.09), "눌린 정맥")
    if stage >= 2:
        s.extras.append(lambda img, sec: _in_retina(img, sec, [(0.66, 0.2), (0.72, 0.3)], A.HEME, size=(0.018, 0.1)))
        s.extras.append(lambda img, sec: _in_retina(img, sec, [(0.82, 0.06), (0.835, 0.12)], A.CWS, size=(0.02, 0.1)))
        s.mark(0.68, ("surface", 0.05), "출혈")
        s.mark(0.83, ("surface", -0.02), "면화반")
    if stage == 3:
        s.inner_t = s.inner_t + 0.06 * _gauss(s.x, 0.5, 0.12)
        s.extras.append(lambda img, sec: _in_retina(img, sec, [(0.42 + 0.02 * k, 0.95) for k in range(9) if k != 4],
                                                    A.EXUDATE, layer=("inner_top", "pr_top"), size=(0.006, 0.04)))
        s.mark(0.46, ("pr_top", -0.02), "삼출물")
    sight = (Sight(), Sight(), Sight(blur=1.0), Sight(blur=2.5, center_dark=0.35, center_r=0.14, center_tint=(80, 70, 60),
                                                         center_blur=4))[stage]
    return f, s, sight


# -- 망막박리 ------------------------------------------------------------------------------------------
def _rd(stage):
    f = Fundus(look=Look(seed=37, fovea_reflex=stage < 2))
    tear = (-0.50, -0.70)
    if stage >= 1:
        far = (-0.95, -1.05)                           # it spreads from the superotemporal periphery
        radius = (0.98, 1.46)[stage - 1]
        d = f.dist(far)
        wob = 0.03 * np.sin(np.arctan2(f.V - far[1], f.U - far[0]) * 9)
        m = np.clip((radius + wob - d) / 0.02, 0, 1).astype(np.float32)
        m = cv2.GaussianBlur(m, (0, 0), 0.01 * f.R)
        f.tone(m * f.vessel_mask, 0.78)
        f.paint(m, (206, 198, 194), 0.42, under_vessels=True)
        folds = f.mask()                               # undulating folds of the loose retina
        rng = np.random.default_rng(5)
        for k in range(12):
            r0 = rng.uniform(0.25, radius - 0.08)
            a0 = rng.uniform(math.radians(-10), math.radians(100))
            pts = []
            for t in np.linspace(-0.22, 0.22, 14):
                a = a0 + t
                r = r0 + 0.025 * math.sin(t * 25 + k)
                pts.append((far[0] + r * math.cos(a), far[1] + r * math.sin(a)))
            f.polyline(folds, pts, 0.007)
        f.paint(folds * m, (244, 240, 236), 0.5, blur=0.006)
        f.mark(-0.40, -0.42, "들뜬 망막 (회색 주름)")
        ang = math.radians(28)
        f.mark(far[0] + radius * math.cos(ang), far[1] + radius * math.sin(ang), "박리 경계")
        if stage == 2:
            f.mark(FOVEA[0], FOVEA[1] + 0.02, "황반까지 떨어짐")
    # the tear: a horseshoe of bare (redder) choroid with the flap of retina on its far side
    m = f.mask()
    f.ellipse(m, *tear, 0.075, 0.05, angle=35)
    f.ellipse(m, tear[0] + 0.03, tear[1] + 0.025, 0.05, 0.03, angle=35, value=0)
    f.paint(m, (214, 74, 48), 0.95, blur=0.004)
    flap = f.mask()
    f.ellipse(flap, tear[0] + 0.035, tear[1] + 0.03, 0.05, 0.026, angle=35)
    f.paint(flap, (224, 200, 186), 0.75, blur=0.004)
    f.mark(*tear, "말굽 모양 열공")
    s = Section()
    if stage == 0:
        def tear_sec(img, sec):
            lv = sec.levels
            W, H = sec.W, sec.H
            x0 = 0.20
            i = int(x0 * (W - 1))
            flap = np.int32([(x0 * W, lv["surface"][i] * H), ((x0 + 0.03) * W, (lv["surface"][i] - 0.12) * H),
                             ((x0 + 0.06) * W, (lv["surface"][i] - 0.16) * H)])
            cv2.polylines(img, [flap], False, (224, 170, 160), int(5 * A.SS), cv2.LINE_AA)
            hy = np.int32([(x * W, (0.10 + 0.06 * (x - 0.26) ** 2 * 9) * H) for x in np.linspace(0.26, 1.0, 30)])
            cv2.polylines(img, [hy], False, (170, 186, 206), A.SS, cv2.LINE_AA)
            cv2.line(img, (int((x0 + 0.06) * W), int((lv["surface"][i] - 0.16) * H)), (int(0.26 * W), int(0.10 * H)),
                     (170, 186, 206), A.SS, cv2.LINE_AA)
        s.hole = (np.abs(s.x - 0.21) < 0.012)
        s.extras.append(tear_sec)
        s.mark(0.21, ("rpe_top", -0.02), "열공")
        s.mark(0.55, 0.08, "유리체가 당김")
        sight = Sight(spots=12, spot_size=0.03, flashes=3)
    else:
        lift = np.clip((0.40 - s.x) / 0.08, 0, 1) if stage == 1 else np.clip((0.75 - s.x) / 0.1, 0, 1)
        s.sub_ret = (0.11 * lift ** 0.7 * (1 + 0.15 * np.sin(s.x * 40))).astype(np.float32)
        s.sub_ret_color = (64, 82, 112)
        s.mark(0.20 if stage == 1 else 0.40, ("pr_bot", 0.03), "망막 밑으로 들어간 물")
        s.mark(0.12 if stage == 1 else 0.25, ("surface", 0.0), "떨어진 망막")
        s.mark(0.5, ("surface", 0.0), "황반 (붙어 있음)" if stage == 1 else "황반 (떨어짐)")
        sight = (Sight(curtain=(225, 0.72, 0.88), spots=6, spot_size=0.03) if stage == 1 else
                 Sight(curtain=(225, 1.12, 0.9), spots=6, spot_size=0.03, center_blur=8, center_dark=0.4, center_r=0.2,
                       center_tint=(60, 60, 62)))
    return f, s, sight



# -- 황반원공 ------------------------------------------------------------------------------------------
def _mh(stage):
    f = Fundus(look=Look(seed=41, fovea_reflex=False))
    s = Section()
    if stage == 0:
        m = f.mask()
        f.ellipse(m, *FOVEA, 0.024)
        f.ellipse(m, *FOVEA, 0.012, value=0.4)
        f.paint(m, (246, 210, 120), 0.75, blur=0.004)
        f.mark(*FOVEA, "중심와의 노란 고리")

        def pull(img, sec):
            lv = sec.levels
            W, H = sec.W, sec.H
            for side in (-1, 1):
                pts = np.int32([(x * W, (lv["surface"][int(0.5 * (W - 1))] - 0.01 - 0.18 * abs(x - 0.5) / 0.5) * H)
                                for x in np.linspace(0.5, 0.5 + side * 0.5, 30)])
                cv2.polylines(img, [pts], False, (176, 194, 214), A.SS, cv2.LINE_AA)
        s.inner_t = s.inner_t + 0.05 * _gauss(s.x, 0.5, 0.05)
        s.cysts = [(0.5, 0.45, 0.025, 0.07)]
        s.extras.append(pull)
        s.mark(0.70, 0.10, "유리체가 중심와를 당김")
        s.mark(0.5, ("surface", 0.07), "갈라지기 시작한 망막")
        sight = Sight(warp=0.35, center_blur=3)
    else:
        cuff = f.mask()
        f.ellipse(cuff, *FOVEA, 0.085)
        f.paint(cuff, (176, 120, 104), 0.45, blur=0.012)
        m = f.mask()
        f.ellipse(m, *FOVEA, 0.045)
        f.paint(m, (176, 44, 30), 0.97, blur=0.002)
        f.spots(f.scatter(7, FOVEA, 0.03), 0.004, (250, 230, 150), 0.9, blur=0.001)
        f.mark(*FOVEA, "황반원공")
        f.mark(FOVEA[0] + 0.07, FOVEA[1] - 0.04, "둘레의 액체 테")
        hole = np.abs(s.x - 0.5) < 0.035
        s.hole = hole
        s.inner_t = s.inner_t + 0.06 * (_gauss(s.x, 0.455, 0.035) + _gauss(s.x, 0.545, 0.035))
        s.outer_t = np.where(hole, 0, s.outer_t).astype(np.float32)
        s.cysts = [(0.445, 0.5, 0.012, 0.06), (0.555, 0.5, 0.012, 0.06), (0.43, 0.65, 0.01, 0.04), (0.57, 0.65, 0.01, 0.04)]

        def oper(img, sec):
            W, H = sec.W, sec.H
            cv2.ellipse(img, (int(0.5 * W), int(0.14 * H)), (int(0.025 * W), int(0.018 * H)), 0, 0, 360, (226, 176, 166), -1, cv2.LINE_AA)
            pts = np.int32([(x * W, (0.10 + 0.04 * math.cos((x - 0.5) * 6)) * H) for x in np.linspace(0, 1, 40)])
            cv2.polylines(img, [pts], False, (176, 194, 214), A.SS, cv2.LINE_AA)
        s.extras.append(oper)
        s.mark(0.5, ("rpe_top", -0.03), "구멍 (전층 원공)")
        s.mark(0.5, 0.14, "떨어진 덮개")
        s.mark(0.445, ("surface", 0.05), "가장자리 부종")
        sight = Sight(center_dark=0.95, center_r=0.05, pinch=0.7, center_blur=3)
    return f, s, sight


# -- 황반전막 ------------------------------------------------------------------------------------------
def _erm(stage):
    f = Fundus(look=Look(seed=43, macular_pull=(0.35, 1.0)[stage], fovea_reflex=False))
    m = f.mask()
    for du, dv, a, b in ((0.0, 0.0, 0.17, 0.13), (0.06, -0.05, 0.08, 0.06), (-0.07, 0.04, 0.09, 0.07)):
        f.ellipse(m, FOVEA[0] + du, FOVEA[1] + dv, a, b)
    f.paint(m, (250, 246, 236), (0.16, 0.30)[stage], blur=0.02, under_vessels=True)
    glint = f.mask()
    rng = np.random.default_rng(2)
    n = (6, 22)[stage]
    c = (FOVEA[0] + 0.03, FOVEA[1] - 0.01)
    for k in range(n):
        a = rng.uniform(0, 2 * math.pi)
        r0, r1 = rng.uniform(0.02, 0.05), rng.uniform(0.12, 0.22)
        pts = [(c[0] + r * math.cos(a + 0.15 * math.sin(r * 30)), c[1] + r * math.sin(a + 0.15 * math.sin(r * 30)))
               for r in np.linspace(r0, r1, 8)]
        f.polyline(glint, pts, 0.0035)
    f.paint(glint, (255, 252, 240), (0.35, 0.55)[stage], blur=0.003)
    f.mark(FOVEA[0] - 0.10, FOVEA[1] + 0.07, "셀로판 같은 막")
    if stage == 1:
        f.mark(c[0] + 0.12, c[1] - 0.06, "방사상 주름")
        f.mark(*f.vessel_point("ITA", 0.45), "끌려간 혈관")
    s = Section()
    s.inner_t = (s.inner_t + (0.04, 0.10)[stage] * _gauss(s.x, 0.5, 0.16) +
                 (0.006, 0.015)[stage] * np.sin(s.x * 90)).astype(np.float32)
    if stage == 1:
        s.cysts = [(0.48, 0.6, 0.015, 0.04), (0.53, 0.55, 0.012, 0.035)]

    def membrane(img, sec):
        lv = sec.levels
        W, H = sec.W, sec.H
        pts = np.int32([(x * W, (lv["surface"][int(x * (W - 1))] - 0.012) * H) for x in np.linspace(0.22, 0.78, 60)])
        cv2.polylines(img, [pts], False, (250, 250, 246), int((2 if stage == 0 else 3) * A.SS), cv2.LINE_AA)
    s.extras.append(membrane)
    s.mark(0.32, ("surface", -0.03), "망막 앞의 막")
    s.mark(0.5, ("surface", 0.05), "주름지고 두꺼워진 망막" if stage else "얕아진 중심와")
    sight = (Sight(warp=0.35, center_blur=1.5), Sight(warp=1.0, center_blur=3, shrink=-0.3))[stage]
    return f, s, sight


# -- 중심장액맥락망막병증 ------------------------------------------------------------------------------
def _csc(stage):
    f = Fundus(look=Look(seed=47, fovea_reflex=False))
    c = (FOVEA[0] + 0.01, FOVEA[1] - 0.01)
    r = (0.16, 0.11)[stage]
    m = f.mask()
    f.ellipse(m, *c, r, r * 0.9)
    f.tone(m, 0.88, blur=0.01)
    f.paint(m, (214, 176, 120), 0.14, blur=0.01)
    ring = f.mask()
    f.ellipse(ring, *c, r, r * 0.9)
    f.ellipse(ring, *c, r - 0.008, r * 0.9 - 0.008, value=0)
    f.paint(ring, (255, 240, 214), 0.45, blur=0.004)
    f.mark(c[0] - r * 0.7, c[1] + r * 0.55, "장액성 망막박리 (물집)")
    leak = (c[0] + 0.05, c[1] - 0.03)
    f.spots([leak], 0.008, (252, 236, 190), 0.9, blur=0.002)
    f.mark(*leak, "새는 곳")
    s = Section()
    s.choroid_t = np.full_like(s.choroid_t, 0.22)
    if stage == 1:
        rng = np.random.default_rng(8)
        mott = f.scatter(40, (c[0], c[1] + 0.12), 0.18) + [(c[0] + rng.normal(0, 0.03), c[1] + t) for t in np.linspace(0.15, 0.55, 18)]
        f.spots(mott[::2], 0.008, A.PIGMENT, 0.55, blur=0.003)
        f.spots(mott[1::2], 0.010, (236, 190, 140), 0.55, blur=0.003)
        f.mark(c[0] + 0.02, c[1] + 0.40, "아래로 흘러내린 자국")
        f.mark(c[0] - 0.12, c[1] + 0.17, "얼룩덜룩한 색소상피")
    s.sub_ret = ((0.085, 0.045)[stage] * np.clip(1 - ((s.x - 0.5) / (0.20, 0.15)[stage]) ** 2, 0, 1) ** 0.6).astype(np.float32)
    s.sub_ret_color = (86, 104, 128)
    s.sub_rpe = (0.025 * _gauss(s.x, 0.56, 0.014)).astype(np.float32)
    s.sub_rpe_color = (90, 110, 136)
    if stage == 1:
        s.pr_loss = (0.45 * np.clip(1 - np.abs(s.x - 0.5) / 0.16, 0, 1)).astype(np.float32)

    def arrow(img, sec):
        lv = sec.levels
        W, H = sec.W, sec.H
        i = int(0.56 * (W - 1))
        y0, y1 = lv["bruch"][i] * H + 4 * A.SS, (lv["rpe_top"][i] - 0.04) * H
        cv2.arrowedLine(img, (int(0.56 * W), int(y0)), (int(0.56 * W), int(y1)), (120, 210, 255), int(2.5 * A.SS),
                        cv2.LINE_AA, tipLength=0.3)
    s.extras.append(arrow)
    s.mark(0.42, ("pr_bot", 0.02), "망막 밑에 고인 액체")
    s.mark(0.56, ("rpe_top", 0.0), "새는 곳 (색소상피)")
    s.mark(0.25, ("choroid_bottom", -0.08), "두꺼운 맥락막")
    sight = (Sight(center_dark=0.45, center_r=0.16, center_tint=(112, 98, 70), shrink=0.5, center_blur=4),
             Sight(center_dark=0.55, center_r=0.13, center_tint=(96, 84, 64), shrink=0.4, center_blur=4, warp=0.35))[stage]
    return f, s, sight


# -- 병적 근시 -----------------------------------------------------------------------------------------
def _myopia(stage):
    f = Fundus(look=Look(seed=53, tessellate=0.95, disc_tilt=1.0, pale_bg=0.45, artery_w=0.85, vein_w=0.85, branches=0.8))
    rx, ry = f.disc_rx, f.disc_ry
    d = np.hypot((f.U - DISC[0]) / rx, (f.V - DISC[1]) / ry)
    width = (0.38, 0.8)[stage]
    crescent = ((d > 0.98) & (d < 1.0 + width) & (f.U < DISC[0] - rx * (0.2 - 0.3 * stage))).astype(np.float32)
    f.paint(crescent, (240, 222, 192), 0.9, blur=0.004)
    edge = ((d > 0.98 + width) & (d < 1.06 + width) & (f.U < DISC[0] - rx * 0.1)).astype(np.float32)
    f.paint(edge, (90, 50, 30), 0.6, blur=0.003)
    f.mark(-0.55, -0.55, "호피 무늬 안저")
    f.mark(DISC[0] + 0.04, DISC[1] - 0.14, "기울어진 시신경 유두")
    f.mark(DISC[0] - rx * (1.0 + width * 0.6), DISC[1] + 0.06, "근시성 반월")
    s = Section()
    s.bow = (0.10 * _gauss(s.x, 0.5, 0.42) - 0.10 * _gauss(np.float32(0.0), 0.5, 0.42)).astype(np.float32)
    s.choroid_t = np.full_like(s.choroid_t, 0.06)
    s.inner_t = s.inner_t * 0.82
    s.outer_t = s.outer_t * 0.85
    s.mark(0.20, ("choroid_bottom", -0.03), "얇아진 맥락막")
    s.mark(0.85, ("choroid_bottom", 0.06), "뒤로 늘어난 눈벽")
    if stage == 0:
        sight = Sight()
    else:
        cracks = f.mask()
        rng = np.random.default_rng(12)
        for k in range(5):
            p = (FOVEA[0] + rng.uniform(-0.15, 0.1), FOVEA[1] + rng.uniform(-0.12, 0.12))
            a = rng.uniform(0, math.pi)
            pts = [p]
            for _ in range(5):
                a += rng.normal(0, 0.4)
                pts.append((pts[-1][0] + 0.03 * math.cos(a), pts[-1][1] + 0.03 * math.sin(a)))
            f.polyline(cracks, pts, 0.004)
        f.paint(cracks, (246, 226, 170), 0.8, blur=0.002)
        f.mark(FOVEA[0] - 0.12, FOVEA[1] - 0.12, "래커 균열")
        atro = f.mask()
        rng2 = np.random.default_rng(21)
        for u, v, a, b in ((-0.48, 0.10, 0.06, 0.045), (-0.43, 0.17, 0.035, 0.03), (0.04, 0.20, 0.04, 0.03)):
            for _ in range(4):
                f.ellipse(atro, u + rng2.normal(0, a * 0.35), v + rng2.normal(0, b * 0.35), a * rng2.uniform(0.5, 0.9),
                          b * rng2.uniform(0.5, 0.9), rng2.uniform(0, 180))
        f.paint(atro, (244, 232, 210), 0.92, blur=0.003)
        rim = cv2.dilate(atro, np.ones((7, 7), np.uint8)) - atro
        f.paint(rim, (70, 36, 22), 0.7, blur=0.002)
        f.mark(-0.48, 0.10, "망막맥락막 위축")
        fs = f.mask()
        f.ellipse(fs, *FOVEA, 0.03)
        f.paint(fs, (40, 26, 22), 0.9, blur=0.005)
        f.spots([(FOVEA[0] + 0.03, FOVEA[1] + 0.02)], 0.018, A.HEME, 0.8, blur=0.004)
        f.mark(*FOVEA, "푹스 반점 (신생혈관)")
        s.pr_loss = (np.clip(1 - np.abs(s.x - 0.28) / 0.06, 0, 1) ** 0.3).astype(np.float32)
        s.rpe_loss = s.pr_loss
        s.sub_rpe = (0.035 * np.clip(1 - ((s.x - 0.5) / 0.04) ** 2, 0, 1) ** 0.6).astype(np.float32)
        s.sub_rpe_color = (60, 48, 40)
        s.sub_ret = (0.02 * np.clip(1 - ((s.x - 0.5) / 0.07) ** 2, 0, 1)).astype(np.float32)
        s.mark(0.28, ("pr_top", 0.0), "위축")
        s.mark(0.5, ("rpe_top", 0.02), "근시성 신생혈관")
        sight = Sight(center_dark=0.75, center_r=0.10, warp=0.6, center_tint=(36, 30, 28), center_blur=3)
    return f, s, sight


# -- 시신경 유두부종 -----------------------------------------------------------------------------------
def _papilledema(stage):
    look = Look(seed=59, disc_swell=(0.4, 1.0, 0.25)[stage], cup=(0.12, 0.0, 0.0)[stage],
                disc_pale=(0.0, 0.0, 0.85)[stage], vein_w=(1.1, 1.3, 0.9)[stage], tortuous=(0.1, 0.3, 0.0)[stage],
                artery_w=(1.0, 1.0, 0.75)[stage])
    f = Fundus(look=look)
    if stage == 1:
        rng = f.rng
        fl = []
        for _ in range(14):
            a = rng.uniform(0, 2 * math.pi)
            r = f.disc_rx * rng.uniform(1.05, 1.5)
            fl.append((DISC[0] + r * math.cos(a), DISC[1] + r * math.sin(a)))
        f.flames(fl, 0.03)
        cws = [(DISC[0] - 0.05, DISC[1] - 0.20), (DISC[0] + 0.02, DISC[1] + 0.21)]
        f.cotton_wool(cws, 0.028)
        paton = f.mask()
        for k in range(3):
            r = f.disc_rx * (1.15 + 0.1 * k)
            pts = [(DISC[0] + r * math.cos(math.radians(a)), DISC[1] + r * math.sin(math.radians(a))) for a in np.linspace(140, 220, 16)]
            f.polyline(paton, pts, 0.003)
        f.paint(paton, (246, 210, 190), 0.45, blur=0.002)
        f.mark(DISC[0] + 0.02, DISC[1] - 0.02, "부풀어 오른 유두")
        f.mark(DISC[0] + f.disc_rx * 0.95, DISC[1] + f.disc_ry * 0.4, "부종에 가려진 혈관")
        f.mark(*fl[0], "유두 둘레 출혈")
        f.mark(*cws[0], "면화반")
    elif stage == 0:
        f.mark(DISC[0] + f.disc_rx, DISC[1], "흐려진 유두 경계")
        f.mark(DISC[0] - 0.02, DISC[1] - 0.03, "붉어진 유두")
    else:
        f.mark(DISC[0], DISC[1], "창백한 유두 (위축)")
        f.mark(*f.vessel_point("STA", 0.4), "가늘어진 동맥")
    s = Section(through="disc")
    s.disc_cup = (0.12, 0.0, 0.08)[stage]
    s.disc_swell = (0.4, 1.0, 0.12)[stage]
    s.nfl_scale = (1.15, 1.5, 0.45)[stage]
    s.mark(0.5, ("surface", 0.0), "부은 시신경 유두" if stage < 2 else "위축된 시신경")
    s.mark(0.30, ("surface", 0.0), "부은 신경섬유층" if stage < 2 else "얇아진 신경섬유층")
    s.mark(0.5, 0.92, "시신경 (뇌압이 전해짐)")
    sight = (Sight(blind_spot=0.08), Sight(blind_spot=0.15, blur=1.0, dim=0.06),
             Sight(tunnel=0.78, blind_spot=0.12, desat=0.35, blur=1.5))[stage]
    return f, s, sight


# -- 망막색소변성 --------------------------------------------------------------------------------------
def _rp(stage):
    look = Look(seed=61, artery_w=(0.85, 0.6, 0.45)[stage], vein_w=(0.95, 0.75, 0.6)[stage],
                disc_pale=(0.1, 0.4, 0.85)[stage], pale_bg=(0.0, 0.15, 0.3)[stage], branches=(1.0, 0.7, 0.45)[stage])
    f = Fundus(look=look)
    n, inner = (30, 95, 190)[stage], (0.62, 0.42, 0.30)[stage]
    pts = f.scatter(n, (0.0, 0.0), 0.94, inner=inner)
    f.pigment_spicules(pts, 0.032)
    f.mark(*pts[0], "뼈 조각 모양 색소")
    f.mark(*f.vessel_point("STA", 0.5), "가늘어진 혈관" if stage < 2 else "아주 가는 혈관")
    if stage >= 1:
        f.mark(DISC[0] + 0.03, DISC[1] - 0.12, "창백해지는 유두" if stage == 1 else "밀랍 같은 창백한 유두")
    s = Section()
    r0 = (0.36, 0.24, 0.12)[stage]
    s.pr_loss = np.clip((np.abs(s.x - 0.5) - r0) / 0.08, 0, 1).astype(np.float32)
    s.rpe_loss = (0.3 * s.pr_loss).astype(np.float32)

    def migrate(img, sec):
        rng = np.random.default_rng(14)
        pts = []
        for _ in range((5, 10, 16)[stage]):
            x = rng.choice([rng.uniform(0.0, 0.5 - r0 - 0.04), rng.uniform(0.5 + r0 + 0.04, 1.0)])
            pts.append((x, rng.uniform(0.35, 0.9)))
        _in_retina(img, sec, pts, A.PIGMENT, layer=("inner_top", "pr_bot"), size=(0.007, 0.05))
    s.extras.append(migrate)
    s.mark(0.08, ("pr_top", 0.02), "시세포가 줄어든 곳")
    s.mark(0.5, ("pr_top", 0.02), "남은 시세포 (가운데)")
    s.mark(0.9, ("inner_top", 0.0), "망막으로 옮겨 간 색소")
    sight = (Sight(dim=0.25, ring=(0.80, 0.12, 0.55)), Sight(ring=(0.55, 0.16, 0.92), tunnel=1.0, dim=0.2),
             Sight(tunnel=0.30, dim=0.15))[stage]
    return f, s, sight


RECIPES = {
    "정상 안저": _normal, "당뇨망막병증": _dr, "나이관련 황반변성": _amd, "녹내장 (시신경 유두)": _glaucoma,
    "망막정맥폐쇄": _rvo, "망막동맥폐쇄": _rao, "고혈압망막병증": _htn, "망막박리": _rd, "황반원공": _mh,
    "황반전막": _erm, "중심장액맥락망막병증": _csc, "병적 근시": _myopia, "시신경 유두부종": _papilledema,
    "망막색소변성": _rp,
}


def _resolve_marks(sec: Section) -> list:
    """Section notes as pixels of the finished section (levels named, or fractions)."""
    out = []
    for x, y, label in sec.marks:
        if isinstance(y, tuple):
            key, dy = y
            i = int(np.clip(x, 0, 1) * (sec.W - 1))
            y = float(sec.levels[key][i]) + dy if key != "surface" else float(sec.y_surface[i]) + dy
        out.append(A.Mark(x * sec.width, float(np.clip(y, 0.04, 0.96)) * sec.height, label))
    return out


@lru_cache(maxsize=48)
def picture(name: str, stage: int = 0) -> Picture:
    """The explanation picture of a disease of ``DISEASES`` at ``stage``."""
    d = BY_NAME[name]
    stage = max(0, min(len(d.stages) - 1, int(stage)))
    f, s, sight = RECIPES[name](stage)
    fundus = f.finish()
    section = s.draw()
    view = sight if isinstance(sight, np.ndarray) else A.vision(_scene(), sight)
    grid = A.amsler(sight) if (stage in d.amsler and not isinstance(sight, np.ndarray)) else None
    layers = []
    if s.through == "fovea":
        mid = 0.035
        lv = s.levels
        for key, label in A.LAYER_NAMES:
            i = int(mid * (s.W - 1))
            if key == "vitreous":
                y = 0.10
            elif key == "inner":
                y = (lv["surface"][i] + lv["outer_top"][i]) / 2
            elif key == "pr":
                y = (lv["pr_top"][i] + lv["pr_bot"][i]) / 2
            elif key == "rpe":
                y = (lv["rpe_top"][i] + lv["bruch"][i]) / 2
            elif key == "choroid":
                y = (lv["bruch"][i] + lv["choroid_bottom"][i]) / 2
            else:
                y = (lv["choroid_bottom"][i] + 1.0) / 2
            layers.append(A.Mark(mid * s.width, float(y) * s.height, label))
    title = "단면 — 중심와를 지나게 자른 망막" if s.through == "fovea" else "단면 — 시신경 유두를 지나게 자른 모습"
    pic = Picture(d, stage, fundus, f.finished_marks(), section, _resolve_marks(s), title, view, grid, layers)
    if s.through == "disc":                    # the disc matters: show it larger
        pic.inset, pic.inset_box = f.crop(DISC[0], DISC[1], 0.24, 300)
    return pic
