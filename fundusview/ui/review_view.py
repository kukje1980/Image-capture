"""검토 tab — a multi-view of the patient's photos: both eyes side by side, an eye next to its
earlier exams, or as many photos as are picked in the timeline.

Layout (top to bottom): a bar · the cells (1, 2, 4, 8, 16 or 32 photos) · the timeline.

It opens on a **stage** (배치), two cells:
  양안      left = OD, right = OS: each eye's photo of the current exam (review.eye_photo); an eye
            not taken in that exam shows its newest earlier photo, tagged 이전.
  OD 비교   left = the eye's photo of an earlier exam (이전), right = the current exam (현재).
  OS 비교   ``[`` / ``]`` (or the small ◀ ▶ on the left cell) step through the earlier exams.
            A compare stage needs an earlier exam of that eye.

Clicking photos in the timeline **selects** them (numbered): the cells then show the selected
photos, in the smallest layout that holds them; with none selected the stage comes back. The
layout control sets the number of cells by hand, ◀ ▶ (← →) page through the *pool* — the
selection, or all photos the timeline lists — and a double click shows one photo alone (again:
back).

The cells are ``ImageView``s (wheel = zoom at the cursor, drag = move); 연동 keeps the zoom and
place of all cells together, as fractions of the photo, so photos of different sizes stay on the
same spot. 보기 shows one colour channel (감각망막 = green, 맥락막 = red). One or two cells show
the whole photo; more cells show a reduced one, read in the background (``imaging.load_reduced``).
The photos are shown as stored — the image-processing toolbar's adjustments belong to the 2D view.
The buttons at the end hand the active cell's photo to the 2D view, the 3D eye or the glaucoma window.
"""
from __future__ import annotations

from collections import OrderedDict

import numpy as np

from PySide6.QtCore import QByteArray, QEvent, QMimeData, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QDrag, QFont, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractButton, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QSizePolicy,
    QToolButton, QVBoxLayout, QWidget,
)

from .. import imaging, review
from . import theme
from .image_view import ImageView
from .thumbs import PICK_COLOR, eye_badge, paint_eye_badge, thumb_pixmap
from .widgets import FlowLayout, Segmented, Switch, vline

MIME = "application/x-fundusview-image"
STAGES = (("ou", "양안 (OD | OS)"), ("od", "OD 비교* (이전 | 현재)"), ("os", "OS 비교* (이전 | 현재)"))
NO_PRIOR = " — 이전 검사 없음"
# key, label, colour channel of imaging.adjust
VIEWS = (("color", "컬러", "rgb"), ("retina", "감각망막 (적색 제거)", "green"), ("choroid", "맥락막 (녹색 제거)", "red"))
EYE_NAMES = {"OD": "OD 우안", "OS": "OS 좌안"}
LENS_MIN, LENS_MAX = 1.5, 6.0


def _rect(view: QWidget) -> QRect:
    """Where a view lies in its parent (``ImageView.geometry`` is the photo's geometry, not this)."""
    return QRect(view.pos(), view.size())


def photo_caption(row) -> str:
    """``2026-01-15 10:20`` of a photo."""
    return " ".join(x for x in (row["exam_date"] or "날짜 없음", (row["exam_time"] or "")[:5]) if x)


def _chip(p: QPainter, text: str, x: float, y: float, color: str, px: int = 12) -> QRectF:
    """Text on a dark pill (legible on a bright retina); returns its rectangle."""
    f = QFont(p.font())
    f.setPixelSize(px)
    f.setWeight(QFont.Weight.DemiBold)
    p.setFont(f)
    fm = p.fontMetrics()
    rect = QRectF(x, y, fm.horizontalAdvance(text) + 14, fm.height() + 5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(12, 12, 14, 205))
    p.drawRoundedRect(rect, 6, 6)
    p.setPen(QColor(color))
    p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
    return rect


class ReviewViewport(ImageView):
    """One cell of the review: which eye, when, 이전 / 현재 on the photo; a frame when active.
    ``compact`` (0 – 2) shrinks the writing for the small cells of the larger layouts."""
    pressed = Signal()                   # any press here: this is the active view now
    doubleClicked = Signal()             # this photo alone / back to the layout
    middleClicked = Signal(QPoint)       # position in the viewport — toggles the 확대창 there
    dropped = Signal(int)                # a timeline photo was dropped here (image id)
    menuRequested = Signal(QPoint)       # global position of a right click

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBackgroundBrush(QBrush(QColor(theme.BLACK)))
        self.setViewportUpdateMode(ImageView.ViewportUpdateMode.FullViewportUpdate)   # the chips stay put
        self.set_tool("pan")             # plain drag moves the photo
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)   # moved by dragging; the
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)     # mini-map shows where
        self.crossfade = True
        self.setAcceptDrops(True)
        self.row = None                  # images row on show
        self.tag = ""                    # 이전 / 현재 / ""
        self.active = False
        self.empty_text = ""
        self.compact = 0                 # 1: smaller writing (8 cells), 2: eye + date only (16 / 32)
        self.pending = None              # the reduced photo still being read (the thumbnail stands in)
        self._drop = False

    def set_photo(self, row, rgb, tag: str = "", keep_view: bool = False) -> None:
        state = self.view_state() if keep_view else None
        self.row, self.tag = (row if rgb is not None else None), tag
        self.set_rgb(rgb)
        self.set_view_state(state)
        self.viewport().update()

    def set_active(self, on: bool) -> None:
        if on != self.active:
            self.active = on
            self.viewport().update()

    # -- mouse: middle click = 확대창, right click = menu, the rest as in every photo view ------------
    def mousePressEvent(self, e):
        self.pressed.emit()
        if e.button() == Qt.MouseButton.MiddleButton:
            self.middleClicked.emit(e.position().toPoint())
            return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit()        # (화면 맞춤 is the 맞춤 button here)
        e.accept()

    def _context_menu(self, gpos: QPoint, sp: QPointF) -> None:
        self.menuRequested.emit(gpos)

    # -- photos dragged from the timeline --------------------------------------------------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            self._drop = True
            self.viewport().update()
            e.acceptProposedAction()
        else:
            e.ignore()                   # files: the window imports them

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        self._drop = False
        self.viewport().update()

    def dropEvent(self, e):
        self._drop = False
        self.viewport().update()
        if not e.mimeData().hasFormat(MIME):
            e.ignore()
            return
        try:
            image_id = int(bytes(e.mimeData().data(MIME)).decode())
        except ValueError:
            return
        e.acceptProposedAction()
        self.dropped.emit(image_id)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.viewport().rect()
        if self.row is not None and self.has_image():
            c = self.compact
            pad, px = (10, 13) if c == 0 else (6, 11) if c == 1 else (4, 10)
            badge = paint_eye_badge(p, self.row["laterality"], pad, pad, px)
            text = photo_caption(self.row) if c < 2 else (self.row["exam_date"] or "날짜 없음")
            chip = _chip(p, text, badge.right() + (6 if c == 0 else 4), pad - 1, theme.TEXT, px - 1)
            if self.tag and c < 2:
                _chip(p, self.tag, chip.right() + 6, pad - 1, theme.YELLOW if self.tag == "이전" else theme.GREEN,
                      px - 1)
        elif self.empty_text:
            f = QFont(p.font())
            f.setPixelSize(14 if self.compact == 0 else 11)
            p.setFont(f)
            p.setPen(QColor(theme.TEXT3 if self.compact == 0 else theme.TEXT4))
            p.drawText(r.adjusted(16, 16, -16, -16), int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                       self.empty_text)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self._drop:
            p.setPen(QPen(QColor(theme.YELLOW), 3))
            p.drawRect(QRectF(r).adjusted(1.5, 1.5, -1.5, -1.5))
        elif self.active:
            p.setPen(QPen(QColor(theme.ACCENT), 2))
            p.drawRect(QRectF(r).adjusted(1, 1, -1, -1))
        else:
            p.setPen(QPen(QColor(theme.CARD), 1))
            p.drawRect(QRectF(r).adjusted(0.5, 0.5, -0.5, -0.5))
        p.end()


