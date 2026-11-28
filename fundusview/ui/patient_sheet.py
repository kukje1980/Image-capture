"""환자용 요약 (한 장): one printed page for the patient to take home — their own fundus photos with
the places the doctor marked (병변 핀), where those places lie in what the eye sees (sight.py, 설명용),
a short explanation of the disease chosen (diseases.py) and the doctor's own words.

``compose`` paints the page (a light sheet, for paper) from a ``Sheet``; ``PatientSheetDialog`` is the
window: what goes on the page is chosen on the right, the page is seen on the left, and it is printed,
saved as a PDF or a picture, or copied.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPageLayout, QPageSize, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .. import diseases as D
from .. import sight as S
from . import theme
from .image_view import to_qimage

W, A4_H = 1240, 1754           # the page at 150 dpi (A4 upright); a longer page is fitted when printed
M = 64                         # margin
PAPER, INK, INK2, RULE = QColor(255, 255, 255), QColor(24, 28, 34), QColor(92, 100, 112), QColor(214, 219, 226)
ACCENT, PIN = QColor(0, 102, 204), QColor(232, 62, 112)
NOTE_FIELD = ("표시한 곳이 시야의 어디쯤인지 보여 주는 설명용 그림입니다. 실제로 그렇게 보인다는 뜻이 아니며, "
              "시야검사를 대신하지 않습니다.")
NOTE_FOOT = "이 안내문은 진료 설명을 돕기 위한 자료이며 진단서가 아닙니다. 표시된 위치와 거리는 참고용 추정값입니다."
EYE_NAMES = {"OD": "오른쪽 눈 (OD)", "OS": "왼쪽 눈 (OS)"}


@dataclass
class EyePhoto:
    eye: str | None                                   # OD / OS / None
    rgb: np.ndarray
    pins: list = field(default_factory=list)          # [(x, y, text)] in the photo's pixels
    caption: str = ""                                 # under the photo (its date · kind)


@dataclass
class Sheet:
    clinic: str = ""
    patient: str = ""                                 # "홍길동 · 12345 · 1960-01-01"
    exam: str = ""                                    # 검사일
    photos: list[EyePhoto] = field(default_factory=list)   # one or two (OD first)
    device: str = ""                                  # what the photos were taken with, in a sentence
    field_eye: str = ""                               # the eye of the 시야 picture
    field_spots: list = field(default_factory=list)   # sight.Spot — empty: no 시야 picture
    disease: str = ""                                 # a name of diseases.DISEASES ("" none)
    stage: int = 0
    memo: str = ""
    show_pins: bool = True
    today: str = ""


def _font(px: float, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(theme.font_families())
    f.setPixelSize(int(round(px)))
    f.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    return f


def _text(p: QPainter, rect: QRectF, text: str, px: float, color: QColor = INK, bold: bool = False,
          measure: bool = False) -> float:
    """Draw ``text`` wrapped in ``rect`` (its height is not a limit); the height it takes."""
    p.setFont(_font(px, bold))
    p.setPen(color)
    flags = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap)
    box = QRectF(rect.x(), rect.y(), rect.width(), 10000.0)
    h = p.boundingRect(box, flags, text).height()
    if not measure:
        p.drawText(box, flags, text)
    return h


def _picture(p: QPainter, rgb: np.ndarray, rect: QRectF, radius: float = 14.0) -> QRectF:
    """``rgb`` fitted into ``rect`` (centred, its shape kept) with round corners; where it was drawn."""
    h, w = rgb.shape[:2]
    k = min(rect.width() / w, rect.height() / h)
    box = QRectF(rect.x() + (rect.width() - w * k) / 2, rect.y() + (rect.height() - h * k) / 2, w * k, h * k)
    path = QPainterPath()
    path.addRoundedRect(box, radius, radius)
    p.save()
    p.setClipPath(path)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.drawImage(box, to_qimage(np.ascontiguousarray(rgb)))
    p.restore()
    return box


def _pin(p: QPainter, c: QPointF, n: int, r: float = 13.0) -> None:
    p.setPen(QPen(QColor(255, 255, 255), 2.5))
    p.setBrush(PIN)
    p.drawEllipse(c, r, r)
    p.setFont(_font(r * 1.2, True))
    p.setPen(QColor(255, 255, 255))
    p.drawText(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), Qt.AlignmentFlag.AlignCenter, str(n))


def _heading(p: QPainter, y: float, text: str) -> float:
    p.setFont(_font(25, True))
    p.setPen(ACCENT)
    p.drawText(QRectF(M, y, W - 2 * M, 36), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
    p.setPen(QPen(RULE, 2))
    p.drawLine(QPointF(M, y + 42), QPointF(W - M, y + 42))
    return y + 58


def pin_rows(sheet: Sheet) -> list[tuple[int, str]]:
    """The pins of the page's photos, numbered through: ``[(number, "오른쪽 눈 — 11시 · 유두에서 9.2 mm"), …]``."""
    rows, n = [], 0
    for ph in sheet.photos:
        for _x, _y, text in ph.pins:
            n += 1
            eye = EYE_NAMES.get(ph.eye or "", "").split(" (")[0]
            rows.append((n, f"{eye} — {text}" if eye else text))
    return rows


