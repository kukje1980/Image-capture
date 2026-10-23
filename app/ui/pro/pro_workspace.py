"""Pro 모드 작업공간 — 전문가용 영상 검토 화면 (VK-2 스타일 워크플로).

표시 모드
  LIVE     실시간 영상. CAPTURE(Space)로 정지/재개, SAVE로 환자 DB 저장
  1화면    단일 영상. PREV/NEXT(←/→)로 이동, 확대·이동, 보정, 텍스트/화살표 주석
  MULTI    16장(4×4) / 36장(6×6) 그리드. 클릭=비교 선택(최대 2), 더블클릭=1화면
  비교     선택한 2장 좌우 비교. 확대·스크롤 동기화, 보정 동일 적용
기타
  보정본 저장  보정·주석을 반영한 새 영상으로 저장(원본 보존, 코멘트 '보정본'/'주석')
  코멘트       영상별 코멘트 편집      환자정보  진단명·담당의 등 편집
  인쇄 / PDF   머리말·환자정보·진단명·꼬리말이 포함된 A4 보고서
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.capture.image_process import Adjust, apply_adjust
from app.ui.patient_dialog import PatientDialog
from app.ui.pro import print_util
from app.ui.pro.image_canvas import ImageCanvas
from app.ui.pro.multi_grid import MultiGrid

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

log = logging.getLogger(__name__)

MODES = ["live", "single", "multi", "compare"]
_EYE_KO = {"OD": "우안(OD)", "OS": "좌안(OS)", "OU": "양안(OU)"}
_CHANNELS = ["rgb", "green", "gray"]


def caption_of(cap, number=None, total=None) -> str:
    parts = [cap.captured_at or ""]
    eye = _EYE_KO.get(cap.eye or "", "")
    if eye:
        parts.append(eye)
    if cap.note:
        parts.append(cap.note)
    text = "  ·  ".join(p for p in parts if p)
    return f"[{number}/{total}]  {text}" if number else text


def load_bgr(path: str | None):
    if not path or cv2 is None or not os.path.exists(path):
        return None
    data = np.fromfile(path, dtype=np.uint8)          # 한글 경로 대응
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


class ProWorkspace(QWidget):
    savedCapture = Signal()
    patientUpdated = Signal(object)

    def __init__(self, db, service, config, get_eye, parent=None):
        super().__init__(parent)
        self.setObjectName("ProWorkspace")
        self.db = db
        self.service = service
        self.config = config
        self.get_eye = get_eye
        self._patient = None
        self._caps: list = []
        self._idx = -1
        self._mode = "multi"
        self._live = None
        self._frozen = False
        self._frozen_frame = None
        self._pair = (None, None)
        self._adj = Adjust()
        self._build()
        self._shortcuts()
        self.set_mode("multi")
        self._update_info()

    # ================= UI =================
    def _btn(self, text, tip, checkable=False, obj="ProBtn") -> QPushButton:
        b = QPushButton(text)
        b.setObjectName(obj)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setMinimumHeight(34)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return b

    @staticmethod
    def _sep() -> QFrame:
        f = QFrame()
        f.setObjectName("ProSep")
        f.setFixedWidth(1)
        return f

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        bar = QFrame()
        bar.setObjectName("ProToolbar")
        tl = QHBoxLayout(bar)
        tl.setContentsMargins(8, 6, 8, 6)
        tl.setSpacing(4)

        self.b_live = self._btn("LIVE", "실시간 영상", True)
        self.b_single = self._btn("1화면", "단일 영상 보기", True)
        self.b_multi = self._btn("MULTI", "다중 영상 그리드 (16/36)", True)
        self.b_cmp = self._btn("비교", "선택한 2장 나란히 비교", True)
        self.mode_group = QButtonGroup(self)
        for b, m in ((self.b_live, "live"), (self.b_single, "single"),
                     (self.b_multi, "multi"), (self.b_cmp, "compare")):
            self.mode_group.addButton(b)
            b.clicked.connect(lambda _=False, m=m: self.set_mode(m))
            tl.addWidget(b)
        tl.addWidget(self._sep())

        self.b_capture = self._btn("❄ CAPTURE", "라이브 정지/재개 (Space)", True, "ProCapture")
        self.b_save = self._btn("💾 SAVE", "정지 영상을 환자 DB에 저장")
        self.c_eye = QComboBox()
        self.c_eye.addItems(["안구 미지정", "OD 우안", "OS 좌안", "OU 양안"])
        self.c_eye.setToolTip("저장할 영상의 안구 방향")
        tl.addWidget(self.c_eye)
        tl.addWidget(self.b_capture)
        tl.addWidget(self.b_save)
        tl.addWidget(self._sep())

        self.b_prev = self._btn("◀ PREV", "이전 영상 / 페이지 (←)")
        self.b_next = self._btn("NEXT ▶", "다음 영상 / 페이지 (→)")
        self.c_per = QComboBox()
        self.c_per.addItems(["16장", "36장"])
        self.c_per.setToolTip("MULTI 표시 장수")
        tl.addWidget(self.b_prev)
        tl.addWidget(self.b_next)
        tl.addWidget(self.c_per)
        tl.addWidget(self._sep())

        # 주석 도구·보정본 저장은 사이드 패널에 배치 (툴바 폭 절약)
        self.b_pan = self._btn("✋ 이동", "이동 / 휠 확대", True)
        self.b_text = self._btn("T 텍스트", "클릭한 위치에 텍스트 주석", True)
        self.b_arrow = self._btn("↗ 화살표", "드래그해 화살표 주석", True)
        self.tool_group = QButtonGroup(self)
        for b, t in ((self.b_pan, "pan"), (self.b_text, "text"), (self.b_arrow, "arrow")):
            self.tool_group.addButton(b)
            b.clicked.connect(lambda _=False, t=t: self.set_tool(t))
        self.b_pan.setChecked(True)
        self.b_clear = self._btn("주석 지우기", "현재 화면의 주석 모두 삭제")
        self.b_edit_save = self._btn("💾 보정본 저장", "보정·주석을 반영한 새 영상으로 저장 (원본 보존)")

        self.b_comment = self._btn("코멘트", "현재 영상 코멘트 편집")
        self.b_patient = self._btn("환자정보", "진단명·담당의 등 환자 정보 편집")
        for b in (self.b_comment, self.b_patient):
            tl.addWidget(b)
        tl.addStretch(1)
        self.b_print = self._btn("🖨 인쇄", "현재 화면 영상 보고서 인쇄")
        self.b_pdf = self._btn("PDF", "PDF 보고서로 저장")
        tl.addWidget(self.b_print)
        tl.addWidget(self.b_pdf)
        root.addWidget(bar)

        body = QHBoxLayout()
        body.setSpacing(8)
        self.stack = QStackedWidget()
        self.stack.setObjectName("ProDisplay")
        self.live_canvas = ImageCanvas()
        self.live_canvas._placeholder = "라이브 영상 대기 중"
        self.single_canvas = ImageCanvas()
        self.multi = MultiGrid()
        cmp = QWidget()
        cl = QHBoxLayout(cmp)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)
        self.cmp_left = ImageCanvas()
        self.cmp_right = ImageCanvas()
        self.cmp_left.link(self.cmp_right)
        cl.addWidget(self.cmp_left)
        cl.addWidget(self.cmp_right)
        for w in (self.live_canvas, self.single_canvas, self.multi, cmp):
            self.stack.addWidget(w)
        body.addWidget(self.stack, 1)
        body.addWidget(self._build_side())
        root.addLayout(body, 1)

        self.info = QLabel()
        self.info.setObjectName("ProInfo")
        self.info.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(self.info)

        self.b_capture.toggled.connect(self._on_capture_toggled)
        self.b_save.clicked.connect(self.save_live)
        self.b_prev.clicked.connect(lambda: self.step(-1))
        self.b_next.clicked.connect(lambda: self.step(1))
        self.c_per.currentIndexChanged.connect(lambda i: self.set_per_page(36 if i == 1 else 16))
        self.b_clear.clicked.connect(self.clear_annotations)
        self.b_edit_save.clicked.connect(self.save_edited)
        self.b_comment.clicked.connect(self.edit_comment)
        self.b_patient.clicked.connect(self.edit_patient)
        self.b_print.clicked.connect(self.print_current)
        self.b_pdf.clicked.connect(self._pdf_dialog)
        self.multi.openRequested.connect(self.open_index)
        self.multi.selectionChanged.connect(self._on_selection)

    def _build_side(self) -> QFrame:
        side = QFrame()
        side.setObjectName("ProSide")
        side.setFixedWidth(260)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(8)

        h1 = QLabel("영상 정보")
        h1.setObjectName("PanelHeader")
        lay.addWidget(h1)
        self.lbl_img = QLabel("-")
        self.lbl_img.setWordWrap(True)
        self.lbl_img.setObjectName("Muted")
        lay.addWidget(self.lbl_img)

        h2 = QLabel("이미지 보정")
        h2.setObjectName("PanelHeader")
        lay.addWidget(h2)
        form = QFormLayout()
        form.setSpacing(6)
        self.s_bright = self._slider(-100, 100, 0)
        self.s_contrast = self._slider(20, 300, 100)
        self.s_gamma = self._slider(20, 300, 100)
        form.addRow("밝기", self.s_bright)
        form.addRow("대비", self.s_contrast)
        form.addRow("감마", self.s_gamma)
        self.c_channel = QComboBox()
        self.c_channel.addItems(["컬러", "Red-free (녹색)", "흑백"])
        form.addRow("채널", self.c_channel)
        self.chk_neg = QCheckBox("네거티브 (NEGA)")
        form.addRow("", self.chk_neg)
        lay.addLayout(form)

        r1 = QHBoxLayout()
        self.b_reset = QPushButton("보정 초기화")
        self.b_fit = QPushButton("화면 맞춤")
        r1.addWidget(self.b_reset)
        r1.addWidget(self.b_fit)
        lay.addLayout(r1)
        r2 = QHBoxLayout()
        self.b_zin = QPushButton("확대 +")
        self.b_zout = QPushButton("축소 −")
        r2.addWidget(self.b_zin)
        r2.addWidget(self.b_zout)
        lay.addLayout(r2)

        h_ann = QLabel("주석 · 보정본")
        h_ann.setObjectName("PanelHeader")
        lay.addWidget(h_ann)
        from PySide6.QtWidgets import QGridLayout
        g = QGridLayout()
        g.setSpacing(4)
        g.addWidget(self.b_pan, 0, 0)
        g.addWidget(self.b_text, 0, 1)
        g.addWidget(self.b_arrow, 1, 0)
        g.addWidget(self.b_clear, 1, 1)
        g.addWidget(self.b_edit_save, 2, 0, 1, 2)
        lay.addLayout(g)

        h3 = QLabel("2장 비교")
        h3.setObjectName("PanelHeader")
        lay.addWidget(h3)
        self.lbl_sel = QLabel("MULTI에서 영상 2장을 클릭해 선택한 뒤 '비교'를 누르세요.")
        self.lbl_sel.setWordWrap(True)
        self.lbl_sel.setObjectName("Muted")
        lay.addWidget(self.lbl_sel)
        lay.addStretch(1)

        for s in (self.s_bright, self.s_contrast, self.s_gamma):
            s.valueChanged.connect(self._on_adjust)
        self.c_channel.currentIndexChanged.connect(self._on_adjust)
        self.chk_neg.toggled.connect(self._on_adjust)
        self.b_reset.clicked.connect(self.reset_adjust)
        self.b_fit.clicked.connect(self._fit_all)
        self.b_zin.clicked.connect(lambda: self._zoom(1.25))
        self.b_zout.clicked.connect(lambda: self._zoom(0.8))
        return side

    @staticmethod
    def _slider(lo, hi, val) -> QSlider:
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi)
        s.setValue(val)
        return s

    def _shortcuts(self) -> None:
        for key, fn in ((Qt.Key.Key_Left, lambda: self.step(-1)),
                        (Qt.Key.Key_Right, lambda: self.step(1)),
                        (Qt.Key.Key_Space, self._space)):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)

    def _space(self) -> None:
        if self._mode == "live":
            self.b_capture.toggle()

    # ================= 데이터 =================
    def set_patient(self, patient) -> None:
        self._patient = patient
        self.multi.clear_selection()
        self.reload()
        self._update_info()

    def reload(self, select_last: bool = True) -> None:
        if self._patient is None:
            self._caps = []
        else:
            self._caps = [c for c in self.db.captures.list_by_patient(self._patient.id, order="asc")
                          if c.media_type == "photo"]
        self.multi.set_captures(self._caps)
        if select_last or not (0 <= self._idx < len(self._caps)):
            self._idx = len(self._caps) - 1
        self._show_current()
        self._update_info()

    def captures(self) -> list:
        return list(self._caps)

    def current_index(self) -> int:
        return self._idx

    def mode(self) -> str:
        return self._mode

    def _update_info(self) -> None:
        p = self._patient
        if p is None:
            self.info.setText("환자를 선택하세요")
            return
        sex = {"M": "남", "F": "여", "O": "기타"}.get(p.sex or "", "")
        bits = [f"<b>{p.name}</b> ({p.chart_no or '-'})"]
        if sex:
            bits.append(sex)
        if p.birth_date:
            bits.append(p.birth_date)
        bits.append(f"진단명: <b>{p.diagnosis or '-'}</b>")
        bits.append(f"담당의: {p.doctor or '-'}")
        bits.append(f"영상 {len(self._caps)}장")
        self.info.setText("&nbsp;&nbsp;·&nbsp;&nbsp;".join(bits))

    # ================= 모드 =================
    def set_mode(self, mode: str) -> None:
        if mode == "compare" and not self._prepare_compare():
            mode = self._mode if self._mode != "compare" else "multi"
        self._mode = mode
        self.stack.setCurrentIndex(MODES.index(mode))
        {"live": self.b_live, "single": self.b_single, "multi": self.b_multi,
         "compare": self.b_cmp}[mode].setChecked(True)
        live = mode == "live"
        self.b_capture.setEnabled(live)
        self.b_save.setEnabled(live)
        self.c_per.setEnabled(mode == "multi")
        ann = mode in ("single", "compare")
        for b in (self.b_text, self.b_arrow, self.b_clear, self.b_edit_save):
            b.setEnabled(ann)
        self.b_comment.setEnabled(mode == "single")
        if mode == "single":
            self._show_current()
        if live and self._live is not None and not self._frozen:
            self.live_canvas.set_image(self._live, keep_view=True)
        self._update_side()

    def _show_current(self) -> None:
        if not (0 <= self._idx < len(self._caps)):
            self.single_canvas.set_image(None)
            self._update_side()
            return
        cap = self._caps[self._idx]
        self.single_canvas.set_image(load_bgr(cap.file_path))
        self.single_canvas.set_adjust(self._adj)
        self.single_canvas.set_caption(caption_of(cap, self._idx + 1, len(self._caps)))
        self._update_side()

    def _update_side(self) -> None:
        if self._mode == "single" and 0 <= self._idx < len(self._caps):
            c = self._caps[self._idx]
            self.lbl_img.setText(
                f"{self._idx + 1} / {len(self._caps)}\n촬영: {c.captured_at}\n"
                f"안구: {_EYE_KO.get(c.eye or '', '미지정')}\n코멘트: {c.note or '-'}")
        elif self._mode == "multi":
            self.lbl_img.setText(
                f"페이지 {self.multi.page() + 1} / {self.multi.page_count()}  ·  "
                f"{self.multi.per_page()}장 보기\n전체 {len(self._caps)}장  ·  선택 {len(self.multi.selection())}장")
        elif self._mode == "compare":
            rows = [f"{'좌' if i == 0 else '우'}: {c.captured_at} {_EYE_KO.get(c.eye or '', '')}"
                    for i, c in enumerate(self._pair) if c]
            self.lbl_img.setText("2장 비교 (확대·이동 동기화)\n" + "\n".join(rows))
        elif self._mode == "live":
            self.lbl_img.setText("LIVE — " + ("정지됨 · SAVE로 저장" if self._frozen else "실시간"))
        else:
            self.lbl_img.setText("영상이 없습니다")

    # ================= 탐색 =================
    def step(self, delta: int) -> None:
        if self._mode == "multi":
            self.multi.go_page(delta)
            self._update_side()
        elif self._mode == "single" and self._caps:
            self._idx = min(max(0, self._idx + delta), len(self._caps) - 1)
            self._show_current()

    def open_index(self, idx: int) -> None:
        if 0 <= idx < len(self._caps):
            self._idx = idx
            self.set_mode("single")

    def set_per_page(self, n: int) -> None:
        self.multi.set_per_page(n)
        blk = self.c_per.blockSignals(True)
        self.c_per.setCurrentIndex(1 if n == 36 else 0)
        self.c_per.blockSignals(blk)
        self._update_side()

    def select_for_compare(self, i: int, j: int) -> None:
        self.multi.set_selection([i, j])

    def _on_selection(self, sel: list) -> None:
        self.lbl_sel.setText(
            f"선택 {len(sel)}/2 — 2장이면 '비교'를 누르세요." if sel
            else "MULTI에서 영상 2장을 클릭해 선택한 뒤 '비교'를 누르세요.")
        self._update_side()

    # ================= 비교 =================
    def _prepare_compare(self) -> bool:
        sel = self.multi.selection()
        if len(sel) == 2:
            i, j = sorted(sel)
        elif self._mode == "single" and self._idx > 0:
            i, j = self._idx - 1, self._idx
        else:
            if self.isVisible():
                QMessageBox.information(self, "2장 비교", "MULTI 화면에서 비교할 영상 2장을 클릭해 선택하세요.")
            return False
        a, b = self._caps[i], self._caps[j]
        self._pair = (a, b)
        for cv, cap, num in ((self.cmp_left, a, i + 1), (self.cmp_right, b, j + 1)):
            cv.set_image(load_bgr(cap.file_path))
            cv.set_adjust(self._adj)
            cv.set_caption(caption_of(cap, num, len(self._caps)))
        return True

    # ================= 보정 =================
    def _canvases(self) -> list:
        return [self.live_canvas, self.single_canvas, self.cmp_left, self.cmp_right]

    def _on_adjust(self, *_) -> None:
        self._adj = Adjust(
            brightness=float(self.s_bright.value()),
            contrast=self.s_contrast.value() / 100.0,
            gamma=self.s_gamma.value() / 100.0,
            negative=self.chk_neg.isChecked(),
            channel=_CHANNELS[self.c_channel.currentIndex()],
        )
        for cv in self._canvases():
            cv.set_adjust(self._adj)

    def set_adjust(self, adj: Adjust) -> None:
        widgets = (self.s_bright, self.s_contrast, self.s_gamma, self.c_channel, self.chk_neg)
        for w in widgets:
            w.blockSignals(True)
        self.s_bright.setValue(int(adj.brightness))
        self.s_contrast.setValue(int(round(adj.contrast * 100)))
        self.s_gamma.setValue(int(round(adj.gamma * 100)))
        self.c_channel.setCurrentIndex(_CHANNELS.index(adj.channel))
        self.chk_neg.setChecked(adj.negative)
        for w in widgets:
            w.blockSignals(False)
        self._on_adjust()

    def adjust(self) -> Adjust:
        return self._adj

    def reset_adjust(self) -> None:
        self.set_adjust(Adjust())

    def _fit_all(self) -> None:
        for cv in self._canvases():
            cv.reset_view()

    def _zoom(self, f: float) -> None:
        if self._mode == "compare":
            self.cmp_left.zoom_by(f)
        elif self._mode == "single":
            self.single_canvas.apply_zoom(f)
        elif self._mode == "live":
            self.live_canvas.apply_zoom(f)

    # ================= 주석 =================
    def set_tool(self, tool: str) -> None:
        for cv in (self.single_canvas, self.cmp_left, self.cmp_right):
            cv.set_tool(tool)
        {"pan": self.b_pan, "text": self.b_text, "arrow": self.b_arrow}[tool].setChecked(True)

    def clear_annotations(self) -> None:
        for cv in (self.single_canvas, self.cmp_left, self.cmp_right):
            cv.clear_annotations()

    # ================= LIVE =================
    def set_live_frame(self, frame) -> None:
        self._live = frame
        if self._mode == "live" and not self._frozen:
            self.live_canvas.set_image(frame, keep_view=True)

    def _on_capture_toggled(self, on: bool) -> None:
        self._frozen = on
        if on:
            self._frozen_frame = None if self._live is None else self._live.copy()
            if self._frozen_frame is not None:
                self.live_canvas.set_image(self._frozen_frame, keep_view=True)
            self.b_capture.setText("▶ RESUME")
        else:
            self._frozen_frame = None
            self.b_capture.setText("❄ CAPTURE")
        self._update_side()

    def current_eye(self) -> str:
        if self.get_eye is not None:
            return self.get_eye()
        return ["NA", "OD", "OS", "OU"][self.c_eye.currentIndex()]

    def _require_patient(self) -> bool:
        if self._patient is None:
            QMessageBox.information(self, "확인", "환자를 먼저 선택하세요.")
            return False
        return True

    def save_live(self):
        if not self._require_patient():
            return None
        frame = self._frozen_frame if (self._frozen and self._frozen_frame is not None) else self._live
        if frame is None:
            QMessageBox.information(self, "확인", "저장할 영상이 없습니다.")
            return None
        cap = self.service.save_photo(frame, self._patient, eye=self.current_eye())
        self.reload()
        self.savedCapture.emit()
        if self._frozen:
            self.b_capture.setChecked(False)
        return cap

    # ================= 편집 저장 / 코멘트 / 환자 =================
    def save_edited(self) -> list:
        if not self._require_patient():
            return []
        if self._mode == "single" and 0 <= self._idx < len(self._caps):
            targets = [(self.single_canvas, self._caps[self._idx])]
        elif self._mode == "compare":
            targets = [(self.cmp_left, self._pair[0]), (self.cmp_right, self._pair[1])]
        else:
            targets = []
        saved = []
        for cv, src in targets:
            if cv.image() is None or src is None:
                continue
            if self._adj.is_identity() and not cv.has_annotations():
                continue
            note = "주석" if cv.has_annotations() else "보정본"
            saved.append(self.service.save_photo(cv.render_to_bgr(), self._patient,
                                                 eye=src.eye or "NA", note=note))
        if not saved:
            QMessageBox.information(self, "보정본 저장", "보정이나 주석이 없어 저장할 내용이 없습니다.")
            return []
        self.clear_annotations()
        self.reset_adjust()                       # 저장본엔 보정이 이미 반영됨 → 이중 적용 방지
        self.reload(select_last=(self._mode == "single"))
        self.savedCapture.emit()
        return saved

    def edit_comment(self) -> None:
        if not (self._mode == "single" and 0 <= self._idx < len(self._caps)):
            return
        cap = self._caps[self._idx]
        text, ok = QInputDialog.getText(self, "코멘트", "이 영상의 코멘트:", text=cap.note or "")
        if ok:
            self.set_comment(text)

    def set_comment(self, text: str) -> None:
        if not (0 <= self._idx < len(self._caps)):
            return
        cap = self._caps[self._idx]
        note = (text or "").strip() or None
        self.db.captures.update_note(cap.id, note)
        cap.note = note
        self.multi.set_captures(self._caps, keep_page=True)
        self._show_current()
        self.savedCapture.emit()

    def edit_patient(self) -> None:
        if not self._require_patient():
            return
        dlg = PatientDialog(self, patient=self._patient)
        if not dlg.exec():
            return
        p = dlg.get_patient()
        try:
            self.db.patients.update(p)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "오류", f"수정 실패: {e}")
            return
        self._patient = p
        self._update_info()
        self.patientUpdated.emit(p)

    # ================= 인쇄 =================
    def print_items(self) -> list:
        if self._mode == "single" and self.single_canvas.image() is not None:
            return [(self.single_canvas.render_to_bgr(), caption_of(self._caps[self._idx]))]
        if self._mode == "compare":
            return [(cv.render_to_bgr(), caption_of(c))
                    for cv, c in ((self.cmp_left, self._pair[0]), (self.cmp_right, self._pair[1]))
                    if cv.image() is not None and c is not None]
        if self._mode == "live" and self.live_canvas.image() is not None:
            return [(self.live_canvas.render_to_bgr(), "LIVE " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))]
        if self._mode == "multi":
            items = []
            for i in (self.multi.selection() or self.multi.page_indices()):
                img = load_bgr(self._caps[i].file_path)
                if img is not None:
                    items.append((apply_adjust(img, self._adj), caption_of(self._caps[i])))
            return items
        return []

    def export_pdf(self, path: str) -> int:
        items = self.print_items()
        if not items:
            return 0
        printer = print_util.make_pdf_printer(path)
        return print_util.render_report(printer, self._patient, items,
                                        clinic=getattr(self.config, "clinic_name", "") or "")

    def _default_pdf_path(self) -> str:
        base = getattr(self.config, "export_root", "") or os.path.expanduser("~")
        chart = (self._patient.chart_no if self._patient else None) or "report"
        return os.path.join(base, f"{chart}_{datetime.now():%Y%m%d_%H%M}.pdf")

    def _pdf_dialog(self) -> None:
        if not self.print_items():
            QMessageBox.information(self, "PDF", "출력할 영상이 없습니다.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "PDF 보고서 저장", self._default_pdf_path(), "PDF (*.pdf)")
        if path:
            n = self.export_pdf(path)
            QMessageBox.information(self, "PDF", f"{n}쪽 보고서를 저장했습니다.\n{path}")

    def print_current(self) -> None:
        items = self.print_items()
        if not items:
            QMessageBox.information(self, "인쇄", "출력할 영상이 없습니다.")
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        if QPrintDialog(printer, self).exec():
            print_util.render_report(printer, self._patient, items,
                                     clinic=getattr(self.config, "clinic_name", "") or "")