class Magnifier(QWidget):
    """확대창: a square that floats over the cells and shows what is under its centre, larger.

    Drag = move · wheel = 1.5× – 6× · right click (or double click) = show the *next* cell's
    photo at the same place (nothing with one cell) · middle click = close. ``views`` = the cells on screen."""
    closed = Signal()
    SIDE = 200

    def __init__(self, stage: QWidget, views):
        super().__init__(stage)
        self.views = list(views)
        self.mag = 2.5
        self.other = False
        self._grab: QPoint | None = None
        self.setFixedSize(self.SIDE, self.SIDE)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip("드래그: 옮기기 · 휠: 배율 (1.5×–6×) · 오른쪽 클릭: 반대쪽 화면의 같은 곳 · 가운데 클릭: 닫기")
        self.hide()

    def host(self) -> int:
        """Index of the view under the centre of the square (−1: none)."""
        c = self.geometry().center()
        return next((i for i, v in enumerate(self.views) if _rect(v).contains(c)), -1)

    def source(self):
        """``(view shown, source rectangle in its photo's pixels)`` or None."""
        i = self.host()
        if i < 0 or not self.views[i].has_image():
            return None
        host = self.views[i]
        shown = self.views[(i + 1) % len(self.views)] if self.other and len(self.views) > 1 else host
        if not shown.has_image():
            return None
        sp = host.mapToScene(host.viewport().mapFrom(self.parentWidget(), self.geometry().center()))
        hp, pm = host._pix.pixmap(), shown._pix.pixmap()
        # the other photo is read at the same place as a fraction of the photo, at the host's scale
        kx, ky = pm.width() / max(hp.width(), 1), pm.height() / max(hp.height(), 1)
        half = self.SIDE / 2.0 / (host.zoom * self.mag)
        return shown, QRectF((sp.x() - half) * kx, (sp.y() - half) * ky, 2 * half * kx, 2 * half * ky)

    def caption(self) -> str:
        src = self.source()
        if src is None or src[0].row is None:
            return "사진 위로 옮기세요"
        row = src[0].row
        return (f"{self.mag:.1f}× · {eye_badge(row['laterality'])[0]} {row['exam_date'] or ''}".rstrip()
                + (" · 반대쪽" if self.other and len(self.views) > 1 else ""))

    def move_to(self, centre: QPoint) -> None:
        """Put the centre at ``centre`` (stage coordinates), kept inside the stage."""
        stage = self.parentWidget().rect()
        h = self.SIDE // 2
        x = max(h, min(max(h, stage.width() - h), centre.x()))
        y = max(h, min(max(h, stage.height() - h), centre.y()))
        self.move(x - h, y - h)
        self.update()

    def set_mag(self, mag: float) -> None:
        self.mag = max(LENS_MIN, min(LENS_MAX, mag))
        self.update()

    def toggle_other(self) -> None:
        self.other = not self.other and len(self.views) > 1      # one cell: there is no other photo
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton:
            self.closed.emit()
        elif e.button() == Qt.MouseButton.RightButton:
            self.toggle_other()
        elif e.button() == Qt.MouseButton.LeftButton:
            self._grab = e.position().toPoint()
        e.accept()

    def mouseMoveEvent(self, e):
        if self._grab is not None:
            top_left = self.mapToParent(e.position().toPoint()) - self._grab
            self.move_to(top_left + QPoint(self.SIDE // 2, self.SIDE // 2))
        e.accept()

    def mouseReleaseEvent(self, e):
        self._grab = None
        e.accept()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.toggle_other()
        e.accept()

    def wheelEvent(self, e):
        self.set_mag(self.mag * 1.15 ** (e.angleDelta().y() / 120.0))
        e.accept()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        full = QRectF(self.rect())
        p.fillRect(full, QColor(theme.BLACK))
        src = self.source()
        if src is not None:
            pm, rect = src[0]._pix.pixmap(), src[1]
            part = rect.intersected(QRectF(pm.rect()))
            if not part.isEmpty():               # the part of the square that lies on the photo
                sx, sy = full.width() / rect.width(), full.height() / rect.height()
                target = QRectF((part.x() - rect.x()) * sx, (part.y() - rect.y()) * sy,
                                part.width() * sx, part.height() * sy)
                p.drawPixmap(target, pm, part)
        f = QFont(p.font())
        f.setPixelSize(11)
        p.setFont(f)
        bar = QRectF(0, full.height() - 20, full.width(), 20)
        p.fillRect(bar, QColor(12, 12, 14, 205))
        p.setPen(QColor(theme.TEXT))
        p.drawText(bar.adjusted(7, 0, -7, 0), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                   self.caption())
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(theme.ORANGE if self.other and len(self.views) > 1 else theme.ACCENT), 2))
        p.drawRoundedRect(full.adjusted(1, 1, -1, -1), 6, 6)
        p.end()