def _paint(p: QPainter, sheet: Sheet) -> float:
    """Paint the page; the height used."""
    inner = W - 2 * M
    # -- the head -------------------------------------------------------------------------------------
    y = 54.0
    if sheet.clinic:
        y += _text(p, QRectF(M, y, inner, 0), sheet.clinic, 24, INK2, True) + 6
    y += _text(p, QRectF(M, y, inner, 0), "안저 검사 결과 안내", 46, INK, True) + 10
    who = "  ·  ".join(x for x in (sheet.patient, f"검사일 {sheet.exam}" if sheet.exam else "") if x)
    if who:
        y += _text(p, QRectF(M, y, inner, 0), who, 24, INK) + 6
    p.setPen(QPen(INK, 3))
    p.drawLine(QPointF(M, y + 8), QPointF(W - M, y + 8))
    y += 30

    # -- the photos -----------------------------------------------------------------------------------
    photos = sheet.photos[:2]
    n = 0
    if photos:
        gap = 28.0
        cell_w = (inner - gap) / 2 if len(photos) == 2 else min(inner, 820.0)
        cell_h = cell_w * 0.78
        x0 = M if len(photos) == 2 else M + (inner - cell_w) / 2
        for i, ph in enumerate(photos):
            x = x0 + i * (cell_w + gap)
            p.setFont(_font(24, True))
            p.setPen(INK)
            p.drawText(QRectF(x, y, cell_w, 34), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       EYE_NAMES.get(ph.eye or "", "안저 사진"))
            if ph.caption:
                p.setFont(_font(19))
                p.setPen(INK2)
                p.drawText(QRectF(x, y, cell_w, 34), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                           ph.caption)
            frame = QRectF(x, y + 42, cell_w, cell_h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(12, 12, 14))
            p.drawRoundedRect(frame, 14, 14)
            box = _picture(p, ph.rgb, frame)
            if sheet.show_pins:
                k = box.width() / ph.rgb.shape[1]
                for px, py, _text_ in ph.pins:
                    n += 1
                    _pin(p, QPointF(box.x() + px * k, box.y() + py * k), n)
        y += 42 + cell_h + 14
    if sheet.device:
        y += _text(p, QRectF(M, y, inner, 0), sheet.device, 21, INK2) + 8

    # -- the places marked --------------------------------------------------------------------------------
    rows = pin_rows(sheet) if sheet.show_pins else []
    if rows:
        y = _heading(p, y + 16, "표시한 곳")
        for num, text in rows:
            _pin(p, QPointF(M + 15, y + 17), num)
            y += max(36.0, _text(p, QRectF(M + 44, y + 2, inner - 44, 0), text, 23)) + 6
        y += _text(p, QRectF(M, y, inner, 0), "방향은 검사자가 본 안저 사진 기준(12시가 위), 거리는 12 mm 안구 모형으로 계산한 "
                                              "참고용 값입니다.", 18, INK2) + 4

    # -- where that is in what the eye sees ---------------------------------------------------------------
    if sheet.field_spots:
        eye = EYE_NAMES.get(sheet.field_eye, "").split(" (")[0]
        y = _heading(p, y + 16, f"시야에서는 어디쯤일까요{' — ' + eye if eye else ''}")
        plain = D.G.sample_scene(900)
        span = S.span_for(sheet.field_spots, plain.shape)          # (far-out places: more of the field shown)
        scene = S.simulate(plain, sheet.field_spots, span_deg=span)
        pic_w = 500.0
        box = _picture(p, scene, QRectF(M, y, pic_w, pic_w * scene.shape[0] / scene.shape[1]))
        k = box.width() / scene.shape[1]
        cx, cy = box.center().x(), box.center().y()
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.drawLine(QPointF(cx - 10, cy), QPointF(cx + 10, cy))
        p.drawLine(QPointF(cx, cy - 10), QPointF(cx, cy + 10))
        for spot in sheet.field_spots:
            sx, sy = S.to_pixel(spot, scene.shape, span)
            if spot.label and 0 <= sx < scene.shape[1] and 0 <= sy < scene.shape[0]:
                _pin(p, QPointF(box.x() + sx * k, box.y() + sy * k), int(spot.label), 11)
        tx = M + pic_w + 28
        th = _text(p, QRectF(tx, y, W - M - tx, 0),
                   "눈은 망막에 맺힌 상을 위아래가 뒤집힌 채로 받아들입니다. 그래서 망막의 위쪽에 있는 곳은 "
                   "시야의 아래쪽에, 아래쪽에 있는 곳은 시야의 위쪽에 해당합니다.\n\n"
                   "그림 가운데의 십자(+)가 바라보는 곳이고, 번호는 위 사진에 표시한 곳입니다."
                   + (f" 표시한 곳이 주변부라서 그림은 시야의 넓은 범위(좌우 약 {span:.0f}°)를 나타냅니다."
                      if span > S.SPAN_DEG + 1 else ""), 22)
        th += 14 + _text(p, QRectF(tx, y + th + 14, W - M - tx, 0), NOTE_FIELD, 18, INK2)
        y += max(box.height(), th) + 10

    # -- the disease ---------------------------------------------------------------------------------------
    dis = D.find(sheet.disease) if sheet.disease else None
    if dis is not None:
        stage = max(0, min(int(sheet.stage), len(dis.stages) - 1))
        y = _heading(p, y + 16, f"{dis.name}  ({dis.english})")
        pic = D.picture(dis.name, stage)
        side = 300.0
        _picture(p, pic.fundus, QRectF(M, y, side, side))
        sight_h = side * pic.sight.shape[0] / pic.sight.shape[1]
        _picture(p, pic.sight, QRectF(M, y + side + 34, side, sight_h))
        p.setFont(_font(18))
        p.setPen(INK2)
        p.drawText(QRectF(M, y + side + 4, side, 26), Qt.AlignmentFlag.AlignCenter, f"설명 그림 — {dis.stages[stage].name}")
        p.drawText(QRectF(M, y + side + 34 + sight_h + 4, side, 26), Qt.AlignmentFlag.AlignCenter, "이렇게 보일 수 있습니다")
        tx, tw, ty = M + side + 28, W - M - (M + side + 28), y
        for title, body in (("어떤 병인가요", dis.about), ("증상", dis.symptoms), ("치료와 관리", dis.care)):
            if not body:
                continue
            ty += _text(p, QRectF(tx, ty, tw, 0), title, 22, INK, True) + 4
            ty += _text(p, QRectF(tx, ty, tw, 0), body, 21) + 14
        ty += _text(p, QRectF(tx, ty, tw, 0), D.NOTE_MODEL, 18, INK2)
        y = max(y + side + 34 + sight_h + 34, ty) + 6

    # -- the doctor's words -------------------------------------------------------------------------------
    y = _heading(p, y + 16, "의사 소견")
    memo = sheet.memo.strip()
    h = max(120.0, _text(p, QRectF(M + 18, y + 14, inner - 36, 0), memo, 24, measure=True) + 28) if memo else 150.0
    p.setPen(QPen(RULE, 2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(M, y, inner, h), 12, 12)
    if memo:
        _text(p, QRectF(M + 18, y + 14, inner - 36, 0), memo, 24)
    y += h + 22

    # -- the foot ---------------------------------------------------------------------------------------------
    y += _text(p, QRectF(M, y, inner, 0), NOTE_FOOT, 17, INK2) + 4
    y += _text(p, QRectF(M, y, inner, 0), "  ·  ".join(x for x in (sheet.clinic, sheet.today or date.today().isoformat())
                                                         if x), 17, INK2)
    return y + 44


def compose(sheet: Sheet) -> QImage:
    """The page as a picture: ``W`` wide, as high as an A4 sheet — or longer when there is more on it."""
    probe = QImage(W, 16, QImage.Format.Format_RGB888)
    p = QPainter(probe)
    need = _paint(p, sheet)
    p.end()
    img = QImage(W, int(max(A4_H, need)), QImage.Format.Format_RGB888)
    img.fill(PAPER)
    p = QPainter(img)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    _paint(p, sheet)
    p.end()
    return img


def paint_on(device, img: QImage) -> None:
    """The page on a printer or a PDF writer: fitted into its page, at the top, centred."""
    p = QPainter(device)
    page = device.pageLayout().paintRectPixels(device.resolution())
    k = min(page.width() / img.width(), page.height() / img.height())
    w, h = img.width() * k, img.height() * k
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.drawImage(QRectF((page.width() - w) / 2, 0, w, h), img)
    p.end()


def save_pdf(img: QImage, path: str) -> None:
    from PySide6.QtGui import QPdfWriter

    out = QPdfWriter(path)
    out.setResolution(150)
    out.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                                  QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter))
    paint_on(out, img)


