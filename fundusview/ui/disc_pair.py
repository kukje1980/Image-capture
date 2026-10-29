"""디스크 2장 — the optic discs of two photos on one sheet (보험 청구용).

The sheet is a white page: a header (title, patient), the two disc panels
with the eye above and exam date · device under each, and a footer. The
dialog previews it; clicking a panel re-centres that crop on the click (the
point is also stored as the photo's disc, like the 2D "시신경 유두로 지정").
It is saved into the patient record, to a file, printed or copied.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPageLayout, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QVBoxLayout,
)

from .. import discpair
from .image_view import from_qimage, to_qimage

TITLE = "시신경 유두 사진 (Optic Disc Photographs)"
INK, MUTED, RULE = QColor(20, 24, 28), QColor(92, 100, 108), QColor(176, 182, 188)


def _font(px: int, bold: bool = False) -> QFont:
    f = QFont()
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def render_sheet(panels, labels, captions, patient_line: str, footer: str,
                 panel_px: int = discpair.PANEL_PX) -> tuple[QImage, list[QRect]]:
    """The sheet image and the rectangle of each panel on it."""
    m, gap = 56, 44
    w = 2 * panel_px + gap + 2 * m
    y_pat = m + 52
    y_rule = y_pat + 40 + 16
    y_label = y_rule + 20
    y_panel = y_label + 50
    y_cap = y_panel + panel_px + 8
    y_rule2 = y_cap + 44 + 12
    h = y_rule2 + 12 + 30 + 34
    img = QImage(w, h, QImage.Format.Format_RGB888)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
                     | QPainter.RenderHint.SmoothPixmapTransform)
    left = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    p.setPen(INK)
    p.setFont(_font(40, True))
    p.drawText(QRectF(m, m, w - 2 * m, 52), left, TITLE)
    p.setFont(_font(28))
    p.drawText(QRectF(m, y_pat, w - 2 * m, 40), left, patient_line)
    p.setPen(QPen(RULE, 2))
    p.drawLine(m, y_rule, w - m, y_rule)
    rects = []
    for i, (rgb, label, cap) in enumerate(zip(panels, labels, captions)):
        x = m + i * (panel_px + gap)
        rect = QRect(x, y_panel, panel_px, panel_px)
        rects.append(rect)
        p.setPen(INK)
        p.setFont(_font(34, True))
        p.drawText(QRectF(x, y_label, panel_px, 50), left, label)
        p.drawImage(rect, to_qimage(rgb))
        p.setPen(QPen(RULE, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(rect.adjusted(-1, -1, 0, 0))
        p.setPen(MUTED)
        p.setFont(_font(24))
        p.drawText(QRectF(x, y_cap, panel_px, 44), left, cap)
    p.setPen(QPen(RULE, 2))
    p.drawLine(m, y_rule2, w - m, y_rule2)
    p.setPen(MUTED)
    p.setFont(_font(20))
    p.drawText(QRectF(m, y_rule2 + 12, w - 2 * m, 30), left, footer)
    p.end()
    return img, rects


class _Preview(QLabel):
    """The sheet scaled to the label; reports clicks in sheet pixels."""
    clickedAt = Signal(QPointF)

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(860, 560)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("background:#3a4148")
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._img: QImage | None = None

    def set_image(self, img: QImage) -> None:
        self._img = img
        self._rescale()

    def _scale(self) -> float:
        if self._img is None:
            return 1.0
        return min((self.width() - 8) / self._img.width(), (self.height() - 8) / self._img.height())

    def _rescale(self) -> None:
        if self._img is not None:
            s = self._scale()
            self.setPixmap(QPixmap.fromImage(self._img).scaled(
                max(1, int(self._img.width() * s)), max(1, int(self._img.height() * s)),
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._rescale()

    def to_sheet(self, pos: QPointF) -> QPointF | None:
        if self._img is None:
            return None
        s = self._scale()
        ox = (self.width() - self._img.width() * s) / 2
        oy = (self.height() - self._img.height() * s) / 2
        return QPointF((pos.x() - ox) / s, (pos.y() - oy) / s)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            pt = self.to_sheet(e.position())
            if pt is not None:
                self.clickedAt.emit(pt)
        super().mousePressEvent(e)


class DiscPairDialog(QDialog):
    """Preview and output of the disc pair. ``sources`` = two ``discpair.DiscSource``;
    ``save_record(rgb, sources)`` stores the sheet in the patient record (returns the id);
    ``adjust`` (rgb -> rgb) = the 2D view's gamma / contrast / brightness / filter."""
    discPicked = Signal(int, float, float)

    def __init__(self, sources, *, patient_line: str, footer: str, file_stem: str,
                 save_record=None, adjust=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("디스크 2장 (보험 청구용)")
        self.sources = list(discpair.order_pair(*sources))
        self.patient_line, self.footer_prefix, self.file_stem = patient_line, footer, file_stem
        self._save_record, self._adjust = save_record, adjust
        self._sheet: QImage | None = None
        self._rects: list[QRect] = []
        self.saved_id: int | None = None

        self.preview = _Preview()
        self.preview.clickedAt.connect(self._on_click)
        self.hint = QLabel("유두 중심이 맞지 않으면 사진에서 유두 중심을 클릭하세요 — 그곳을 중심으로 다시 자릅니다")
        self.hint.setStyleSheet("color:#667")
        self.warn = QLabel("")
        self.warn.setStyleSheet("color:#b4561a; font-weight:600")
        self.warn.setWordWrap(True)
        self.field = QComboBox()
        for key, label, factor in discpair.FIELDS:
            self.field.addItem(f"{label} (유두 지름 ×{factor:g})", key)
        self.field.setCurrentIndex(self.field.findData("normal"))
        self.field.setToolTip("사진 한 칸에 담을 범위 — 유두 지름의 몇 배인지")
        self.field.currentIndexChanged.connect(self.rerender)
        self.c_adjust = QCheckBox("화면 조정 적용 (감마·대비·밝기·필터)")
        self.c_adjust.setToolTip("끄면 원본 색 그대로입니다")
        self.c_adjust.setEnabled(adjust is not None)
        self.c_adjust.toggled.connect(self.rerender)
        b_swap = QPushButton("좌우 바꾸기")
        b_swap.clicked.connect(self.swap)
        opts = QHBoxLayout()
        opts.addWidget(QLabel("범위"))
        opts.addWidget(self.field)
        opts.addWidget(self.c_adjust)
        opts.addStretch()
        opts.addWidget(b_swap)
        self.status = QLabel("")
        self.status.setStyleSheet("color:#1d7a46")
        btns = QHBoxLayout()
        btns.addWidget(self.status, 1)
        self.b_record = QPushButton("환자 기록에 저장")
        self.b_record.setToolTip("이 환자의 사진 목록에 새 사진으로 추가 (원본 사진은 그대로)")
        self.b_record.setEnabled(save_record is not None)
        self.b_record.clicked.connect(self.save_to_record)
        for b, fn in ((self.b_record, None), (QPushButton("파일로 저장…"), self.save_file),
                      (QPushButton("인쇄…"), self.print_sheet), (QPushButton("복사"), self.copy),
                      (QPushButton("닫기"), self.accept)):
            if fn is not None:
                b.clicked.connect(fn)
            btns.addWidget(b)
        lay = QVBoxLayout(self)
        lay.addWidget(self.preview, 1)
        lay.addWidget(self.hint)
        lay.addWidget(self.warn)
        lay.addLayout(opts)
        lay.addLayout(btns)
        self.resize(1180, 860)
        self.rerender()

    # -- sheet ------------------------------------------------------------------------
    @property
    def field_key(self) -> str:
        return self.field.currentData() or "normal"

    def sheet(self) -> QImage:
        return self._sheet

    def rerender(self, *_) -> None:
        adjust = self._adjust if self._adjust is not None and self.c_adjust.isChecked() else None
        key = self.field_key
        panels = [discpair.panel(s, key, adjust=adjust) for s in self.sources]
        footer = f"{self.footer_prefix}  ·  시신경 유두 중심, 유두 지름의 약 {discpair.FIELD_FACTOR[key]:g}배 범위"
        self._sheet, self._rects = render_sheet(panels, [s.eye_label for s in self.sources],
                                                [s.caption for s in self.sources], self.patient_line, footer)
        self.preview.set_image(self._sheet)
        guessed = [s.eye_label for s in self.sources if s.found == "estimated"]
        self.warn.setText(f"{', '.join(guessed)}: 유두를 찾지 못해 예상 위치로 잘랐습니다 — 사진에서 유두 중심을 "
                          "클릭하세요" if guessed else "")
        self.warn.setVisible(bool(guessed))

    def swap(self) -> None:
        self.sources.reverse()
        self.rerender()

    def _on_click(self, pt: QPointF) -> None:
        for src, rect in zip(self.sources, self._rects):
            if rect.contains(pt.toPoint()):
                u = (pt.x() - rect.x()) / rect.width()
                v = (pt.y() - rect.y()) / rect.height()
                self.recentre(src, u, v)
                return

    def recentre(self, src: discpair.DiscSource, u: float, v: float) -> None:
        """Move ``src``'s disc to panel position ``(u, v)`` (0…1) and redraw."""
        x, y = discpair.to_source_point(src, self.field_key, u, v)
        h, w = src.rgb.shape[:2]
        src.disc = (min(max(x, 0.0), w - 1.0), min(max(y, 0.0), h - 1.0))
        src.found = "saved"
        self.discPicked.emit(src.image_id, *src.disc)
        self.rerender()
        self.status.setText(f"{src.eye_label}: 유두 위치를 고쳤습니다")

    # -- output -------------------------------------------------------------------------
    def save_to_record(self) -> None:
        if self._save_record is None:
            return
        self.saved_id = self._save_record(from_qimage(self._sheet), self.sources)
        self.status.setText("환자 기록에 새 사진으로 저장했습니다")

    def save_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "디스크 2장 저장", f"{self.file_stem}.jpg",
                                              "JPEG (*.jpg *.jpeg);;PNG (*.png)")
        if not path:
            return
        if not Path(path).suffix:
            path += ".jpg"
        if self._sheet.save(path, quality=95):
            self.status.setText(f"저장했습니다: {path}")
        else:
            self.status.setText(f"저장하지 못했습니다: {path}")

    def copy(self) -> None:
        QApplication.clipboard().setImage(self._sheet)
        self.status.setText("클립보드에 복사했습니다")

    def print_sheet(self) -> None:
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPageOrientation(QPageLayout.Orientation.Landscape)
        if QPrintDialog(printer, self).exec() != QDialog.DialogCode.Accepted:
            return
        img = self._sheet
        painter = QPainter(printer)
        page = printer.pageLayout().paintRectPixels(printer.resolution())
        scale = min(page.width() / img.width(), page.height() / img.height())
        tw, th = int(img.width() * scale), int(img.height() * scale)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(QRect((page.width() - tw) // 2, 0, tw, th), img)
        painter.end()
        self.status.setText("인쇄를 보냈습니다")