class _TimelineThumb(QAbstractButton):
    """A photo of the timeline: thumbnail, eye badge, a frame while it is on one of the cells, a
    yellow frame and number while it is selected. Click = select / deselect; drag = drop it on a cell."""
    SIDE = 76

    def __init__(self, row, parent=None):
        super().__init__(parent)
        self.image_id = row["id"]
        self.eye = row["laterality"] or ""
        self.shown = False
        self.rank = 0                    # place in the selection (0 = not selected)
        self._pm = thumb_pixmap(row["thumb_path"], self.SIDE - 4)
        self._press: QPoint | None = None
        self.setFixedSize(self.SIDE, self.SIDE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        from ..models import MODALITY_LABELS
        kind = MODALITY_LABELS.get(row["modality"] or "", row["modality"] or "")
        self.setToolTip(" · ".join(x for x in (photo_caption(row), eye_badge(self.eye)[0], kind) if x))

    def sizeHint(self) -> QSize:
        return QSize(self.SIDE, self.SIDE)

    def set_shown(self, on: bool) -> None:
        if on != self.shown:
            self.shown = on
            self.update()

    def set_rank(self, rank: int) -> None:
        if rank != self.rank:
            self.rank = rank
            self.update()

    def mousePressEvent(self, e):
        self._press = e.position().toPoint() if e.button() == Qt.MouseButton.LeftButton else None
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if (self._press is not None and e.buttons() & Qt.MouseButton.LeftButton
                and (e.position().toPoint() - self._press).manhattanLength() > 8):
            self._press = None
            self.setDown(False)
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(MIME, QByteArray(str(self.image_id).encode()))
            drag.setMimeData(mime)
            if not self._pm.isNull():
                drag.setPixmap(self._pm)
                drag.setHotSpot(QPoint(self._pm.width() // 2, self._pm.height() // 2))
            drag.exec(Qt.DropAction.CopyAction)
            return
        super().mouseMoveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.BLACK))
        p.drawRoundedRect(r, 7, 7)
        if not self._pm.isNull():
            p.drawPixmap(int((self.width() - self._pm.width()) / 2), int((self.height() - self._pm.height()) / 2),
                         self._pm)
        paint_eye_badge(p, self.eye, 4, 4, 10)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self.rank:                        # selected: yellow frame, its number (as the multi picks)
            p.setPen(QPen(QColor(PICK_COLOR), 2 if self.shown else 1.5))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 7, 7)
            f = QFont(p.font())
            f.setBold(True)
            f.setPixelSize(11)
            p.setFont(f)
            d = 18.0
            dot = QRectF(r.right() - d - 4, r.top() + 4, d, d)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(PICK_COLOR))
            p.drawEllipse(dot)
            p.setPen(QColor("#111827"))
            p.drawText(dot, Qt.AlignmentFlag.AlignCenter, str(self.rank))
            p.setBrush(Qt.BrushStyle.NoBrush)
        if self.shown:
            p.setPen(QPen(QColor(theme.ACCENT), 2))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1) if not self.rank else r.adjusted(3, 3, -3, -3), 7, 7)
        elif not self.rank:
            p.setPen(QPen(QColor(theme.FILL2 if self.underMouse() else theme.FILL), 1))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
        p.end()

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()


class Timeline(QFrame):
    """The patient's photos by exam, newest exam first; folds away to its heading."""
    photoClicked = Signal(int)
    examClicked = Signal(str)
    eyeChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("timeline")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 6)
        lay.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.btn_fold = QPushButton("▾ 타임라인")
        self.btn_fold.setObjectName("plain")
        self.btn_fold.setCheckable(True)
        self.btn_fold.setChecked(True)
        self.btn_fold.setToolTip("타임라인 접기 / 펴기")
        self.btn_fold.toggled.connect(self.set_open)
        head.addWidget(self.btn_fold)
        self.lbl_count = QLabel("")
        self.lbl_count.setObjectName("caption")
        head.addWidget(self.lbl_count)
        # which eye's photos the strip lists (모두 = both and the photos without an eye)
        self.eye = ""
        self.eye_buttons = {}
        for key, label, tip in (("", "모두", "모든 사진"), ("OD", "OD", "우안(OD) 사진만"), ("OS", "OS", "좌안(OS) 사진만")):
            b = QPushButton(label)
            b.setToolTip(tip)
            self.eye_buttons[key] = b
        self.eye_buttons[""].setChecked(True)
        self.eye_seg = Segmented(list(self.eye_buttons.values()), on_card=False)
        self.eye_seg.setFixedWidth(168)
        self.eye_buttons[""].setChecked(True)
        for key, b in self.eye_buttons.items():
            b.toggled.connect(lambda on, key=key: on and self.set_eye(key))
        head.addWidget(self.eye_seg)
        self.lbl_hint = QLabel("사진을 누르면 고르기(번호) — 고른 사진만큼 화면이 나뉩니다 · 화면으로 끌어다 놓기 · "
                               "날짜를 누르면 그 검사가 현재 검사")
        self.lbl_hint.setObjectName("caption")
        self.lbl_hint.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)   # cut, not a wider window
        head.addWidget(self.lbl_hint, 1)
        lay.addLayout(head)
        self.body = QWidget()
        self.body.setObjectName("timelineBody")
        self.body_lay = QHBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        self.body_lay.setSpacing(14)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("timelineScroll")
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.body)
        self.scroll.setFixedHeight(_TimelineThumb.SIDE + 44)
        self.scroll.viewport().installEventFilter(self)
        lay.addWidget(self.scroll)
        self.thumbs: list[_TimelineThumb] = []
        self.dates: list[QPushButton] = []
        self._groups: list = []
        self._current: str | None = None
        self._shown: set = set()
        self._selected: list = []

    def listed(self) -> list[int]:
        """Ids of the photos listed now (the eye filter applied), in the order of the strip."""
        return [t.image_id for t in self.thumbs]

    def mark_selected(self, ids) -> None:
        """Number the selected photos in the order they were picked."""
        self._selected = list(ids)
        rank = {iid: k + 1 for k, iid in enumerate(self._selected)}
        for t in self.thumbs:
            t.set_rank(rank.get(t.image_id, 0))

    def set_eye(self, eye: str) -> None:
        """List only the photos of ``eye`` ("OD" / "OS"); "" lists them all. Kept from patient to patient."""
        eye = eye if eye in self.eye_buttons else ""
        if not self.eye_buttons[eye].isChecked():
            self.eye_buttons[eye].setChecked(True)      # comes back here through toggled
            return
        if eye != self.eye:
            self.eye = eye
            self._rebuild()
            self.eyeChanged.emit(eye)

    def is_open(self) -> bool:
        return self.btn_fold.isChecked()

    def set_open(self, on: bool) -> None:
        if self.btn_fold.isChecked() != on:
            self.btn_fold.setChecked(on)
            return
        self.btn_fold.setText(("▾" if on else "▸") + " 타임라인")
        self.scroll.setVisible(on)
        self.lbl_hint.setVisible(on)

    def eventFilter(self, obj, e):
        if obj is self.scroll.viewport() and e.type() == QEvent.Type.Wheel:    # the wheel moves along the exams
            bar = self.scroll.horizontalScrollBar()
            d = e.angleDelta()
            bar.setValue(bar.value() - (d.y() if d.y() else d.x()))
            return True
        return super().eventFilter(obj, e)

    def set_exams(self, groups, current: str | None) -> None:
        """``groups`` = ``review.exams`` of the photos to list; ``current`` = the exam under review."""
        self._groups, self._current = list(groups), current
        self._rebuild()

    def _rebuild(self) -> None:
        current = self._current
        groups = self._groups
        if self.eye:                                    # the eye's photos only; exams without one drop out
            groups = [(d, [r for r in rows if r["laterality"] == self.eye]) for d, rows in groups]
            groups = [(d, rows) for d, rows in groups if rows]
        newest = self._groups[0][0] if self._groups else None
        while self.body_lay.count():
            item = self.body_lay.takeAt(0)
            old = item.widget()
            if old is not None:
                old.hide()                              # gone now, not a frame later under the new ones
                old.setParent(None)
                old.deleteLater()
        self.thumbs, self.dates = [], []
        n = 0
        for i, (d, rows) in enumerate(groups):
            day = QWidget()
            v = QVBoxLayout(day)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(3)
            marks = [m for m, on in (("현재", d == current), ("최근", d == newest and d != current)) if on]
            b = QPushButton(" · ".join([d or "날짜 없음"] + marks))
            b.setObjectName("timelineDate")
            b.setProperty("current", d == current)
            b.setProperty("exam", d)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip("이 검사를 현재 검사로 — 더 이른 검사가 이전 검사가 됩니다")
            b.clicked.connect(lambda _=False, d=d: self.examClicked.emit(d))
            v.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
            self.dates.append(b)
            row = QHBoxLayout()
            row.setSpacing(5)
            for r in rows:
                t = _TimelineThumb(r)
                t.clicked.connect(lambda _=False, iid=r["id"]: self.photoClicked.emit(iid))
                row.addWidget(t)
                self.thumbs.append(t)
                n += 1
            row.addStretch(1)
            v.addLayout(row)
            v.addStretch(1)
            self.body_lay.addWidget(day)
        self.body_lay.addStretch(1)
        what = f"{self.eye} 사진" if self.eye else "사진"
        self.lbl_count.setText(f"검사 {len(groups)}회 · {n}장" if n else f"{what} 없음")
        self.mark_shown(self._shown)
        self.mark_selected(self._selected)

    def mark_shown(self, ids) -> None:
        ids = self._shown = set(ids)
        for t in self.thumbs:
            t.set_shown(t.image_id in ids)


