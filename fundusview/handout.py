"""환자용 한 장 요약: one page the patient takes home — today's photo(s), the explanation picture of the
disease talked about, where the marked lesions lie in what the patient sees, and a line or two from the
doctor. ``ui/patient_views.py`` draws it (a preview, a PDF, the printer); here is what goes on it.

The page is for explaining: the disease picture is a model (it says so), and the page carries the name of
the patient — it is handed to the patient, not sent anywhere by the program.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

MEMO_MAX = 300              # characters of the doctor's note
MEMO_LINES = 5
TITLE = "안저 검사 설명 자료"
NOTE_MODEL = "설명용 모형입니다 — 환자분의 실제 상태와 다를 수 있습니다."
FOOTER = ("이 자료는 진료 때 들으신 설명을 돕기 위한 것으로, 진단서나 소견서가 아닙니다. "
          "증상이 달라지면 예약일 전이라도 병원에 연락하세요.")


@dataclass
class Handout:
    patient: str = ""                               # "홍길동 · ID 1234"
    exam: str = ""                                  # "검사일 2026-11-28"
    issued: str = ""                                # the day the page was made
    photos: list = field(default_factory=list)      # [(rgb, caption), …] — one or two
    disease: str | None = None                      # a name of diseases.DISEASES, or None
    stage: int = 0
    sight: np.ndarray | None = None                 # fieldsim.simulate(…) of the photo's pins
    sight_lines: list = field(default_factory=list)
    memo: str = ""


def clean_memo(text: str | None) -> str:
    """The doctor's note as it goes on the page: no empty lines, at most ``MEMO_LINES`` lines and
    ``MEMO_MAX`` characters."""
    lines = [" ".join(ln.split()) for ln in (text or "").splitlines()]
    return "\n".join([ln for ln in lines if ln][:MEMO_LINES])[:MEMO_MAX]


def file_stem(patient_id: str | None, day: str | None) -> str:
    """The name a page is saved under: "1234_설명자료_2026-11-28"."""
    return "_".join(x for x in ((patient_id or "").strip(), "설명자료", (day or "").strip()) if x)