class PatientSheetDialog(QDialog):
    """``base``: the page's fixed part (who, the photos with their pins, the device); ``pair``: its
    photos with the other eye too (None: only one eye there is); ``spots``: ``{eye: [sight.Spot]}``."""

    def __init__(self, base: Sheet, pair: list[EyePhoto] | None = None, spots: dict | None = None,
                 file_stem: str = "안저검사안내", parent=None):
        super().__init__(parent)
        self.setWindowTitle("환자용 요약 (한 장)")
        self.resize(1180, 900)
        self.base, self._one, self._pair, self._spots = base, list(base.photos), pair, spots or {}
        self.file_stem = file_stem
        self.image: QImage | None = None
        lay = QHBoxLayout(self)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.preview)
        lay.addWidget(scroll, 1)
        side = QVBoxLayout()
        side.setSpacing(8)

        def label(text):
            lb = QLabel(text)
            lb.setStyleSheet("font-weight:600")
            return lb
        side.addWidget(label("병원 이름"))
        self.clinic = QLineEdit(base.clinic)
        self.clinic.setPlaceholderText("안내문 맨 위에 들어갑니다")
        side.addWidget(self.clinic)
        self.c_pair = QCheckBox("두 눈 사진을 함께")
        self.c_pair.setChecked(pair is not None)
        self.c_pair.setEnabled(pair is not None)
        self.c_pair.setToolTip("" if pair is not None else "반대쪽 눈의 사진이 없습니다")
        self.c_pins = QCheckBox("표시한 곳(병변 핀)과 그 위치")
        self.c_pins.setChecked(True)
        have_spots = any(self._spots.values())
        self.c_field = QCheckBox("시야에서는 어디쯤인지 (설명용 그림)")
        self.c_field.setEnabled(have_spots)
        self.c_field.setToolTip("표시한 곳이 시야의 어디에 해당하는지 풍경 그림 위에 보여 줍니다 — 그렇게 보인다는 뜻이 아닌 "
                                "설명용 그림입니다" if have_spots else "황반을 찾은 사진에 병변 핀을 꽂으면 쓸 수 있습니다")
        for c in (self.c_pair, self.c_pins, self.c_field):
            side.addWidget(c)
        side.addWidget(label("질환 설명"))
        self.disease = QComboBox()
        self.disease.addItem("넣지 않음", "")
        for d in D.DISEASES:
            self.disease.addItem(d.name, d.name)
        self.stage = QComboBox()
        side.addWidget(self.disease)
        side.addWidget(self.stage)
        side.addWidget(label("의사 소견"))
        self.memo = QPlainTextEdit()
        self.memo.setPlaceholderText("환자에게 전할 말 (비워 두면 손으로 쓸 빈 칸이 인쇄됩니다)")
        self.memo.setFixedHeight(150)
        side.addWidget(self.memo)
        side.addStretch(1)
        self.b_print = QPushButton("인쇄…")
        self.b_print.setObjectName("primary")
        self.b_pdf = QPushButton("PDF로 저장…")
        self.b_png = QPushButton("그림으로 저장…")
        self.b_copy = QPushButton("복사")
        self.b_close = QPushButton("닫기")
        for b, fn in ((self.b_print, self.print_), (self.b_pdf, self.save_pdf), (self.b_png, self.save_png),
                      (self.b_copy, self.copy), (self.b_close, self.accept)):
            b.clicked.connect(fn)
            side.addWidget(b)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color:{theme.TEXT2}")
        side.addWidget(self.status)
        box = QWidget()
        box.setLayout(side)
        box.setFixedWidth(330)
        lay.addWidget(box)
        self.disease.currentIndexChanged.connect(self._disease_changed)
        for w in (self.c_pair, self.c_pins, self.c_field):
            w.toggled.connect(lambda _on: self.refresh())
        self.stage.currentIndexChanged.connect(lambda _i: self.refresh())
        self.clinic.editingFinished.connect(self.refresh)
        self.memo.textChanged.connect(self.refresh)
        self._disease_changed()

    def _disease_changed(self) -> None:
        d = D.find(self.disease.currentData())
        blk = self.stage.blockSignals(True)
        self.stage.clear()
        for i, st in enumerate(d.stages if d is not None else ()):
            self.stage.addItem(st.name, i)
        self.stage.blockSignals(blk)
        self.stage.setEnabled(d is not None)
        self.refresh()

    def sheet(self) -> Sheet:
        s = self.base
        photos = self._pair if (self.c_pair.isChecked() and self._pair) else self._one
        first = self._one[0].eye if self._one else ""
        spots = self._spots.get(first or "", []) if self.c_field.isChecked() and self.c_pins.isChecked() else []
        # the 시야 picture is of the eye being looked at; its numbers are those of that eye's pins on the page
        start = 0
        for ph in photos:
            if ph.eye == first:
                break
            start += len(ph.pins)
        spots = [S.Spot(sp.x_deg, sp.y_deg, str(start + int(sp.label))) for sp in spots]
        return Sheet(clinic=self.clinic.text().strip(), patient=s.patient, exam=s.exam, photos=list(photos),
                     device=s.device, field_eye=first or "", field_spots=spots,
                     disease=self.disease.currentData() or "", stage=int(self.stage.currentData() or 0),
                     memo=self.memo.toPlainText(), show_pins=self.c_pins.isChecked(), today=s.today)

    def refresh(self) -> None:
        self.image = compose(self.sheet())
        shown = self.image.scaledToWidth(760, Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(QPixmap.fromImage(shown))

    # -- out ----------------------------------------------------------------------------------------------------
    def print_(self) -> None:
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        if QPrintDialog(printer, self).exec() != QDialog.DialogCode.Accepted:
            return
        paint_on(printer, self.image)
        self.status.setText("인쇄를 보냈습니다")

    def save_pdf(self, path: str | None = None) -> None:
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "PDF로 저장", f"{self.file_stem}.pdf", "PDF (*.pdf)")
        if not path:
            return
        try:
            save_pdf(self.image, path)
            self.status.setText(f"저장했습니다: {path}")
        except Exception as exc:
            self.status.setText(f"저장하지 못했습니다 — {exc}")

    def save_png(self, path: str | None = None) -> None:
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "그림으로 저장", f"{self.file_stem}.png", "PNG (*.png);;JPEG (*.jpg)")
        if not path:
            return
        ok = self.image.save(path)
        self.status.setText(f"저장했습니다: {path}" if ok else "저장하지 못했습니다")

    def copy(self) -> None:
        QApplication.clipboard().setImage(self.image)
        self.status.setText("클립보드로 복사했습니다")