# cells of a layout: (columns, rows) — wide rather than tall, as the area is
LAYOUTS = {1: (1, 1), 2: (2, 1), 4: (2, 2), 8: (4, 2), 16: (4, 4), 32: (8, 4)}
# longest side of the photo read for a cell of that layout (0 = the whole photo): many cells never
# hold many full-size photos
SIDES = {1: 0, 2: 0, 4: 1600, 8: 900, 16: 640, 32: 448}
SMALL_BUDGET = 256 * 1024 * 1024         # bytes of reduced photos kept


def layout_for(n: int) -> int:
    """The smallest layout that holds ``n`` photos (32 at most — the arrows page beyond)."""
    return next((k for k in LAYOUTS if k >= n), 32)


class _Reader(QObject):
    """Reads reduced photos on worker threads (``imaging.load_reduced``) for the cells of the larger layouts."""
    loaded = Signal(object, object)       # (image id, side), RGB array (None: unreadable)

    def __init__(self, parent=None):
        super().__init__(parent)
        from concurrent.futures import ThreadPoolExecutor

        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="fundus-review")
        self.busy: set = set()

    def request(self, key, path: str) -> None:
        if key not in self.busy:
            self.busy.add(key)
            self._pool.submit(self._run, key, path)

    def _run(self, key, path: str) -> None:
        try:
            rgb = imaging.load_reduced(path, key[1])
        except Exception:
            rgb = None
        try:
            self.loaded.emit(key, rgb)
        except RuntimeError:              # the page is gone
            pass

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


