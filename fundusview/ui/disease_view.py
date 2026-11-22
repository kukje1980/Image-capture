"""질환 설명 그림: one picture per disease and stage to explain the disease to a patient (diseases.py draws
the parts) — the schematic fundus with numbered findings and their legend, the retina cut through with
its labels, what the patient sees (and the Amsler grid for diseases of the macula), the stage's words —
and the panel of the 질환 샘플 window that shows it (stages, what the disease is, symptoms, care; save ·
copy). Its switch **단계별 그림 | 기전** shows instead how the disease comes about, step by step
(ui/mechanism_view.py). The pictures say that they are models: they are never put into a patient's record.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel, QListWidget, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from .. import diseases as D
from . import theme
from .image_view import ImageView, from_qimage, to_qimage
from .widgets import Segmented, card, segment

W = 1600                       # the picture's width (pixels)
M = 28                         # its margin
BADGE = QColor(255, 214, 10)   # the numbers on the fundus
INK = QColor(theme.TEXT)
INK2 = QColor(theme.TEXT2)
NUMS = "①②③④⑤⑥⑦⑧⑨⑩"


def _font(px: float, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(theme.font_families())
    f.setPixelSize(int(round(px)))
    f.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    return f


def _image(p: QPainter, rgb: np.ndarray, rect: QRectF, radius: float = 10) -> None:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    p.save()
    p.setClipPath(path)
    p.drawImage(rect, to_qimage(rgb))
    p.restore()


def _caption(p: QPainter, x: float, y: float, text: str, px: float = 19) -> None:
    p.setFont(_font(px, True))
    p.setPen(INK2)
    p.drawText(QPointF(x, y), text)


def _badge(p: QPainter, c: QPointF, n: int, r: float = 13) -> None:
    p.setPen(QPen(QColor(0, 0, 0, 170), 2.5))
    p.setBrush(BADGE)
    p.drawEllipse(c, r, r)
    p.setFont(_font(r * 1.25, True))
    p.setPen(QColor(20, 20, 20))
    p.drawText(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), Qt.AlignmentFlag.AlignCenter, str(n))


def _pill(p: QPainter, at: QPointF, text: str, px: float, bounds: QRectF, place: str = "right",
          taken: list | None = None) -> None:
    """A label on a dark pill beside ``at`` with a short leader line, kept inside ``bounds`` and off the
    labels already ``taken`` (their boxes; this one is added)."""
    p.setFont(_font(px, True))
    fm = QFontMetricsF(p.font())
    tw, th = fm.horizontalAdvance(text) + 14, fm.height() + 6
    dx, dy = (16, -th - 10)
    x = at.x() + dx if place == "right" else at.x() - dx - tw
    if x + tw > bounds.right() - 4:
        x = at.x() - dx - tw
    if x < bounds.left() + 4:
        x = bounds.left() + 4
    y = at.y() + dy
    if y < bounds.top() + 4:
        y = at.y() + 12
    if y + th > bounds.bottom() - 4:
        y = bounds.bottom() - 4 - th
    box = QRectF(x, y, tw, th)
    taken = [] if taken is None else taken
    if any(box.adjusted(-3, -3, 3, 3).intersects(t) for t in taken):
        tries = []
        for k in range(1, 12):                     # nearest free place above or below
            for sgn in (-1, 1):
                tries.append(box.translated(0, sgn * k * (th * 0.55)))
        for cand in tries:
            if cand.top() >= bounds.top() + 2 and cand.bottom() <= bounds.bottom() - 2 and \
                    not any(cand.adjusted(-3, -3, 3, 3).intersects(t) for t in taken):
                box = cand
                break
    taken.append(box)
    p.setPen(QPen(QColor(255, 255, 255, 220), 1.6))
    near = QPointF(min(max(at.x(), box.left()), box.right()),
                   box.bottom() if at.y() > box.bottom() else (box.top() if at.y() < box.top() else at.y()))
    p.drawLine(at, near)
    p.setPen(QPen(QColor(0, 0, 0, 160), 1.5))
    p.setBrush(QColor(255, 255, 255))
    p.drawEllipse(at, 4.5, 4.5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(18, 18, 20, 215))
    p.drawRoundedRect(box, 7, 7)
    p.setPen(INK)
    p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)


def _wrapped(p: QPainter, rect: QRectF, text: str, px: float, color: QColor = INK, bold: bool = False) -> float:
    """Draw ``text`` wrapped in ``rect``; the height it took."""
    p.setFont(_font(px, bold))
    p.setPen(color)
    flags = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap)
    r = p.boundingRect(rect, flags, text)
    p.drawText(rect, flags, text)
    return r.height()


def compose(pic: D.Picture, width: int = W) -> np.ndarray:
    """The whole explanation picture (RGB): title, fundus + legend, what the patient sees (+ Amsler grid),
    the section with its labels, and the stage's words."""
    k = width / W
    fund = 620
    right_x = M + fund + 40
    right_w = W - right_x - M
    has_grid = pic.amsler is not None
    grid_w = 250 if has_grid else 0
    sight_w = right_w - (grid_w + 24 if has_grid else 0)
    sight_h = min(410, sight_w * pic.sight.shape[0] / pic.sight.shape[1])
    sight_w = sight_h * pic.sight.shape[1] / pic.sight.shape[0]
    sec_h = right_w * pic.section.shape[0] / pic.section.shape[1]
    legend_rows = (len(pic.fundus_marks) + 1) // 2
    top = 96
    left_h = 34 + fund + 18 + legend_rows * 32
    right_h = 34 + sight_h + 26 + 34 + sec_h
    body = max(left_h, right_h)
    text_h = 96
    H = int(top + body + 26 + text_h + M)
    img = QImage(int(W * k), int(H * k), QImage.Format.Format_RGB888)
    img.fill(QColor(theme.BG))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.scale(k, k)

    # title, and that it is a model
    p.setFont(_font(34, True))
    p.setPen(INK)
    title = pic.disease.name
    p.drawText(QPointF(M, 52), title)
    fm = QFontMetricsF(p.font())
    x = M + fm.horizontalAdvance(title) + 18
    if len(pic.disease.stages) > 1:
        p.setFont(_font(26, True))
        p.setPen(QColor(theme.TEAL))
        p.drawText(QPointF(x, 52), pic.stage_name)
    p.setFont(_font(17))
    p.setPen(INK2)
    p.drawText(QPointF(M, 80), pic.disease.english)
    p.setFont(_font(16, True))
    p.setPen(QColor(theme.ORANGE))
    p.drawText(QRectF(W - M - 620, 30, 620, 30), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
               "설명용 모형 — 이 환자의 소견이 아닙니다")

    # the fundus, numbered, and the legend under it
    y = top
    _caption(p, M, y + 22, "안저 모식도 (오른쪽 눈)")
    frect = QRectF(M, y + 34, fund, fund)
    _image(p, pic.fundus, frect, 12)
    s = fund / pic.fundus.shape[1]
    if pic.inset is not None:                  # the disc close up, in the corner, and where it is
        bx, by, bw, bh = pic.inset_box
        box = QRectF(frect.left() + bx * s, frect.top() + by * s, bw * s, bh * s)
        side = 236
        irect = QRectF(frect.right() - side - 10, frect.bottom() - side - 10, side, side)
        p.setPen(QPen(QColor(255, 255, 255, 200), 1.6, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(box)
        p.drawLine(box.bottomLeft(), irect.topLeft())
        p.drawLine(box.bottomRight(), irect.topRight())
        _image(p, pic.inset, irect, 8)
        p.setPen(QPen(QColor(255, 255, 255, 230), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(irect, 8, 8)
        p.setFont(_font(14, True))
        p.setPen(QColor(255, 255, 255))
        p.drawText(irect.adjusted(8, 4, -8, -4), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), "시신경 유두 확대")
    pts = _spread([QPointF(frect.left() + mk.x * s, frect.top() + mk.y * s) for mk in pic.fundus_marks], 30)
    for i, (mk, (at, put)) in enumerate(zip(pic.fundus_marks, pts)):
        if (put - at).manhattanLength() > 2:
            p.setPen(QPen(QColor(255, 255, 255, 230), 1.6))
            p.drawLine(at, put)
            p.setPen(QPen(QColor(0, 0, 0, 160), 1.2))
            p.setBrush(QColor(255, 255, 255))
            p.drawEllipse(at, 3.5, 3.5)
        _badge(p, put, i + 1)
    ly = frect.bottom() + 18
    p.setFont(_font(19))
    for i, mk in enumerate(pic.fundus_marks):
        cx = M + (i % 2) * (fund / 2)
        cy = ly + (i // 2) * 32
        _badge(p, QPointF(cx + 13, cy + 13), i + 1, 12)
        p.setFont(_font(19))
        p.setPen(INK)
        p.drawText(QRectF(cx + 32, cy, fund / 2 - 36, 28), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   mk.label)

    # what the patient sees
    _caption(p, right_x, y + 22, "환자가 보는 모습 (예시)")
    srect = QRectF(right_x, y + 34, sight_w, sight_h)
    _image(p, pic.sight, srect, 12)
    if has_grid:
        gx = right_x + right_w - grid_w
        _caption(p, gx, y + 22, "암슬러 격자로 보면")
        grect = QRectF(gx, y + 34, grid_w, grid_w)
        _image(p, pic.amsler, grect, 8)
        _wrapped(p, QRectF(gx, grect.bottom() + 10, grid_w, sight_h - grid_w), "한쪽 눈씩 가운데 점을 보며 선이 휘거나 "
                 "비어 보이는지 확인합니다.", 15, INK2)

    # the section
    sy = srect.bottom() + 26
    _caption(p, right_x, sy + 22, pic.section_title)
    crect = QRectF(right_x, sy + 34, right_w, sec_h)
    _image(p, pic.section, crect, 10)
    cs = right_w / pic.section.shape[1]
    p.setFont(_font(14, True))
    fm = QFontMetricsF(p.font())
    last = -1e9
    for mk in sorted(pic.layer_marks, key=lambda m: m.y):     # the layers' names, kept apart
        at = QPointF(crect.left() + mk.x * cs, crect.top() + mk.y * cs)
        y = max(at.y(), last + 19)
        last = y
        pt = QPointF(at.x(), y)
        if y - at.y() > 3:                     # moved off its (thin) layer: a line back to it
            tx = pt.x() + fm.horizontalAdvance(mk.label) + 6
            p.setPen(QPen(QColor(255, 255, 255, 200), 1.2))
            p.drawLine(QPointF(tx, y), QPointF(tx + 22, at.y()))
        p.setPen(QColor(0, 0, 0, 200))
        p.drawText(pt + QPointF(1.2, 5.2), mk.label)
        p.setPen(QColor(255, 255, 255, 235))
        p.drawText(pt + QPointF(0, 4), mk.label)
    taken: list = []
    for mk in pic.section_marks:
        _pill(p, QPointF(crect.left() + mk.x * cs, crect.top() + mk.y * cs), mk.label, 16, crect,
              "left" if mk.x * cs > right_w * 0.78 else "right", taken)

    # the stage's words
    ty = top + body + 26
    p.setPen(QPen(QColor(theme.SEP), 1))
    p.drawLine(QPointF(M, ty - 10), QPointF(W - M, ty - 10))
    _wrapped(p, QRectF(M, ty + 4, W - 2 * M, text_h), pic.stage_text, 21)
    p.end()
    return from_qimage(img)


def _spread(points: list[QPointF], gap: float) -> list[tuple[QPointF, QPointF]]:
    """(where, where to draw the badge) for each point: badges closer than ``gap`` are pushed apart."""
    put = [QPointF(q) for q in points]
    for _ in range(40):
        moved = False
        for i in range(len(put)):
            for j in range(i):
                d = put[i] - put[j]
                dist = (d.x() ** 2 + d.y() ** 2) ** 0.5
                if dist < gap:
                    if dist < 1e-3:
                        d, dist = QPointF(1.0, -0.6), 1.17
                    push = d * ((gap - dist) / dist / 2 + 0.02)
                    put[i] += push
                    put[j] -= push
                    moved = True
        if not moved:
            break
    return list(zip(points, put))


class _StageList(QListWidget):
    """The stages of a disease, one under another."""

    def set_stages(self, names: list[str]) -> None:
        self.blockSignals(True)
        self.clear()
        self.addItems(names)
        self.blockSignals(False)
        self.setFixedHeight(max(1, len(names)) * 30 + 8)


class DiseaseExplainPanel(QWidget):
    """The 환자 설명 page of the 질환 샘플 window: the picture of the chosen disease at a stage, the words
    beside it, save and copy."""
    stageChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("diseaseExplain")
        self.disease: D.Disease | None = None
        self.stage = 0
        self.kind = "stage"                     # or "mechanism" (기전)
        self._rgb: np.ndarray | None = None
        self.view = ImageView()
        self.view.set_navigator(False)
        self.view.setToolTip("휠: 배율 · 드래그: 이동 · 더블클릭: 전체 보기")
        self.lbl_none = QLabel()
        self.lbl_none.setWordWrap(True)
        self.lbl_none.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_none.setObjectName("hint")
        self.lbl_none.hide()

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(10)
        self.stages = _StageList()
        self.stages.setObjectName("stageList")
        self.stages.currentRowChanged.connect(lambda r: self.set_stage(r) if r >= 0 else None)
        self.card_stages = card("진행 단계", self.stages, lines=False)
        self.lbl_stage = QLabel()
        self.lbl_about = QLabel()
        self.lbl_symptoms = QLabel()
        self.lbl_care = QLabel()
        for lb in (self.lbl_stage, self.lbl_about, self.lbl_symptoms, self.lbl_care):
            lb.setWordWrap(True)
            lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.card_stage = card("이 단계", self.lbl_stage)
        self.seg_stage = segment("단계별 그림", "안저 모식도 · 단면 · 환자가 보는 모습을 진행 단계별로")
        self.seg_mech = segment("기전", "이 병이 어떻게 생기는지 단계별 그림으로")
        self.kinds = Segmented([self.seg_stage, self.seg_mech])
        self.seg_stage.setChecked(True)
        self.seg_stage.clicked.connect(lambda: self.set_kind("stage"))
        self.seg_mech.clicked.connect(lambda: self.set_kind("mechanism"))
        self.lbl_model = QLabel(D.NOTE_MODEL)
        self.lbl_model.setWordWrap(True)
        self.lbl_model.setStyleSheet(f"color:{theme.ORANGE}; font-weight:600")
        for w in (card("그림", self.kinds, lines=False), self.card_stages, self.card_stage,
                  card("어떤 병인가요", self.lbl_about), card("증상", self.lbl_symptoms),
                  card("치료 · 관리", self.lbl_care), card("", self.lbl_model, lines=False)):
            sl.addWidget(w)
        sl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(side)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedWidth(330)
        self.side = side

        self.b_save = QPushButton("파일로 저장…")
        self.b_save.setToolTip("이 설명 그림을 그림 파일로 (환자 기록에는 넣지 않습니다)")
        self.b_save.clicked.connect(self.save_file)
        self.b_copy = QPushButton("복사")
        self.b_copy.setToolTip("이 설명 그림을 클립보드로")
        self.b_copy.clicked.connect(self.copy)
        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{theme.GREEN}")
        bottom = QHBoxLayout()
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.b_save)
        bottom.addWidget(self.b_copy)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(self.view, 1)
        left.addWidget(self.lbl_none, 1)
        left.addLayout(bottom)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(left, 1)
        lay.addWidget(scroll)
        self.set_disease(None)

    # -- what is shown ------------------------------------------------------------------------------
    def set_disease(self, name: str | None) -> None:
        """The disease of the sample library called ``name`` (its picture, if it has one)."""
        d = D.find(name)
        if d is not None and d is self.disease:
            return
        self.disease = d
        has = d is not None
        self.view.setVisible(has)
        self.lbl_none.setVisible(not has)
        self.side.setEnabled(has)
        for b in (self.b_save, self.b_copy):
            b.setEnabled(has)
        if not has:
            self._rgb = None
            self.view.set_rgb(None)
            known = ", ".join(x.name for x in D.DISEASES)
            self.lbl_none.setText((f"'{name}'의 설명 그림은 아직 없습니다.\n\n" if name else "") +
                                  f"설명 그림이 있는 질환: {known}")
            for lb in (self.lbl_stage, self.lbl_about, self.lbl_symptoms, self.lbl_care):
                lb.setText("")
            self.stages.set_stages([])
            return
        self.lbl_about.setText(d.about)
        self.lbl_symptoms.setText(d.symptoms)
        self.lbl_care.setText(d.care)
        self.stages.set_stages([s.name for s in d.stages])
        self.stage = -1
        self._rgb = None                         # (drawn anew for this disease, whichever picture)
        self._show_kind()
        self.set_stage(0)

    def set_kind(self, kind: str) -> None:
        """``"stage"``: the pictures stage by stage; ``"mechanism"``: how the disease comes about (기전)."""
        kind = "mechanism" if kind == "mechanism" else "stage"
        (self.seg_mech if kind == "mechanism" else self.seg_stage).setChecked(True)
        if kind == self.kind:
            return
        self.kind = kind
        self._show_kind()
        if self.disease is not None:
            self._draw()

    def _show_kind(self) -> None:
        stage = self.kind == "stage"
        has = self.disease is not None
        self.card_stages.setVisible(stage and has and len(self.disease.stages) > 1)
        self.card_stage.setVisible(stage)

    def set_stage(self, stage: int) -> None:
        if self.disease is None:
            return
        stage = max(0, min(len(self.disease.stages) - 1, int(stage)))
        if self.stages.currentRow() != stage:
            self.stages.blockSignals(True)
            self.stages.setCurrentRow(stage)
            self.stages.blockSignals(False)
        if stage == self.stage and self._rgb is not None:
            return
        self.stage = stage
        self.lbl_stage.setText(self.disease.stages[stage].text)
        if self.kind == "stage" or self._rgb is None:
            self._draw()
        self.stageChanged.emit(stage)

    def _draw(self) -> None:
        from .mechanism_view import compose_mechanism

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if self.kind == "mechanism":
                self._rgb = compose_mechanism(self.disease)
            else:
                self._rgb = compose(D.picture(self.disease.name, max(0, self.stage)))
        finally:
            QApplication.restoreOverrideCursor()
        self.view.set_rgb(self._rgb)
        self.status.setText("")

    def picture(self) -> np.ndarray | None:
        return self._rgb

    def note(self) -> str:
        if self.disease is None:
            return ""
        if self.kind == "mechanism":
            return f"{self.disease.name} — 기전 (설명용 그림)"
        stage = self.disease.stages[self.stage].name if len(self.disease.stages) > 1 else ""
        return f"{self.disease.name}" + (f" — {stage}" if stage else "") + " (설명용 모형)"

    # -- save · copy ----------------------------------------------------------------------------------
    def save_file(self) -> None:
        if self._rgb is None:
            return
        stem = self.note().replace(" (설명용 모형)", "").replace(" (설명용 그림)", "").replace(" — ", "_").replace(" ", "")
        stem = "".join(ch if ch not in '\\/:*?"<>|()' else "_" for ch in stem)
        path, _ = QFileDialog.getSaveFileName(self, "질환 설명 그림 저장", f"질환설명_{stem}.jpg",
                                              "JPEG (*.jpg *.jpeg);;PNG (*.png)")
        if not path:
            return
        if not Path(path).suffix:
            path += ".jpg"
        ok = to_qimage(self._rgb).save(path, quality=95)
        self.status.setText(f"저장했습니다: {path}" if ok else f"저장하지 못했습니다: {path}")

    def copy(self) -> None:
        if self._rgb is None:
            return
        QApplication.clipboard().setImage(to_qimage(self._rgb))
        self.status.setText("클립보드에 복사했습니다")
