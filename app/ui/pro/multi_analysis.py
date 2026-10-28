"""멀티 화면 '분석' 탭 — 측정 종류를 하나 고르고 '측정 실행' → 결과 → '코멘트에 기록' · '결과 영상 저장'.

Pro 검토의 '분석'(형광 염색 면적 · 충혈 지수 · 백내장 혼탁 지수) 과 '정밀 분석'(영상 품질 · 형광염색 · 결막 충혈 ·
마이봄샘 · 수정체) 을 한 흐름으로 합쳤다. 측정은 누른 칸(노란 테두리)에서, 편집 탭 '원' 주석을 그리면 그 안만.
- 정밀 종류(clinical.KINDS): AnalysisPanel 의 분석 그대로 — 결과 표 · 결과 표시를 합성한 '결과 영상 저장'.
- 빠른 측정 · 백내장: ProWorkspace 의 measure_* — 표시 레이어는 저장본에 들어가지 않고, 백내장은 촬영 조건 · LOCS 와 함께
  '측정 기록' 으로 저장한다.
종류에 따라 필요한 것만 보인다 (충혈 민감도 · 마이봄샘 옵션 · 백내장 기록 칸).
ProWorkspace 가 쓰는 AnalysisTab 의 이름(lbl_tag · lbl_result · lbl_cat · s_red_sens · trend · locs · e_cond …)을 그대로 둬
측정 로직은 Pro 검토와 같다. 비교 화면 · LIVE 전용 조각(고스트 · 깜빡임 · 촬영 가이드)은 만들어만 두고 보이지 않는다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.analysis import clinical
from app.ui.pro.analysis_panel import DISCLAIMER, AnalysisPanel
from app.ui.pro.smart_panel import RednessSlider, _muted, _sub, locs_inputs

QUICK = ("fluo_quick", "redness")
CATARACT = ("nuclear", "cortical")
# (종류, 콤보 글자, 실행 전 안내)
KINDS = [
    ("quality", "영상 품질", "초점 · 노출 · 반사 — 촬영이 잘 됐는지 (전체 또는 '원' 안)"),
    ("fluorescein", "형광염색 — 각막 손상", "코발트블루 + 형광 염색 사진 · 염색 면적 · 병변 수 · Oxford 참고 등급"),
    ("hyperemia", "결막 충혈 — 혈관 · 등급", "혈관 면적 · 붉은기 · 참고 등급 (0~4) — '원' 으로 결막만 둘러 측정"),
    ("meibography", "마이봄샘 (IR)", "적외선 마이봄샘 사진 · 샘 탈락 % · Meiboscore — 샘 부위를 '원' 으로"),
    ("lens", "수정체 혼탁 (참고)", "슬릿 단면 사진 · 수정체 핵을 '원' 으로 — 밝기 L* · 황색도 b* (경과 비교용)"),
    ("fluo_quick", "형광 염색 면적 (빠른)", "녹색 형광 화소의 면적 · 비율 (눈금 보정 시 mm²)"),
    ("redness", "충혈 지수 (빠른)", "붉은 기 0~100 · 혈관 화소 % — 아래 민감도로 붉은 화소 기준을 조절"),
    ("nuclear", "백내장 핵 혼탁 — 슬릿", "슬릿 단면 사진 · 수정체 띠 밝기 ÷ 각막 띠 밝기 → 0~100"),
    ("cortical", "백내장 피질 혼탁 — 역조명", "역조명 사진 · 먼저 '원' 으로 동공을 표시 → 동공 안 어두운 얼룩 %"),
]
_HINTS = {k: h for k, _t, h in KINDS}


class MultiAnalysisPanel(AnalysisPanel):
    rednessSensitivityChanged = Signal(int)      # 충혈 민감도 1~10

    # ---- 배치 ----
    def _build_ui(self) -> None:
        ws = self.ws
        self._can_record = True
        self._quick_kind = None                   # 마지막으로 성공한 빠른 측정 · 백내장 종류
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 8, 4, 4)
        lay.setSpacing(6)

        lay.addWidget(_muted("누른 칸(노란 테두리)에서 측정 · 편집 탭 '원' 을 그리면 그 안만"))
        self.lbl_tag = _muted("조명 추정: -")
        lay.addWidget(self.lbl_tag)

        lay.addWidget(_sub("측정 종류"))
        self.c_kind = QComboBox()
        self.c_kind.setToolTip("위 다섯 개는 결과 표 · 결과 영상 저장이 되는 정밀 종류, 아래는 빠른 측정 · 백내장 지수")
        for key, text, _hint in KINDS:
            self.c_kind.addItem(text, key)
        lay.addWidget(self.c_kind)
        self.lbl_hint = _muted("")
        lay.addWidget(self.lbl_hint)
        self.chk_dark = QCheckBox("샘이 어둡게 보임 (투과 조명)")
        lay.addWidget(self.chk_dark)
        self.red = RednessSlider()
        self.s_red_sens, self.lbl_red_sens = self.red.slider, self.red.label
        lay.addWidget(self.red)

        g = QGridLayout()
        g.setSpacing(4)
        self.b_run = ws._btn("측정 실행", "누른 칸의 사진을 위 종류로 측정", obj="ProPrimary")
        self.b_clear = ws._btn("표시 지우기", "사진 위 측정 표시 · 결과 지우기")
        g.addWidget(self.b_run, 0, 0)
        g.addWidget(self.b_clear, 0, 1)
        lay.addLayout(g)

        lay.addWidget(_sub("결과"))
        self.lbl_result = QLabel("-")             # 빠른 측정은 글, 정밀 종류는 표 (AutoText)
        self.lbl_result.setWordWrap(True)
        self.lbl_result.setObjectName("AnalysisResult")
        self.lbl_cat = self.lbl_result             # 백내장 결과도 같은 칸 (ProWorkspace 호환)
        lay.addWidget(self.lbl_result)
        self.lbl_warn = QLabel("")
        self.lbl_warn.setWordWrap(True)
        self.lbl_warn.setStyleSheet("color:#f5b94a;")
        lay.addWidget(self.lbl_warn)
        g2 = QGridLayout()
        g2.setSpacing(4)
        self.b_note = ws._btn("코멘트에 기록", "")
        self.b_save = ws._btn("결과 영상 저장", "")
        g2.addWidget(self.b_note, 0, 0)
        g2.addWidget(self.b_save, 0, 1)
        lay.addLayout(g2)

        # 백내장 측정 기록 — 핵 · 피질 종류일 때만
        self.cat_box = QWidget()
        cl = QVBoxLayout(self.cat_box)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)
        cl.addWidget(_sub("백내장 측정 기록"))
        self.e_cond = QLineEdit()
        self.e_cond.setPlaceholderText("촬영 조건 (예: 슬릿 0.2mm · 45° · 16×)")
        self.e_cond.setToolTip("지수는 같은 조건에서만 비교 의미가 있습니다. 다음 검사 때 LIVE 가이드에 표시됩니다.")
        cl.addWidget(self.e_cond)
        cl.addWidget(_muted("LOCS III 의사 입력 (1~6 · 0 = 미입력)"))
        g4 = QGridLayout()
        g4.setSpacing(4)
        self.locs = locs_inputs(g4)
        cl.addLayout(g4)
        self.trend = QLabel()
        self.trend.setFixedSize(236, 64)
        self.trend.setObjectName("Histogram")
        self.trend.setToolTip("이 환자 · 같은 안구의 혼탁 지수 경과 (보라 = 핵, 빨강 = 피질)")
        cl.addWidget(self.trend)
        self.lbl_trend = _muted("")
        cl.addWidget(self.lbl_trend)
        lay.addWidget(self.cat_box)

        lay.addWidget(_sub("사진 고르기 · 내보내기"))
        g3 = QGridLayout()
        g3.setSpacing(4)
        self.b_best = ws._btn("가장 선명한 칸", "멀티 칸 가운데 가장 선명한 사진을 편집 대상(노란 테두리)으로")
        self.b_tbut = ws._btn("TBUT (동영상)", "형광염색 동영상에서 눈물막 파괴 시간 측정")
        self.b_dicom = ws._btn("DICOM 저장", "멀티 칸의 환자 사진 원본을 Ophthalmic Photography(OP) DICOM 으로 내보내기 — PACS 연동")
        g3.addWidget(self.b_best, 0, 0)
        g3.addWidget(self.b_tbut, 0, 1)
        g3.addWidget(self.b_dicom, 1, 0, 1, 2)
        lay.addLayout(g3)
        lay.addWidget(_muted(DISCLAIMER))
        lay.addStretch(1)

        # Pro 검토 전용(비교 · LIVE) 조각 — ProWorkspace 가 참조하므로 만들어만 둔다 (보이지 않음)
        self.chk_guide = QCheckBox(self)
        self.b_blink = QPushButton(self)
        self.b_blink.setCheckable(True)
        self.s_ghost = QSlider(Qt.Orientation.Horizontal, self)
        self.lbl_cmp = QLabel(self)
        for w in (self.chk_guide, self.b_blink, self.s_ghost, self.lbl_cmp):
            w.hide()

        self.c_kind.currentIndexChanged.connect(self._on_kind)
        self.b_run.clicked.connect(self.run)
        self.b_clear.clicked.connect(self.clear)
        self.b_note.clicked.connect(self.record)
        self.b_save.clicked.connect(self.save_result_image)
        self.b_best.clicked.connect(self.open_sharpest)
        self.b_tbut.clicked.connect(self._tbut_dialog)
        self.b_dicom.clicked.connect(self._dicom_dialog)
        self.red.valueChanged.connect(self.rednessSensitivityChanged)
        self._on_kind()

    # ---- 종류 ----
    def _on_kind(self, *_) -> None:
        kind = self.kind()
        cat = kind in CATARACT
        self.lbl_hint.setText(_HINTS.get(kind, ""))
        self.chk_dark.setVisible(kind == "meibography")
        self.red.setVisible(kind == "redness")
        self.cat_box.setVisible(cat)
        self.b_note.setText("측정 기록" if cat else "코멘트에 기록")
        self.b_note.setToolTip("지수 · 촬영 조건 · LOCS 입력을 이 사진의 측정 기록으로 저장하고 코멘트에 추가" if cat
                               else "측정 결과를 이 사진의 코멘트에 추가")
        self.b_save.setToolTip("결과 표시를 합성한 새 영상으로 저장 (원본 보존)" if kind in clinical.KINDS
                               else "빠른 측정 · 백내장의 표시 레이어는 저장본에 들어가지 않습니다 — "
                                    "형광염색 · 결막 충혈 같은 정밀 종류를 쓰세요")
        self.sync()

    # ---- 실행 · 지우기 · 기록 ----
    def run(self):
        ws, kind = self.ws, self.kind()
        if kind in clinical.KINDS:
            ws.clear_analysis()                   # 빠른 측정의 표시 레이어는 지움 (결과 칸은 아래서 다시 씀)
            self._quick_kind = None
            return super().run()
        self._drop_clinical()
        fn = {"fluo_quick": ws.measure_fluorescein, "redness": ws.measure_redness,
              "nuclear": ws.measure_nuclear, "cortical": ws.measure_cortical}[kind]
        r = fn()
        self._quick_kind = kind if r is not None else None
        self.sync()
        return r

    def _drop_clinical(self) -> None:
        for cv in self.ws._canvases():
            cv.set_analysis_overlay(None)
        self.result = self._result_canvas = None
        self.lbl_warn.setText("")

    def clear(self) -> None:
        super().clear()
        self.ws.clear_analysis()
        self.ws._cat = None
        self._quick_kind = None
        self.lbl_result.setText("-")
        self.sync()

    def on_view_changed(self) -> None:
        self._quick_kind = None
        super().on_view_changed()
        if not self.lbl_result.text():
            self.lbl_result.setText("-")

    def record(self) -> None:
        kind = self.kind()
        if kind in clinical.KINDS:
            self.add_to_comment()
        elif kind in CATARACT:
            self.ws.record_cataract()
        else:
            self.ws.record_measurement()
        self.sync()

    # ---- 상태 ----
    def sync(self) -> None:
        ws = self.ws
        cv = ws.active_canvas()
        has = cv is not None and cv.image() is not None
        kind = self.kind()
        clinical_kind = kind in clinical.KINDS
        own = ws.current_capture() is not None            # 환자 사진 (참조 사진 칸은 아님)
        if clinical_kind:
            have = self.result is not None and self._result_canvas is cv and self.result.kind == kind
        else:
            have = self._quick_kind == kind
        shown = self.result is not None or self._quick_kind is not None or bool(getattr(ws, "_analysis_text", ""))
        self.b_run.setEnabled(has)
        self.b_clear.setEnabled(bool(shown))
        self.b_note.setEnabled(bool(have and own and self._can_record))
        self.b_save.setEnabled(bool(have and clinical_kind and own))
        n = ws.grid_view.count() if ws.mode() == "grid" else len(ws.captures())
        self.b_best.setEnabled(n >= 2)
        self.b_tbut.setEnabled(ws._patient is not None)
        self.b_dicom.setEnabled(ws._patient is not None and bool(ws.captures()))

    def set_enabled_for(self, mode: str, can_record: bool = True) -> None:
        """기록(코멘트 · 측정 기록)은 환자 사진일 때만 — 참조 사진 칸은 측정만 (AnalysisTab 과 같은 이름)."""
        self._can_record = bool(can_record)
        self.sync()

    def set_red_sensitivity(self, v: int) -> None:
        self.red.set_value(v)

    def locs_values(self) -> dict:
        return {k: sb.value() for k, sb in self.locs.items() if sb.value() > 0}

    def set_locs(self, values: dict | None) -> None:
        for k, sb in self.locs.items():
            sb.setValue(int((values or {}).get(k, 0) or 0))