class ReviewPage(QWidget):
    handOff = Signal(str, int, object)   # "2d" / "3d" / "glaucoma", image id, second image id (or None)
    examPicked = Signal(str)             # a date of the timeline was clicked
    status = Signal(str)

    def __init__(self, load, path_of=None, parent=None):
        """``load(row)`` returns the photo of an images row as an RGB array (None: unreadable);
        ``path_of(row)`` its file (None: missing) — with it the reduced photos of the larger layouts
        are read in the background."""
        super().__init__(parent)
        self.setObjectName("reviewPage")
        self._load, self._path_of = load, path_of
        self.rows: list = []             # the patient's photographs (sheets left out)
        self.current: str | None = None  # exam under review
        self.stage = "ou"
        self.prior = 0                   # which earlier exam the compare stage shows (0 = the latest)
        self.preset = True               # the cells show the stage's pair (else: a page of the pool)
        self.layout_n = 2                # cells on screen
        self.start = 0                   # pool index of the first cell (page of the pool)
        self.selection: list[int] = []   # image ids picked in the timeline, in the order picked
        self._back: dict | None = None   # where a double click came from (single photo → back)
        self.active = 0
        self.link = True
        self.view_mode = "color"
        self._syncing = False
        self._small: OrderedDict = OrderedDict()     # (image id, side) -> reduced RGB
        self._small_bytes = 0
        self._reader = _Reader(self)
        self._reader.loaded.connect(self._on_reduced)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # -- the bar (wraps onto a second line in a narrow window) --------------------------------
        bar = QWidget()
        bar.setObjectName("barReview")
        self.bar_lay = FlowLayout(bar)
        add = self.bar_lay.addWidget
        self.btn_prev = QPushButton("◀")
        self.btn_prev.setToolTip("앞의 사진들 (←) — 지금 배치의 장수만큼 넘깁니다")
        self.btn_prev.clicked.connect(lambda: self.page(-1))
        self.lbl_pos = QLabel("")
        self.lbl_pos.setObjectName("reviewPos")
        self.lbl_pos.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_pos.setMinimumWidth(74)
        self.lbl_pos.setToolTip("화면에 있는 사진 / 넘겨 볼 수 있는 사진 (고른 사진이 있으면 고른 사진, 없으면 타임라인의 사진)")
        self.btn_next = QPushButton("▶")
        self.btn_next.setToolTip("다음 사진들 (→)")
        self.btn_next.clicked.connect(lambda: self.page(1))
        for b in (self.btn_prev, self.btn_next):
            b.setObjectName("square")
            b.setFixedWidth(34)
        self.c_stage = QComboBox()
        self.c_stage.setToolTip("배치 — * 비교는 그 눈의 이전 검사가 있을 때 쓸 수 있습니다\n"
                                "([ / ] 로 더 이전 · 더 최근 검사) · 배치를 고르면 고른 사진이 해제됩니다")
        for key, label in STAGES:
            self.c_stage.addItem(label, key)
        fm = self.c_stage.fontMetrics()         # as wide as a stage's name; the list as its longest line
        self.c_stage.setFixedWidth(max(fm.horizontalAdvance(label) for _, label in STAGES) + 60)
        self.c_stage.view().setMinimumWidth(max(fm.horizontalAdvance(label + NO_PRIOR) for _, label in STAGES) + 44)
        self.c_stage.activated.connect(lambda i: self.set_stage(self.c_stage.itemData(i)))
        # how many photos at once
        self.layout_buttons = {n: QPushButton(str(n)) for n in LAYOUTS}
        for n, b in self.layout_buttons.items():
            cols, rows = LAYOUTS[n]
            b.setToolTip(f"사진 {n}장 ({cols} × {rows})" if n > 1 else "사진 1장 (화면을 두 번 눌러도 됩니다)")
        self.seg_layout = Segmented(list(self.layout_buttons.values()), on_card=False)
        self.seg_layout.setFixedWidth(34 * len(LAYOUTS) + 4)
        self.seg_layout.setToolTip("한 화면에 보는 사진 수")
        self.layout_buttons[2].setChecked(True)
        for n, b in self.layout_buttons.items():
            b.clicked.connect(lambda _=False, n=n: self.set_layout(n))
        self.btn_clear = QPushButton("선택 해제")
        self.btn_clear.setToolTip("고른 사진을 모두 해제하고 배치(양안 · 비교)로 돌아갑니다")
        self.btn_clear.clicked.connect(self.clear_selection)
        self.btn_clear.hide()
        for w in (self.btn_prev, self.lbl_pos, self.btn_next, self.c_stage, self.seg_layout, self.btn_clear, vline()):
            add(w)
        self.btn_fit = QPushButton("맞춤")
        self.btn_fit.setToolTip("사진 전체가 보이게")
        self.btn_fit.clicked.connect(self.fit)
        self.btn_out = QPushButton("−")
        self.btn_out.setToolTip("축소 (휠)")
        self.btn_out.clicked.connect(lambda: self.zoom_by(0.8))
        self.btn_in = QPushButton("+")
        self.btn_in.setToolTip("확대 (휠 — 커서가 가리키는 곳으로)")
        self.btn_in.clicked.connect(lambda: self.zoom_by(1.25))
        for b in (self.btn_out, self.btn_in):
            b.setObjectName("square")
            b.setFixedWidth(34)
        self.sw_link = Switch("연동", trailing=False)
        self.sw_link.setToolTip("화면에 있는 모든 사진의 확대·이동을 함께 움직입니다")
        self.sw_link.setChecked(True)
        self.sw_link.toggled.connect(self.set_link)
        for w in (self.btn_fit, self.btn_out, self.btn_in, self.sw_link, vline()):
            add(w)
        self.c_view = QComboBox()
        self.c_view.setToolTip("보기 — 컬러 / 감각망막: 녹색 성분만 (적색 제거, 혈관·출혈·신경섬유층) / "
                               "맥락막: 적색 성분만 (녹색 제거, 깊은 층)")
        for key, label, _ in VIEWS:
            self.c_view.addItem(label, key)
        self.c_view.currentIndexChanged.connect(lambda i: self.set_view_mode(self.c_view.itemData(i)))
        self.sw_lens = Switch("확대창", trailing=False)
        self.sw_lens.setToolTip("사진 위에 떠 있는 확대창 — 화면에서 가운데 버튼을 눌러도 그 자리에 켜고 끕니다")
        self.sw_lens.toggled.connect(lambda on: self.set_lens(on))
        for w in (self.c_view, self.sw_lens, vline()):
            add(w)
        self.btn_2d = QPushButton("2D 보기")
        self.btn_2d.setToolTip("고른 화면(파란 테두리)의 사진을 2D 보기로 — 확대·측정·영상 처리")
        self.btn_3d = QPushButton("3D 안구")
        self.btn_3d.setToolTip("고른 화면의 사진을 3D 안구 모형으로")
        self.btn_glaucoma = QPushButton("녹내장")
        self.btn_glaucoma.setToolTip("고른 화면의 사진으로 녹내장 분석 — 비교 배치에서는 이전 · 현재 두 장으로 경과 비교까지")
        for b, where in ((self.btn_2d, "2d"), (self.btn_3d, "3d"), (self.btn_glaucoma, "glaucoma")):
            b.clicked.connect(lambda _=False, where=where: self.hand_off(where))
            add(b)
        lay.addWidget(bar)

        # -- the cells (made when a layout first needs them) -----------------------------------------
        self.stage_w = QWidget()
        self.stage_w.setObjectName("reviewStage")
        self.grid = QGridLayout(self.stage_w)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(3)
        self.cells: list[ReviewViewport] = []
        lay.addWidget(self.stage_w, 1)
        self.lens = Magnifier(self.stage_w, [])
        self.lens.closed.connect(lambda: self.set_lens(False))
        self._apply_layout(2)
        self.cells[0].set_active(True)
        # ◀ 이전 검사 k/n ▶ on the left cell (compare stages)
        self.prior_nav = QWidget(self.cells[0])
        self.prior_nav.setObjectName("priorNav")
        pl = QHBoxLayout(self.prior_nav)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(4)
        self.btn_older = QToolButton()
        self.btn_older.setText("◀")
        self.btn_older.setToolTip("더 이전 검사 ( [ )")
        self.btn_older.clicked.connect(lambda: self.step_prior(1))
        self.lbl_prior = QLabel("")
        self.lbl_prior.setObjectName("priorPos")
        self.btn_newer = QToolButton()
        self.btn_newer.setText("▶")
        self.btn_newer.setToolTip("더 최근 검사 ( ] )")
        self.btn_newer.clicked.connect(lambda: self.step_prior(-1))
        for w in (self.btn_older, self.lbl_prior, self.btn_newer):
            pl.addWidget(w)
        self.prior_nav.hide()
        self.cells[0].installEventFilter(self)
        self.stage_w.installEventFilter(self)

        # -- the timeline ----------------------------------------------------------------------------
        self.timeline = Timeline()
        self.timeline.photoClicked.connect(self.toggle_select)
        self.timeline.examClicked.connect(self.examPicked.emit)
        self.timeline.eyeChanged.connect(self._on_eye)
        lay.addWidget(self.timeline)

        for seq, fn in (("Left", lambda: self.page(-1)), ("Right", lambda: self.page(1)),
                        ("[", lambda: self.step_prior(1)), ("]", lambda: self.step_prior(-1))):
            sc = QShortcut(QKeySequence(seq), self, context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
        self._sync_ui()

    def shutdown(self) -> None:
        self._reader.shutdown()

    # -- the cells -----------------------------------------------------------------------------------
    @property
    def views(self) -> list[ReviewViewport]:
        """The cells on screen."""
        return self.cells[:self.layout_n]

    def _make_cell(self) -> ReviewViewport:
        i = len(self.cells)
        v = ReviewViewport(self.stage_w)
        v.hide()
        v.pressed.connect(lambda i=i: self.set_active(i))
        v.doubleClicked.connect(lambda i=i: self._double(i))
        v.middleClicked.connect(lambda pos, i=i: self._middle(i, pos))
        v.dropped.connect(lambda iid, i=i: self.show_photo(iid, i))
        v.menuRequested.connect(lambda gpos, i=i: self._menu(i, gpos))
        v.zoomChanged.connect(lambda _, i=i: self._view_moved(i))
        v.horizontalScrollBar().valueChanged.connect(lambda _, i=i: self._view_moved(i))
        v.verticalScrollBar().valueChanged.connect(lambda _, i=i: self._view_moved(i))
        self.cells.append(v)
        return v

    def _apply_layout(self, n: int) -> None:
        """Lay ``n`` cells out (the photos are put on them by ``_fill``)."""
        n = n if n in LAYOUTS else 2
        while len(self.cells) < n:
            self._make_cell()
        cols, _ = LAYOUTS[n]
        self.layout_n = n
        for i, v in enumerate(self.cells):
            self.grid.removeWidget(v)
            if i < n:
                v.setMinimumSize(*((120, 70) if n <= 2 else (40, 30)))     # the window's least size stays
                v.compact = 0 if n <= 4 else 1 if n == 8 else 2
                v.crossfade = n <= 2
                v.set_navigator(n <= 8)
                self.grid.addWidget(v, i // cols, i % cols)
                v.show()
            else:
                v.hide()
                if v.row is not None or v.pending is not None:
                    v.pending = None
                    v.set_photo(None, None)                                 # a hidden cell keeps no photo
        rows_n = LAYOUTS[n][1]
        for c in range(8):                                # equal cells; the columns and rows not used take nothing
            self.grid.setColumnStretch(c, 1 if c < cols else 0)
        for r in range(4):
            self.grid.setRowStretch(r, 1 if r < rows_n else 0)
        if self.active >= n:
            self.active = 0
        for k, v in enumerate(self.cells):
            v.set_active(k == self.active)
        self.lens.views = self.views
        self.lens.raise_()
        b = self.layout_buttons[n]
        if not b.isChecked():
            b.setChecked(True)

    # -- photos ------------------------------------------------------------------------------------
    def set_photos(self, rows, current: str | None = None) -> None:
        """The patient's ``rows`` (images, any order) and the exam under review (None = the newest).
        The stage is kept when it is still possible; the cells show its default photos again."""
        rows = [r for r in rows if review.is_photo(r)]
        dates = review.exam_dates(rows)
        current = current if current in dates else (dates[0] if dates else None)
        # the same photos and the same exam again (a list refresh, a search): leave everything as the
        # user has it — zoom, stage, the prior on screen, the selection, the layout and the page
        key = (current, tuple((r["id"], r["exam_date"], r["exam_time"], r["laterality"], r["modality"]) for r in rows))
        if key == getattr(self, "_photos_key", None):
            self.rows = rows
            return
        self._photos_key = key
        self.rows, self.current = rows, current
        self.selection = []
        self.timeline.set_exams(review.exams(self.rows), self.current)
        self._sync_stages()
        self.set_stage(self.stage if self.stage_ok(self.stage) else "ou")

    def set_current_exam(self, exam_date: str) -> None:
        if exam_date != self.current:
            self.set_photos(self.rows, exam_date)

    def _row(self, image_id):
        return next((r for r in self.rows if r["id"] == image_id), None)

    def pool(self) -> list:
        """The photos one can page through: the selection if there is one, else the photos the
        timeline lists now (its eye filter applied), in its order."""
        ids = self.selection or self.timeline.listed()
        return [r for r in (self._row(i) for i in ids) if r is not None]

    def series(self, eye: str) -> list:
        """The eye's photo per exam from the current exam back (newest first)."""
        return review.eye_series(self.rows, eye, self.current)

    def stage_ok(self, stage: str) -> bool:
        return stage == "ou" or len(self.series(stage.upper())) >= 2

    def _sync_stages(self) -> None:
        model = self.c_stage.model()
        for i, (key, label) in enumerate(STAGES):
            ok = self.stage_ok(key)
            self.c_stage.setItemText(i, label if ok else label + NO_PRIOR)
            item = model.item(i)
            item.setEnabled(ok)

    def set_stage(self, stage: str) -> None:
        """The stage's pair on two cells — the state the tab opens in. Clears the selection."""
        if not self.stage_ok(stage):
            stage = "ou"
        self.stage, self.prior = stage, 0
        self.preset, self.selection, self._back, self.start = True, [], None, 0
        self.c_stage.setCurrentIndex(self.c_stage.findData(stage))
        self._apply_layout(2)
        self._fill(keep_view=False)          # a new stage starts with the whole photos

    def prior_count(self) -> int:
        if not self.preset or self.layout_n != 2 or self.stage == "ou":
            return 0
        return max(0, len(self.series(self.stage.upper())) - 1)

    def step_prior(self, d: int) -> None:
        """+1 = an earlier exam on the left cell, −1 = a later one (compare stages)."""
        n = self.prior_count()
        if not n:
            return
        k = max(0, min(n - 1, self.prior + d))
        if k != self.prior:
            self.prior = k
            self._fill(keep_view=True)

    def _fill(self, keep_view: bool) -> None:
        """Put the photos on the cells: the stage's pair, or a page of the pool."""
        if self.preset:
            if self.stage == "ou":
                for i, eye in enumerate(review.EYES):
                    s = self.series(eye)
                    row = s[0] if s else None
                    self.cells[i].empty_text = f"{EYE_NAMES[eye]} 사진이 없습니다"
                    tag = "이전" if row is not None and (row["exam_date"] or "") != (self.current or "") else ""
                    self._show(i, row, tag, keep_view)
            else:
                s = self.series(self.stage.upper())
                self.prior = max(0, min(len(s) - 2, self.prior))
                newest = s[0]
                for v in self.views:
                    v.empty_text = "사진 없음"
                self._show(0, s[1 + self.prior], "이전", keep_view)
                self._show(1, newest, "현재" if (newest["exam_date"] or "") == (self.current or "") else "이전",
                           keep_view)
        else:
            pool = self.pool()
            for i, v in enumerate(self.views):
                k = self.start + i
                v.empty_text = ""
                self._show(i, pool[k] if 0 <= k < len(pool) else None, "", keep_view)
            if self.views[self.active].row is None and self._cell_row(self.views[self.active]) is None:
                self.set_active(0)
        self._sync_ui()

    # -- reading the photos: whole for one or two cells, reduced (and in the background) for more ---------
    def _channel(self, rgb):
        if rgb is not None and self.view_mode != "color":
            return imaging.adjust(rgb, channel=next(ch for k, _, ch in VIEWS if k == self.view_mode))
        return rgb

    def _keep_small(self, key, rgb) -> None:
        if key in self._small:
            return
        self._small[key] = rgb
        self._small_bytes += rgb.nbytes
        while self._small_bytes > SMALL_BUDGET and len(self._small) > 1:
            _, old = self._small.popitem(last=False)
            self._small_bytes -= old.nbytes

    @staticmethod
    def _thumb_rgb(row):
        """The stored thumbnail as a stand-in while the reduced photo is read."""
        try:
            from PIL import Image

            with Image.open(row["thumb_path"]) as img:
                return np.asarray(img.convert("RGB"))
        except Exception:
            return None

    def _show(self, i: int, row, tag: str, keep_view: bool) -> None:
        cell = self.cells[i]
        cell.pending = None
        side = SIDES[self.layout_n]
        missing = False
        if row is None:
            rgb = None
        elif side == 0:
            rgb = self._load(row)
            missing = rgb is None
        else:
            key = (row["id"], side)
            rgb = self._small.get(key)
            if rgb is not None:
                self._small.move_to_end(key)
            else:
                path = self._path_of(row) if self._path_of is not None else None
                if self._path_of is None:                     # no files to read from: reduce the loaded photo
                    full = self._load(row)
                    rgb = imaging.downscale(full, side) if full is not None else None
                    missing = rgb is None
                    if rgb is not None:
                        self._keep_small(key, rgb)
                elif path is None:
                    missing = True
                else:                                         # the thumbnail now, the photo when it is read
                    rgb = self._thumb_rgb(row)
                    cell.pending = (key, row, tag)
                    self._reader.request(key, path)
        self._syncing = True                 # a photo coming in is not a move of the view
        try:
            cell.set_photo(row, self._channel(rgb), tag, keep_view=keep_view)
        finally:
            self._syncing = False
        if missing:
            cell.empty_text = "파일을 찾을 수 없습니다"

    def _on_reduced(self, key, rgb) -> None:
        self._reader.busy.discard(key)
        if rgb is not None:
            self._keep_small(key, rgb)
        for cell in self.views:
            if cell.pending is None or cell.pending[0] != key:
                continue
            _, row, tag = cell.pending
            cell.pending = None
            self._syncing = True
            try:
                cell.set_photo(row, self._channel(rgb), tag, keep_view=cell.has_image())
            finally:
                self._syncing = False
            if rgb is None:
                cell.empty_text = "파일을 찾을 수 없습니다"
        self._sync_ui()

    def loading(self) -> bool:
        """Reduced photos are still being read for cells on screen."""
        return any(v.pending is not None for v in self.views)

    @staticmethod
    def _cell_row(cell):
        return cell.row if cell.row is not None else (cell.pending[1] if cell.pending is not None else None)

    def slot_ids(self) -> list:
        """Image ids on the cells on screen (None: an empty cell)."""
        rows = [self._cell_row(v) for v in self.views]
        return [r["id"] if r is not None else None for r in rows]

    def _pool_index(self, image_id) -> int:
        return next((k for k, r in enumerate(self.pool()) if r["id"] == image_id), -1)

    def _first_index(self) -> int:
        """Pool index of the first photo on screen (0 when none of them is in the pool)."""
        for iid in self.slot_ids():
            k = self._pool_index(iid) if iid is not None else -1
            if k >= 0:
                return k
        return 0

    # -- selection: the photos picked in the timeline are the photos on screen ----------------------------
    def toggle_select(self, image_id: int) -> None:
        """A photo of the timeline was clicked: pick it / drop it. The cells show the picked photos,
        in as small a layout as holds them; with none left the stage's pair comes back."""
        if self._row(image_id) is None:
            return
        if image_id in self.selection:
            self.selection.remove(image_id)
        else:
            self.selection.append(image_id)
        if not self.selection:
            self.set_stage(self.stage)
            return
        self.preset, self._back = False, None
        n = layout_for(len(self.selection))
        k = self.selection.index(image_id) if image_id in self.selection else 0
        self.start = (k // n) * n if len(self.selection) > n else 0
        self._apply_layout(n)
        self._fill(keep_view=False)
        if image_id in self.selection:
            self.set_active(max(0, min(self.layout_n - 1, k - self.start)))

    def clear_selection(self) -> None:
        if self.selection:
            self.set_stage(self.stage)

    def set_layout(self, n: int) -> None:
        """The layout control: ``n`` cells, filled from the pool starting at the first photo on screen."""
        if n not in LAYOUTS or (n == self.layout_n and (self.preset or self._back is None)):
            self._apply_layout(self.layout_n)            # (the same layout: nothing changes)
            return
        self.start = self._first_index()
        self.preset, self._back = False, None
        self._apply_layout(n)
        self._fill(keep_view=False)

    def page(self, d: int) -> None:
        """◀ ▶ / ← →: the previous / next ``layout_n`` photos of the pool (one photo in the single layout)."""
        pool = self.pool()
        if not pool:
            return
        base = self._first_index() if self.preset else self.start
        if base < 0:                                      # a single photo that is not in the pool: to its start
            new = 0
        elif d > 0 and base + self.layout_n >= len(pool):
            return                                        # the last photos are on screen
        else:
            new = max(0, base + d * self.layout_n)
        if new == self.start and not self.preset:
            return
        self.preset, self.start = False, new
        self._fill(keep_view=False)

    def _double(self, i: int) -> None:
        """A double click: that photo alone; again: back to the layout it came from."""
        if self.layout_n == 1:
            if self._back is not None:
                self.close_single()
            return
        row = self._cell_row(self.views[i]) if i < self.layout_n else None
        if row is not None:
            self.open_single(i)

    def open_single(self, i: int) -> None:
        row = self._cell_row(self.views[i])
        if row is None:
            return
        self._back = {"preset": self.preset, "layout": self.layout_n, "start": self.start, "id": row["id"],
                      "active": i}
        self.preset = False
        self.start = self._pool_index(row["id"])          # −1: not in the pool (another eye than the filter's)
        self._apply_layout(1)
        self.cells[0].empty_text = ""
        self._show(0, row, "", keep_view=False)
        self.set_active(0)
        self._sync_ui()

    def close_single(self) -> None:
        back, self._back = self._back, None
        if back is None:
            return
        now = self.slot_ids()[0]
        if now == back["id"]:                             # nothing was walked: exactly as it was
            self.preset, self.start = back["preset"], back["start"]
            self._apply_layout(back["layout"])
            self._fill(keep_view=False)
            self.set_active(back["active"])
            return
        n = back["layout"]
        k = max(0, self._pool_index(now))
        self.preset, self.start = False, (k // n) * n     # the page that holds the photo last looked at
        self._apply_layout(n)
        self._fill(keep_view=False)
        self.set_active(k - self.start)

    def _on_eye(self, _eye: str) -> None:
        """The timeline lists another eye: the pool is another one — what is on screen stays until paged."""
        if not self.preset and not self.selection:
            first = self.slot_ids()[0]
            k = self._pool_index(first) if first is not None else -1
            self.start = k if k >= 0 or self.layout_n == 1 else self._first_index()
        self._sync_ui()

    def show_photo(self, image_id: int, index: int | None = None) -> None:
        """A photo of the timeline was dropped on cell ``index``: it goes there. In a selection it
        takes the place of that cell's photo."""
        row = self._row(image_id)
        if row is None:
            return
        index = self.active if index is None else index
        if self.selection:
            k = self.start + index
            if image_id in self.selection:
                self.selection.remove(image_id)
                k = min(k, len(self.selection))
            if k < len(self.selection):
                self.selection[k] = image_id
            else:
                self.selection.append(image_id)
            self._fill(keep_view=True)
            self.set_active(min(self.layout_n - 1, max(0, self.selection.index(image_id) - self.start)))
            return
        tag = ""
        if self.preset:
            if (row["exam_date"] or "") != (self.current or ""):
                tag = "이전" if not self.current or (row["exam_date"] or "") < self.current else ""
            elif self.stage != "ou":
                tag = "현재"
        self._show(index, row, tag, keep_view=True)
        if self.link:                         # the photo swapped in follows the other cells
            other = next((k for k, v in enumerate(self.views) if k != index and v.has_image()), None)
            if other is not None:
                self._view_moved(other)
        self.set_active(index)
        self._sync_ui()

    # -- the views ---------------------------------------------------------------------------------
    def set_active(self, i: int) -> None:
        self.active = max(0, min(self.layout_n - 1, i))
        for k, v in enumerate(self.cells):
            v.set_active(k == self.active)
        self._sync_buttons()

    def active_row(self):
        return self._cell_row(self.views[self.active])

    def _view_moved(self, i: int) -> None:
        if self._syncing or i >= self.layout_n:
            return
        if self.link and self.cells[i].has_image():
            self._syncing = True
            try:
                state = self.cells[i].view_state()
                for k, v in enumerate(self.views):
                    if k != i and v.has_image():
                        v.set_view_state(state)
            finally:
                self._syncing = False
        if self.lens.isVisible():
            self.lens.update()

    def set_link(self, on: bool) -> None:
        self.link = on
        if self.sw_link.isChecked() != on:
            self.sw_link.setChecked(on)
        if on:
            self._view_moved(self.active)

    def fit(self) -> None:
        lead = self.views[self.active]
        if self.link and lead.has_image():
            lead.fit(animate=True)                          # the other cells follow
            self._view_moved(self.active)
        else:
            for v in self.views:
                v.fit(animate=True)
        self.lens.update()

    def zoom_by(self, factor: float) -> None:
        v = self.views[self.active]
        if v.has_image():
            v.zoom_to(v.zoom * factor, animate=True)

    def set_view_mode(self, key: str) -> None:
        if key == self.view_mode or key not in [k for k, _, _ in VIEWS]:
            return
        self.view_mode = key
        if self.c_view.currentData() != key:
            self.c_view.setCurrentIndex(self.c_view.findData(key))
        for i, v in enumerate(self.views):
            row = self._cell_row(v)
            if row is not None:
                self._show(i, row, v.tag, keep_view=True)
        self.lens.update()

    # -- 확대창 --------------------------------------------------------------------------------------
    def set_lens(self, on: bool, centre: QPoint | None = None) -> None:
        """Show / hide the magnifier; ``centre`` (stage coordinates) = where, else over the active cell."""
        if on:
            if centre is None and not self.lens.isVisible():
                centre = _rect(self.views[self.active]).center()
            if centre is not None:
                self.lens.move_to(centre)
            self.lens.show()
            self.lens.raise_()
        else:
            self.lens.hide()
        if self.sw_lens.isChecked() != on:
            self.sw_lens.blockSignals(True)
            self.sw_lens.setChecked(on)
            self.sw_lens.blockSignals(False)

    def _middle(self, i: int, pos: QPoint) -> None:
        centre = self.cells[i].viewport().mapTo(self.stage_w, pos)
        self.set_lens(not self.lens.isVisible(), centre)

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.Resize:
            if obj is self.stage_w and self.lens.isVisible():
                self.lens.move_to(self.lens.geometry().center())
            elif obj is self.cells[0]:
                self._place_prior_nav()
        return super().eventFilter(obj, e)

    def _place_prior_nav(self) -> None:
        self.prior_nav.adjustSize()
        self.prior_nav.move(10, max(10, self.cells[0].height() - self.prior_nav.height() - 10))
        self.prior_nav.raise_()

    # -- hand-offs -----------------------------------------------------------------------------------
    def hand_off(self, where: str, index: int | None = None) -> None:
        i = self.active if index is None else index
        row = self._cell_row(self.views[i])
        if row is None:
            self.status.emit("사진이 없는 화면입니다 — 사진이 있는 화면을 누른 뒤 다시 누르세요")
            return
        second = None
        if where == "glaucoma" and self.preset and self.stage != "ou" and self.layout_n == 2:
            other = self._cell_row(self.views[1 - i])
            second = other["id"] if other is not None else None     # 이전 + 현재: the glaucoma window's 경과 비교
        self.handOff.emit(where, row["id"], second)

    def _menu(self, i: int, gpos: QPoint) -> None:
        if self._cell_row(self.cells[i]) is None:
            return
        menu = QMenu(self)
        menu.addAction("2D 보기로 열기", lambda: self.hand_off("2d", i))
        menu.addAction("3D 안구로 보기", lambda: self.hand_off("3d", i))
        menu.addAction("녹내장 분석…", lambda: self.hand_off("glaucoma", i))
        menu.addSeparator()
        if self.layout_n > 1:
            menu.addAction("이 사진만 보기", lambda: self.open_single(i))
        elif self._back is not None:
            menu.addAction("여러 장으로 돌아가기", self.close_single)
        menu.addAction("화면에 맞춤", self.fit)
        menu.addAction("확대창 끄기" if self.lens.isVisible() else "확대창 켜기",
                       lambda: self.set_lens(not self.lens.isVisible()))
        menu.exec(gpos)

    # -- keeping the controls in step ------------------------------------------------------------------
    def _sync_buttons(self) -> None:
        have = self.active_row() is not None
        for b in (self.btn_2d, self.btn_3d, self.btn_glaucoma):
            b.setEnabled(have)

    def position(self) -> str:
        """``3–4 / 12``: the photos on screen out of the pool (``2장 / 12`` for the stage's pair)."""
        total = len(self.pool())
        if self.preset:
            return f"{sum(i is not None for i in self.slot_ids())}장 / {total}"
        if self.start < 0 or not total:
            return f"– / {total}"
        last = min(self.start + self.layout_n, total)
        return f"{self.start + 1} / {total}" if last == self.start + 1 else f"{self.start + 1}–{last} / {total}"

    def _sync_ui(self) -> None:
        n = self.prior_count()
        self.prior_nav.setVisible(n > 0)
        if n:
            self.lbl_prior.setText(f"이전 검사 {self.prior + 1}/{n}")
            self.btn_older.setEnabled(self.prior < n - 1)
            self.btn_newer.setEnabled(self.prior > 0)
            self._place_prior_nav()
        total = len(self.pool())
        base = self._first_index() if self.preset else self.start
        self.btn_prev.setEnabled(total > 0 and (base > 0 or (self.start < 0 and not self.preset)))
        self.btn_next.setEnabled(total > 0 and (base + self.layout_n < total or base < 0))
        self.lbl_pos.setText(self.position())
        self.btn_clear.setVisible(bool(self.selection))
        self.bar_lay.invalidate()
        any_photo = any(v.has_image() for v in self.views)
        for b in (self.btn_fit, self.btn_out, self.btn_in):
            b.setEnabled(any_photo)
        self.timeline.mark_shown(i for i in self.slot_ids() if i is not None)
        self.timeline.mark_selected(self.selection)
        self._sync_buttons()
        if self.lens.isVisible():
            self.lens.update()
