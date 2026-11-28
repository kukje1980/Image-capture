"""Three windows for explaining to the patient and for following a fundus over time:

* ``SightDialog``   — 이 환자의 시야 시뮬레이션 (fieldsim.py): the photo with its 병변 핀 beside the street scene
  with a dim patch for every pin;
* ``ChangeDialog``  — 변화 지도 (changemap.py): an earlier photo of the same eye under today's, a line to
  swipe between them, and what differs in colour;
* ``HandoutDialog`` — 환자용 한 장 요약 (handout.py): the page previewed, saved as a PDF or printed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QMarginsF, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QImage, QPageLayout, QPageSize, QPainter, QPainterPath, QPdfWriter,
                           QPen)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
                               QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from .. import changemap as C
from .. import diseases as D
from .. import fieldsim as F
from .. import glaucoma as G
from .. import handout as H
from . import theme
from .glaucoma_dialog import _Slider, _View, _note
from .image_view import to_qimage
from .widgets import card

SIDE_W = 330                 # the column of controls
SHOW_PX = 1500               # a photo is shown (and compared) at most this large


def _fit(rgb: np.ndarray, side: int = SHOW_PX) -> tuple[np.ndarray, float]:
    k = side / float(max(rgb.shape[:2]))
    if k >= 1.0:
        return rgb, 1.0
    return cv2.resize(rgb, (max(1, round(rgb.shape[1] * k)), max(1, round(rgb.shape[0] * k))),
                      interpolation=cv2.INTER_AREA), k


def _side(*widgets) -> QWidget:
    w = QWidget()
    w.setFixedWidth(SIDE_W)
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)
    for x in widgets:
        lay.addWidget(x)
    lay.addStretch(1)
    return w


def _save_rgb(parent, rgb: np.ndarray, stem: str, title: str) -> str:
    path, _ = QFileDialog.getSaveFileName(parent, title, f"{stem}.png", "PNG (*.png);;JPEG (*.jpg *.jpeg)")
    if path:
        to_qimage(rgb).save(path, quality=95)
    return path


# ------------------------------------------------------------------------------------------------------
# 이 환자의 시야 시뮬레이션
# ------------------------------------------------------------------------------------------------------
def pinned_photo(rgb: np.ndarray, pins, centre, height: int) -> np.ndarray:
    """The photo ``height`` pixels high with its pins numbered and a cross where the patient looks."""
    k = height / rgb.shape[0]
    out = cv2.resize(rgb, (max(1, round(rgb.shape[1] * k)), height), interpolation=cv2.INTER_AREA).copy()
    t = max(1, height // 260)
    if centre is not None:
        c, arm = (int(centre[0] * k), int(centre[1] * k)), max(6, height // 40)
        for color, thick in (((0, 0, 0), t + 2), ((255, 255, 255), t)):
            cv2.line(out, (c[0] - arm, c[1]), (c[0] + arm, c[1]), color, thick, cv2.LINE_AA)
            cv2.line(out, (c[0], c[1] - arm), (c[0], c[1] + arm), color, thick, cv2.LINE_AA)
    r = max(7, height // 45)
    for n, pin in enumerate(pins, 1):
        p = (int(pin.x * k), int(pin.y * k))
        cv2.circle(out, p, r, (0, 0, 0), -1, cv2.LINE_AA)
        cv2.circle(out, p, r - 2, (255, 214, 10), -1, cv2.LINE_AA)
        scale = r / 16.0
        (tw, th), _b = cv2.getTextSize(str(n), cv2.FONT_HERSHEY_SIMPLEX, scale, max(1, t))
        cv2.putText(out, str(n), (p[0] - tw // 2, p[1] + th // 2), cv2.FONT_HERSHEY_SIMPLEX, scale, (20, 20, 20),
                    max(1, t), cv2.LINE_AA)
    return out


def sight_picture(rgb: np.ndarray, pins, centre, spots, *, size_deg: float, depth: float,
                  scene_w: int = 900) -> tuple[np.ndarray, np.ndarray]:
    """``(both, scene)``: the pinned photo beside the simulated scene (one picture), and the scene alone."""
    scene = F.simulate(G.sample_scene(scene_w), spots, size_deg=size_deg, depth=depth)
    photo = pinned_photo(rgb, pins, centre, scene.shape[0])
    gap = 14
    both = np.zeros((scene.shape[0], photo.shape[1] + gap + scene.shape[1], 3), np.uint8)
    both[:, :photo.shape[1]] = photo
    both[:, photo.shape[1] + gap:] = scene
    return both, scene


class SightDialog(QDialog):
    def __init__(self, rgb: np.ndarray, pins, cam, centre, how: str, *, title_line: str = "", file_stem: str = "시야",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("이 환자의 시야 시뮬레이션" + (f" — {title_line}" if title_line else ""))
        self.resize(1320, 640)
        self.rgb, self.pins, self.centre, self.file_stem = rgb, list(pins), centre, file_stem
        self.spots = F.spots(self.pins, cam, centre, width=rgb.shape[1])
        self.half = F.half_width(self.spots)
        self.view = _View(F.NO_PINS)
        self.s_size = _Slider("얼룩 크기 (반지름)", F.SIZE_DEG[0], F.SIZE_DEG[1], F.SIZE_DEG[2], 1.0, lambda v: f"{v:.0f}°")
        self.s_depth = _Slider("진하기", 20, 100, 85, 5, lambda v: f"{v:.0f}%")
        for s in (self.s_size, self.s_depth):
            s.changed.connect(lambda _v: self._draw())
        about = {"fovea": "사진에서 찾은 황반(중심와)", "expected": "유두 위치로 짐작한 황반 자리",
                 "image": "사진 가운데 (황반 · 유두 위치를 몰라서)"}[how]
        lines = F.describe(self.spots)
        gone = len(self.pins) - len(self.spots)
        if gone:
            lines.append(f"핀 {gone}개는 사진의 시야 밖이라 그리지 않았습니다")
        self.lbl_lines = _note("\n".join(lines) if lines else "핀이 없습니다")
        how_note = _note(f"왼쪽: 사진과 병변 핀 (흰 십자 = 환자가 보는 곳 — {about}). 오른쪽: 환자가 보는 풍경 "
                         f"(가로 {self.half * 2:.0f}°). 망막의 위쪽 병변은 시야의 아래쪽에 나타납니다.")
        warn = _note(F.NOTE + " 얼룩의 크기와 진하기는 직접 정한 값입니다.")
        warn.setStyleSheet(f"color:{theme.ORANGE}")
        b_save = QPushButton("그림 저장…")
        b_save.setObjectName("primary")
        b_save.clicked.connect(self.save_file)
        b_copy = QPushButton("클립보드로 복사")
        b_copy.clicked.connect(self.copy)
        b_close = QPushButton("닫기")
        b_close.clicked.connect(self.accept)
        self.lbl_done = _note()
        lay = QHBoxLayout(self)
        lay.addWidget(self.view, 1)
        lay.addWidget(_side(card("얼룩", self.s_size, self.s_depth), card("병변이 보이는 곳", self.lbl_lines),
                            how_note, warn, b_save, b_copy, b_close, self.lbl_done))
        self._scene = None
        self._draw()

    def _draw(self) -> None:
        both, self._scene = sight_picture(self.rgb, self.pins, self.centre, self.spots, size_deg=self.s_size.value(),
                                          depth=self.s_depth.value() / 100.0)
        self.view.set_rgb(both)

    def picture(self) -> np.ndarray:
        return self.view.render_rgb()

    def scene(self) -> np.ndarray:
        return self._scene

    def save_file(self) -> None:
        path = _save_rgb(self, self.picture(), f"{self.file_stem}_시야시뮬레이션", "시야 시뮬레이션 저장")
        if path:
            self.lbl_done.setText(f"저장했습니다: {path}")

    def copy(self) -> None:
        QApplication.clipboard().setImage(to_qimage(self.picture()))
        self.lbl_done.setText("클립보드에 복사했습니다")


# ------------------------------------------------------------------------------------------------------
# 변화 지도
# ------------------------------------------------------------------------------------------------------
@dataclass
class Shot:
    """A photo for 변화 지도: its picture is read when it is first compared (``load`` gives the RGB)."""
    image_id: int
    when: str                                  # "YYYY-MM-DD HH:MM:SS"
    caption: str
    load: object                               # () -> rgb or None
    circle: tuple | None = None
    disc: tuple | None = None
    fovea: tuple | None = None

    @property
    def day(self) -> str:
        return self.when[:10]


class ChangeDialog(QDialog):
    """``current``: the photo asked from; ``others``: the other photos of the same eye (newest first). The
    older of the two compared is laid on the newer one: left of the line the older, right the newer."""

    def __init__(self, current: Shot, others: list[Shot], *, start: int = 0, title_line: str = "",
                 file_stem: str = "변화", parent=None):
        super().__init__(parent)
        self.setWindowTitle("변화 지도" + (f" — {title_line}" if title_line else ""))
        self.resize(1280, 860)
        self.current, self.others, self.file_stem = current, list(others), file_stem
        self.at = 0.5
        self.fit: C.Fit | None = None
        self._old = self._new = self._both = self._maps = None
        self.view = _View("비교할 같은 눈의 다른 날짜 사진이 없습니다")
        self.view.overlay = self._overlay
        self.view.pressed.connect(self._drag)
        self.view.moved.connect(self._drag)
        self.combo = QComboBox()
        for s in self.others:
            self.combo.addItem(f"{s.day or '날짜 없음'}  {s.caption}".strip(), s.image_id)
        self.combo.setCurrentIndex(min(max(0, start), max(0, len(self.others) - 1)))
        self.combo.currentIndexChanged.connect(lambda _i: self._compare())
        self.c_mark = QCheckBox("달라진 곳을 색으로 표시")
        self.c_mark.setChecked(True)
        self.c_mark.toggled.connect(lambda _on: self._draw())
        self.s_sens = _Slider("민감도", C.SENSITIVITY[0], C.SENSITIVITY[1], C.SENSITIVITY[2], 1, lambda v: f"{v:.0f}")
        self.s_sens.changed.connect(lambda _v: self._marks())
        self.lbl_fit = _note()
        self.lbl_sides = _note()
        legend = QLabel(f"<span style='color:rgb{C.DARKER}'>■</span> 새 사진에서 더 어두워진 곳 (출혈 · 색소)<br>"
                        f"<span style='color:rgb{C.BRIGHTER}'>■</span> 새 사진에서 더 밝아진 곳 (삼출물 · 위축 · 반흔)")
        legend.setTextFormat(Qt.TextFormat.RichText)
        legend.setWordWrap(True)
        warn = _note(C.NOTE)
        warn.setStyleSheet(f"color:{theme.ORANGE}")
        b_save = QPushButton("그림 저장…")
        b_save.setObjectName("primary")
        b_save.clicked.connect(self.save_file)
        b_close = QPushButton("닫기")
        b_close.clicked.connect(self.accept)
        self.lbl_done = _note()
        lay = QHBoxLayout(self)
        lay.addWidget(self.view, 1)
        lay.addWidget(_side(card("비교할 사진", self.combo, self.lbl_sides, self.lbl_fit),
                            card("달라진 곳", self.c_mark, self.s_sens, legend),
                            _note("사진 위에서 좌우로 끌면 경계선이 움직입니다 — 선 왼쪽이 예전 사진, 오른쪽이 새 사진."),
                            warn, b_save, b_close, self.lbl_done))
        self._compare()

    # -- the two photos ---------------------------------------------------------------------------------
    def _compare(self) -> None:
        self._old = self._new = self._both = self._maps = self.fit = None
        i = self.combo.currentIndex()
        other = self.others[i] if 0 <= i < len(self.others) else None
        if other is None:
            self.view.set_rgb(None)
            return
        older, newer = sorted((self.current, other), key=lambda s: (s.when, s.image_id))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            a, b = older.load(), newer.load()
            if a is None or b is None:
                self.lbl_fit.setText("사진을 읽지 못했습니다")
                self.view.set_rgb(None)
                return
            (a, ka), (b, kb) = _fit(a), _fit(b)

            def at(shot, k):
                scale = lambda p: None if p is None else tuple(v * k for v in p)      # noqa: E731
                return scale(shot.circle), (scale(shot.disc), scale(shot.fovea))
            (ca, ma), (cb, mb) = at(older, ka), at(newer, kb)
            self.fit = C.register(a, b, old_circle=ca, new_circle=cb, old_marks=ma, new_marks=mb)
            self._old, self._both = C.applied(a, self.fit, b.shape)
            self._new = b
        finally:
            QApplication.restoreOverrideCursor()
        self.lbl_sides.setText(f"왼쪽: {older.day or '예전'}  ·  오른쪽: {newer.day or '새 사진'}")
        self._marks()

    def _marks(self) -> None:
        if self._new is None:
            return
        self._maps = C.difference(self._new, self._old, self._both, int(self.s_sens.value()))
        dark, bright = C.changed_share(*self._maps, self._both)
        said = self.fit.text
        if self.fit.how != "none":
            said += f"\n표시된 넓이: 어두워짐 {dark * 100:.1f}% · 밝아짐 {bright * 100:.1f}%"
        self.lbl_fit.setText(said)
        self._draw()

    def _draw(self) -> None:
        if self._new is None:
            return
        old, new = self._old, self._new
        if self.c_mark.isChecked() and self._maps is not None:
            old, new = C.marked(old, *self._maps), C.marked(new, *self._maps)
        self.view.set_rgb(C.swipe(old, new, self.at))

    def _overlay(self, p: QPainter) -> None:
        if self._new is None:
            return
        h, w = self._new.shape[:2]
        x = self.at * w
        s = max(1.0, 1.0 / max(1e-6, self.view.scale()))
        p.setPen(QPen(QColor(0, 0, 0, 160), 4 * s))
        p.drawLine(QPointF(x, 0), QPointF(x, h))
        p.setPen(QPen(QColor(255, 255, 255), 1.6 * s))
        p.drawLine(QPointF(x, 0), QPointF(x, h))

    def _drag(self, x: float, _y: float) -> None:
        if self._new is not None:
            self.set_at(x / self._new.shape[1])

    def set_at(self, at: float) -> None:
        self.at = float(min(1.0, max(0.0, at)))
        self._draw()

    def picture(self) -> np.ndarray | None:
        return self.view.render_rgb()

    def save_file(self) -> None:
        pic = self.picture()
        if pic is None:
            return
        path = _save_rgb(self, pic, f"{self.file_stem}_변화지도", "변화 지도 저장")
        if path:
            self.lbl_done.setText(f"저장했습니다: {path}")


# ------------------------------------------------------------------------------------------------------
# 환자용 한 장 요약
# ------------------------------------------------------------------------------------------------------
PAGE_W, PAGE_H = 1240.0, 1754.0          # A4 at 150 dots an inch: the page is laid out in these units
MARGIN = 70.0
INK, INK2, RULE = QColor(28, 28, 30), QColor(95, 95, 100), QColor(205, 205, 210)
BLUE, AMBER = QColor(0, 96, 190), QColor(176, 96, 0)


def _font(px: float, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(theme.font_families())
    f.setPixelSize(int(round(px)))
    f.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    return f


def _text(p: QPainter, rect: QRectF, text: str, px: float, color: QColor = INK, bold: bool = False,
          align=Qt.AlignmentFlag.AlignLeft) -> float:
    """``text`` wrapped in ``rect``; the height it took."""
    p.setFont(_font(px, bold))
    p.setPen(color)
    flags = int(align | Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap)
    r = p.boundingRect(rect, flags, text)
    p.drawText(rect, flags, text)
    return r.height()


def _picture(p: QPainter, rgb: np.ndarray, box: QRectF, radius: float = 10.0) -> QRectF:
    """``rgb`` as large as fits in ``box`` (centred, round corners); where it went."""
    k = min(box.width() / rgb.shape[1], box.height() / rgb.shape[0])
    w, h = rgb.shape[1] * k, rgb.shape[0] * k
    rect = QRectF(box.center().x() - w / 2, box.top(), w, h)
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    p.save()
    p.setClipPath(path)
    p.drawImage(rect, to_qimage(np.ascontiguousarray(rgb)))
    p.restore()
    return rect


def _heading(p: QPainter, y: float, text: str, extra: str = "") -> float:
    p.setFont(_font(25, True))
    p.setPen(BLUE)
    p.drawText(QPointF(MARGIN, y + 26), text)
    if extra:
        x = MARGIN + p.fontMetrics().horizontalAdvance(text) + 14
        p.setFont(_font(18))
        p.setPen(AMBER)
        p.drawText(QPointF(x, y + 25), extra)
    return y + 42


def paint_handout(p: QPainter, page: QRectF, h: H.Handout) -> None:
    """The page drawn into ``page`` (device units) — the same drawing for the preview, the PDF and the printer."""
    p.save()
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
                     | QPainter.RenderHint.TextAntialiasing)
    k = min(page.width() / PAGE_W, page.height() / PAGE_H)
    p.translate(page.left() + (page.width() - PAGE_W * k) / 2, page.top())
    p.scale(k, k)
    inner = PAGE_W - 2 * MARGIN
    # head
    y = MARGIN
    _text(p, QRectF(MARGIN, y, inner, 50), H.TITLE, 38, INK, True)
    _text(p, QRectF(MARGIN, y + 8, inner, 30), h.issued, 18, INK2, align=Qt.AlignmentFlag.AlignRight)
    y += 58
    _text(p, QRectF(MARGIN, y, inner, 30), "  ·  ".join(x for x in (h.patient, h.exam) if x), 22, INK)
    y += 40
    p.setPen(QPen(RULE, 2))
    p.drawLine(QPointF(MARGIN, y), QPointF(PAGE_W - MARGIN, y))
    y += 20
    pic = D.picture(h.disease, h.stage) if h.disease in D.BY_NAME else None
    parts = (pic is not None) + (h.sight is not None)
    # today's photo(s)
    if h.photos:
        y = _heading(p, y, "안저 사진")
        ph = (560.0, 430.0, 330.0)[parts]
        n = min(2, len(h.photos))
        gap = 24.0
        w = (inner - gap * (n - 1)) / n
        for i, (rgb, caption) in enumerate(h.photos[:n]):
            box = QRectF(MARGIN + i * (w + gap), y, w, ph)
            rect = _picture(p, rgb, box)
            _text(p, QRectF(box.left(), rect.bottom() + 6, w, 26), caption, 18, INK2, align=Qt.AlignmentFlag.AlignHCenter)
        y += ph + 44
    # the disease talked about
    if pic is not None:
        d = pic.disease
        name = d.name + (f" — {pic.stage_name}" if len(d.stages) > 1 else "")
        y = _heading(p, y, name, H.NOTE_MODEL)
        side = 250.0
        _picture(p, pic.fundus, QRectF(MARGIN, y, side, side))
        sw = side * pic.sight.shape[1] / pic.sight.shape[0]
        _picture(p, pic.sight, QRectF(MARGIN + side + 16, y, sw, side))
        _text(p, QRectF(MARGIN, y + side + 4, side, 24), "안저 모식도", 16, INK2, align=Qt.AlignmentFlag.AlignHCenter)
        _text(p, QRectF(MARGIN + side + 16, y + side + 4, sw, 24), "이렇게 보일 수 있습니다", 16, INK2,
              align=Qt.AlignmentFlag.AlignHCenter)
        tx = MARGIN + side + 16 + sw + 22
        tw = PAGE_W - MARGIN - tx
        ty = y
        for label, body in (("어떤 병인가", d.about), ("증상", d.symptoms), ("치료 · 관리", d.care)):
            ty += _text(p, QRectF(tx, ty, tw, 26), label, 17, BLUE, True) + 1
            ty += _text(p, QRectF(tx, ty, tw, 400), body, 16.5, INK) + 9
        y = max(y + side + 30, ty) + 4
        if len(d.stages) > 1:
            y += _text(p, QRectF(MARGIN, y, inner, 120), pic.stage_text, 17, INK2) + 6
        y += 14
    # where the marked lesions lie in what the patient sees
    if h.sight is not None:
        y = _heading(p, y, "표시한 병변이 보이는 곳", F.NOTE)
        sh = 210.0
        rect = _picture(p, h.sight, QRectF(MARGIN, y, 330, sh))
        tx = MARGIN + rect.width() + 22
        lines = "\n".join(h.sight_lines[:6]) or ""
        _text(p, QRectF(tx, y, PAGE_W - MARGIN - tx, sh),
              "사진에 표시한 병변 자리를 환자분이 보는 풍경 위에 옮긴 그림입니다 (흰 십자 = 보는 곳).\n" + lines, 17, INK)
        y += sh + 26
    # the doctor's note
    foot = PAGE_H - MARGIN - 62
    y = _heading(p, y, "의사 메모")
    box = QRectF(MARGIN, y, inner, max(70.0, min(190.0, foot - y - 14)))
    p.setPen(QPen(RULE, 2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(box, 10, 10)
    if h.memo:
        _text(p, box.adjusted(16, 12, -16, -10), h.memo, 20, INK)
    # foot
    p.setPen(QPen(RULE, 2))
    p.drawLine(QPointF(MARGIN, foot), QPointF(PAGE_W - MARGIN, foot))
    _text(p, QRectF(MARGIN, foot + 10, inner, 60), H.FOOTER, 15, INK2)
    p.restore()


def handout_image(h: H.Handout, width: int = 1240) -> QImage:
    """The page as a picture (white paper)."""
    img = QImage(width, int(round(width * PAGE_H / PAGE_W)), QImage.Format.Format_RGB888)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    paint_handout(p, QRectF(0, 0, img.width(), img.height()), h)
    p.end()
    return img


def write_pdf(path: str | Path, h: H.Handout) -> None:
    """The page as a one-page A4 PDF."""
    pdf = QPdfWriter(str(path))
    pdf.setResolution(300)
    pdf.setTitle(H.TITLE)
    pdf.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                                  QMarginsF(0, 0, 0, 0)))
    p = QPainter(pdf)
    if not p.isActive():
        raise OSError(f"PDF 파일을 만들 수 없습니다: {path}")
    size = pdf.pageLayout().fullRectPixels(pdf.resolution())
    paint_handout(p, QRectF(0, 0, size.width(), size.height()), h)
    p.end()


class HandoutDialog(QDialog):
    """``photos``: ``[(rgb, caption), …]`` — the photo asked from first, then (if any) the other eye's;
    ``sight``: ``(scene, lines)`` of the photo's pins or None; ``disease``: the one to start with."""

    def __init__(self, patient: str, exam: str, photos: list, *, sight=None, disease: str | None = None,
                 file_stem: str = "설명자료", parent=None):
        super().__init__(parent)
        self.setWindowTitle("환자용 한 장 요약")
        self.resize(1120, 900)
        self.patient, self.exam, self.photos, self.sight, self.file_stem = patient, exam, list(photos), sight, file_stem
        self.view = _View("")
        self.c_disease = QComboBox()
        self.c_disease.addItem("(질환 설명 없이)", None)
        for d in D.DISEASES[1:]:                       # (the first is 정상 안저)
            self.c_disease.addItem(d.name, d.name)
        self.c_stage = QComboBox()
        self.c_fellow = QCheckBox("반대쪽 눈 사진도 함께")
        self.c_fellow.setChecked(len(self.photos) > 1)
        self.c_fellow.setEnabled(len(self.photos) > 1)
        self.c_sight = QCheckBox("표시한 병변이 보이는 곳 (시야 시뮬레이션)")
        self.c_sight.setChecked(sight is not None)
        self.c_sight.setEnabled(sight is not None)
        if sight is None:
            self.c_sight.setToolTip("사진에 병변 핀을 꽂아 두면 넣을 수 있습니다")
        self.memo = QPlainTextEdit()
        self.memo.setPlaceholderText("환자분께 드릴 말 한두 줄 (예: 3개월 뒤 다시 검사합니다. 혈당 조절이 중요합니다.)")
        self.memo.setFixedHeight(120)
        self.lbl_count = _note()
        b_pdf = QPushButton("PDF로 저장…")
        b_pdf.setObjectName("primary")
        b_pdf.clicked.connect(self.save_pdf)
        b_print = QPushButton("인쇄…")
        b_print.clicked.connect(self.print_page)
        b_close = QPushButton("닫기")
        b_close.clicked.connect(self.accept)
        self.lbl_done = _note()
        warn = _note("환자 이름이 들어가는 자료입니다 — 환자 본인에게만 드리세요. 질환 그림은 설명용 모형입니다.")
        warn.setStyleSheet(f"color:{theme.ORANGE}")
        lay = QHBoxLayout(self)
        lay.addWidget(self.view, 1)
        lay.addWidget(_side(card("질환 설명", self.c_disease, self.c_stage), card("넣을 것", self.c_fellow, self.c_sight),
                            card("의사 메모", self.memo, self.lbl_count), warn, b_pdf, b_print, b_close, self.lbl_done))
        self.c_disease.currentIndexChanged.connect(lambda _i: self._disease_changed())
        self.c_stage.currentIndexChanged.connect(lambda _i: self._draw())
        self.c_fellow.toggled.connect(lambda _on: self._draw())
        self.c_sight.toggled.connect(lambda _on: self._draw())
        self.memo.textChanged.connect(self._draw)
        i = self.c_disease.findData(disease) if disease else 0
        self.c_disease.setCurrentIndex(max(0, i))
        self._disease_changed()

    def _disease_changed(self) -> None:
        d = D.BY_NAME.get(self.c_disease.currentData() or "")
        blk = self.c_stage.blockSignals(True)
        self.c_stage.clear()
        for s in (d.stages if d is not None else ()):
            self.c_stage.addItem(s.name)
        self.c_stage.setEnabled(d is not None and len(d.stages) > 1)
        self.c_stage.blockSignals(blk)
        self._draw()

    def handout(self) -> H.Handout:
        photos = self.photos if self.c_fellow.isChecked() else self.photos[:1]
        if len(photos) == 2 and "OS" in photos[0][1][:3]:        # OD on the left, as the examiner faces the patient
            photos = photos[::-1]
        use_sight = self.sight is not None and self.c_sight.isChecked()
        return H.Handout(patient=self.patient, exam=self.exam, issued=f"발행일 {date.today().isoformat()}",
                         photos=photos, disease=self.c_disease.currentData(), stage=max(0, self.c_stage.currentIndex()),
                         sight=self.sight[0] if use_sight else None, sight_lines=list(self.sight[1]) if use_sight else [],
                         memo=H.clean_memo(self.memo.toPlainText()))

    def _draw(self) -> None:
        h = self.handout()
        lines = [ln for ln in self.memo.toPlainText().splitlines() if ln.strip()]
        over = len(lines) > H.MEMO_LINES or sum(len(" ".join(ln.split())) for ln in lines) + len(lines) - 1 > H.MEMO_MAX
        self.lbl_count.setText(f"{len(h.memo)} / {H.MEMO_MAX}자 · {H.MEMO_LINES}줄까지"
                               + ("  — 넘는 부분은 빠집니다" if over else ""))
        self.view.set_image(handout_image(h, 1000))

    def save_pdf(self) -> str:
        path, _ = QFileDialog.getSaveFileName(self, "환자용 한 장 요약 저장", f"{self.file_stem}.pdf", "PDF (*.pdf)")
        if not path:
            return ""
        try:
            write_pdf(path, self.handout())
        except OSError as e:
            QMessageBox.warning(self, "환자용 한 장 요약", str(e))
            return ""
        self.lbl_done.setText(f"저장했습니다: {path}")
        return path

    def print_page(self) -> None:
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        if QPrintDialog(printer, self).exec() != QPrintDialog.DialogCode.Accepted:
            return
        p = QPainter(printer)
        size = printer.pageLayout().paintRectPixels(printer.resolution())
        paint_handout(p, QRectF(0, 0, size.width(), size.height()), self.handout())
        p.end()
        self.lbl_done.setText("인쇄를 보냈습니다")

