"""검토 tab — both eyes side by side, and an eye next to its earlier exams.

Layout (top to bottom): a bar · two photo views · the timeline.

Stages (배치)
  양안      left = OD, right = OS: each eye's photo of the current exam (review.eye_photo); an eye
            not taken in that exam shows its newest earlier photo, tagged 이전.
  OD 비교   left = the eye's photo of an earlier exam (이전), right = the current exam (현재).
  OS 비교   ``[`` / ``]`` (or the small ◀ ▶ on the left view) step through the earlier exams.
            A compare stage needs an earlier exam of that eye.

The two views are ``ImageView``s (wheel = zoom at the cursor, drag = move, double click = fit);
연동 keeps their zoom and place together, as fractions of the photo, so photos of different
sizes stay on the same spot. 보기 shows one colour channel (감각망막 = green, 맥락막 = red).
The photos are shown as stored — the image-processing toolbar's adjustments belong to the 2D view.
The buttons at the end hand the active view's photo to the 2D view, the 3D eye or the glaucoma window.
"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QEvent, QMimeData, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QDrag, QFont, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractButton, QComboBox, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QSizePolicy,
    QToolButton, QVBoxLayout, QWidget,
)

from .. import imaging, review
from . import theme
from .image_view import ImageView
from .thumbs import eye_badge, paint_eye_badge, thumb_pixmap
from .widgets import FlowLayout, Switch, vline

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
    """One of the two photo views: which eye, when, 이전 / 현재 on the photo; a frame when active."""
    pressed = Signal()                   # any press here: this is the active view now
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
            badge = paint_eye_badge(p, self.row["laterality"], 10, 10, 13)
            x = badge.right() + 6
            chip = _chip(p, photo_caption(self.row), x, 9, theme.TEXT)
            if self.tag:
                _chip(p, self.tag, chip.right() + 6, 9, theme.YELLOW if self.tag == "이전" else theme.GREEN)
        elif self.empty_text:
            f = QFont(p.font())
            f.setPixelSize(14)
            p.setFont(f)
            p.setPen(QColor(theme.TEXT3))
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
    """확대창: a square that floats over the two views and shows what is under its centre, larger.

    Drag = move · wheel = 1.5× – 6× · right click (or double click) = show the *other* view's
    photo at the same place · middle click = close."""
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
        shown = self.views[1 - i] if self.other else host
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
                + (" · 반대쪽" if self.other else ""))

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
        self.other = not self.other
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
        p.setPen(QPen(QColor(theme.ORANGE if self.other else theme.ACCENT), 2))
        p.drawRoundedRect(full.adjusted(1, 1, -1, -1), 6, 6)
        p.end()


class _TimelineThumb(QAbstractButton):
    """A photo of the timeline: thumbnail, eye badge, a frame while it is on one of the views.
    Click = show it; drag = drop it on a view."""
    SIDE = 76

    def __init__(self, row, parent=None):
        super().__init__(parent)
        self.image_id = row["id"]
        self.eye = row["laterality"] or ""
        self.shown = False
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
        if self.shown:
            p.setPen(QPen(QColor(theme.ACCENT), 2))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 7, 7)
        else:
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
        self.lbl_hint = QLabel("사진을 누르거나 화면으로 끌어다 놓으면 그 자리에 뜹니다 · 날짜를 누르면 그 검사가 현재 검사")
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
        while self.body_lay.count():
            item = self.body_lay.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.thumbs, self.dates = [], []
        n = 0
        for i, (d, rows) in enumerate(groups):
            day = QWidget()
            v = QVBoxLayout(day)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(3)
            marks = [m for m, on in (("현재", d == current), ("최근", i == 0 and d != current)) if on]
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
        self.lbl_count.setText(f"검사 {len(groups)}회 · {n}장" if n else "사진 없음")

    def mark_shown(self, ids) -> None:
        ids = set(ids)
        for t in self.thumbs:
            t.set_shown(t.image_id in ids)


class ReviewPage(QWidget):
    handOff = Signal(str, int, object)   # "2d" / "3d" / "glaucoma", image id, second image id (or None)
    examPicked = Signal(str)             # a date of the timeline was clicked
    status = Signal(str)

    def __init__(self, load, parent=None):
        """``load(row)`` returns the photo of an images row as an RGB array (None: unreadable)."""
        super().__init__(parent)
        self.setObjectName("reviewPage")
        self._load = load
        self.rows: list = []             # the patient's photographs (sheets left out)
        self.current: str | None = None  # exam under review
        self.stage = "ou"
        self.prior = 0                   # which earlier exam the compare stage shows (0 = the latest)
        self.active = 0
        self.link = True
        self.view_mode = "color"
        self._syncing = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # -- the bar (wraps onto a second line in a narrow window) --------------------------------
        bar = QWidget()
        bar.setObjectName("barReview")
        self.bar_lay = FlowLayout(bar)
        add = self.bar_lay.addWidget
        self.btn_prev = QPushButton("◀ 이전")
        self.btn_prev.setToolTip("이전 배치 (←)")
        self.btn_prev.clicked.connect(lambda: self.step_stage(-1))
        self.c_stage = QComboBox()
        self.c_stage.setToolTip("배치 — * 비교는 그 눈의 이전 검사가 있을 때 쓸 수 있습니다\n"
                                "([ / ] 로 더 이전 · 더 최근 검사)")
        for key, label in STAGES:
            self.c_stage.addItem(label, key)
        fm = self.c_stage.fontMetrics()         # as wide as a stage's name; the list as its longest line
        self.c_stage.setFixedWidth(max(fm.horizontalAdvance(label) for _, label in STAGES) + 60)
        self.c_stage.view().setMinimumWidth(max(fm.horizontalAdvance(label + NO_PRIOR) for _, label in STAGES) + 44)
        self.c_stage.activated.connect(lambda i: self.set_stage(self.c_stage.itemData(i)))
        self.btn_next = QPushButton("다음 ▶")
        self.btn_next.setToolTip("다음 배치 (→)")
        self.btn_next.clicked.connect(lambda: self.step_stage(1))
        for w in (self.btn_prev, self.c_stage, self.btn_next, vline()):
            add(w)
        self.btn_fit = QPushButton("맞춤")
        self.btn_fit.setToolTip("사진 전체가 보이게 (더블클릭)")
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
        self.sw_link.setToolTip("두 화면의 확대·이동을 함께 움직입니다")
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

        # -- the two views -------------------------------------------------------------------------
        self.stage_w = QWidget()
        self.stage_w.setObjectName("reviewStage")
        sl = QHBoxLayout(self.stage_w)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(3)
        self.views = (ReviewViewport(), ReviewViewport())
        for i, v in enumerate(self.views):
            v.setMinimumSize(120, 70)
            sl.addWidget(v, 1)
            v.pressed.connect(lambda i=i: self.set_active(i))
            v.middleClicked.connect(lambda pos, i=i: self._middle(i, pos))
            v.dropped.connect(lambda iid, i=i: self.show_photo(iid, i))
            v.menuRequested.connect(lambda gpos, i=i: self._menu(i, gpos))
            v.zoomChanged.connect(lambda _, i=i: self._view_moved(i))
            v.horizontalScrollBar().valueChanged.connect(lambda _, i=i: self._view_moved(i))
            v.verticalScrollBar().valueChanged.connect(lambda _, i=i: self._view_moved(i))
        self.views[0].set_active(True)
        lay.addWidget(self.stage_w, 1)
        # ◀ 이전 검사 k/n ▶ on the left view (compare stages)
        self.prior_nav = QWidget(self.views[0])
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
        self.views[0].installEventFilter(self)
        self.lens = Magnifier(self.stage_w, self.views)
        self.lens.closed.connect(lambda: self.set_lens(False))
        self.stage_w.installEventFilter(self)

        # -- the timeline ----------------------------------------------------------------------------
        self.timeline = Timeline()
        self.timeline.photoClicked.connect(self.show_photo)
        self.timeline.examClicked.connect(self.examPicked.emit)
        lay.addWidget(self.timeline)

        for seq, fn in (("Left", lambda: self.step_stage(-1)), ("Right", lambda: self.step_stage(1)),
                        ("[", lambda: self.step_prior(1)), ("]", lambda: self.step_prior(-1))):
            sc = QShortcut(QKeySequence(seq), self, context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
        self._sync_ui()

    # -- photos ------------------------------------------------------------------------------------
    def set_photos(self, rows, current: str | None = None) -> None:
        """The patient's ``rows`` (images, any order) and the exam under review (None = the newest).
        The stage is kept when it is still possible; the views show the default photos again."""
        self.rows = [r for r in rows if review.is_photo(r)]
        dates = review.exam_dates(self.rows)
        self.current = current if current in dates else (dates[0] if dates else None)
        self.timeline.set_exams(review.exams(self.rows), self.current)
        self._sync_stages()
        self.set_stage(self.stage if self.stage_ok(self.stage) else "ou")

    def set_current_exam(self, exam_date: str) -> None:
        if exam_date != self.current:
            self.set_photos(self.rows, exam_date)

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
        if not self.stage_ok(stage):
            stage = "ou"
        self.stage, self.prior = stage, 0
        self.c_stage.setCurrentIndex(self.c_stage.findData(stage))
        self._fill(keep_view=False)          # a new stage starts with the whole photos

    def step_stage(self, d: int) -> None:
        ok = [k for k, _ in STAGES if self.stage_ok(k)]
        self.set_stage(ok[(ok.index(self.stage) + d) % len(ok)])

    def prior_count(self) -> int:
        return 0 if self.stage == "ou" else max(0, len(self.series(self.stage.upper())) - 1)

    def step_prior(self, d: int) -> None:
        """+1 = an earlier exam on the left view, −1 = a later one (compare stages)."""
        n = self.prior_count()
        if not n:
            return
        k = max(0, min(n - 1, self.prior + d))
        if k != self.prior:
            self.prior = k
            self._fill(keep_view=True)

    def _fill(self, keep_view: bool) -> None:
        """Put the stage's photos on the two views."""
        if self.stage == "ou":
            for i, eye in enumerate(review.EYES):
                s = self.series(eye)
                row = s[0] if s else None
                self.views[i].empty_text = f"{EYE_NAMES[eye]} 사진이 없습니다"
                tag = "이전" if row is not None and (row["exam_date"] or "") != (self.current or "") else ""
                self._show(i, row, tag, keep_view)
        else:
            s = self.series(self.stage.upper())
            self.prior = max(0, min(len(s) - 2, self.prior))
            newest = s[0]
            for v in self.views:
                v.empty_text = "사진 없음"
            self._show(0, s[1 + self.prior], "이전", keep_view)
            self._show(1, newest, "현재" if (newest["exam_date"] or "") == (self.current or "") else "이전", keep_view)
        self._sync_ui()

    def _show(self, i: int, row, tag: str, keep_view: bool) -> None:
        rgb = self._load(row) if row is not None else None
        if rgb is not None and self.view_mode != "color":
            rgb = imaging.adjust(rgb, channel=next(ch for k, _, ch in VIEWS if k == self.view_mode))
        self._syncing = True                 # a photo coming in is not a move of the view
        try:
            self.views[i].set_photo(row, rgb, tag, keep_view=keep_view)
        finally:
            self._syncing = False
        if row is not None and rgb is None:
            self.views[i].empty_text = "파일을 찾을 수 없습니다"

    def slot_ids(self) -> list:
        return [v.row["id"] if v.row is not None else None for v in self.views]

    def show_photo(self, image_id: int, index: int | None = None) -> None:
        """A photo of the timeline was clicked (``index`` None) or dropped on view ``index``:
        양안 puts a clicked photo on the view of its eye, everything else on the active view."""
        row = next((r for r in self.rows if r["id"] == image_id), None)
        if row is None:
            return
        if index is None:
            eye = row["laterality"]
            index = review.EYES.index(eye) if self.stage == "ou" and eye in review.EYES else self.active
        tag = ""
        if (row["exam_date"] or "") != (self.current or ""):
            tag = "이전" if not self.current or (row["exam_date"] or "") < self.current else ""
        elif self.stage != "ou":
            tag = "현재"
        self._show(index, row, tag, keep_view=True)
        if self.link:                         # the photo swapped in follows the other view
            self._view_moved(1 - index)
        self.set_active(index)
        self._sync_ui()

    # -- the views ---------------------------------------------------------------------------------
    def set_active(self, i: int) -> None:
        self.active = i
        for k, v in enumerate(self.views):
            v.set_active(k == i)
        self._sync_buttons()

    def active_row(self):
        return self.views[self.active].row

    def _view_moved(self, i: int) -> None:
        if self._syncing:
            return
        if self.link and self.views[i].has_image() and self.views[1 - i].has_image():
            self._syncing = True
            try:
                self.views[1 - i].set_view_state(self.views[i].view_state())
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
        if self.link and all(v.has_image() for v in self.views):
            self.views[self.active].fit(animate=True)       # the other view follows
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
            if v.row is not None:
                self._show(i, v.row, v.tag, keep_view=True)
        self.lens.update()

    # -- 확대창 --------------------------------------------------------------------------------------
    def set_lens(self, on: bool, centre: QPoint | None = None) -> None:
        """Show / hide the magnifier; ``centre`` (stage coordinates) = where, else over the active view."""
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
        centre = self.views[i].viewport().mapTo(self.stage_w, pos)
        self.set_lens(not self.lens.isVisible(), centre)

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.Resize:
            if obj is self.stage_w and self.lens.isVisible():
                self.lens.move_to(self.lens.geometry().center())
            elif obj is self.views[0]:
                self._place_prior_nav()
        return super().eventFilter(obj, e)

    def _place_prior_nav(self) -> None:
        self.prior_nav.adjustSize()
        self.prior_nav.move(10, max(10, self.views[0].height() - self.prior_nav.height() - 10))
        self.prior_nav.raise_()

    # -- hand-offs -----------------------------------------------------------------------------------
    def hand_off(self, where: str, index: int | None = None) -> None:
        i = self.active if index is None else index
        row = self.views[i].row
        if row is None:
            self.status.emit("사진이 없는 화면입니다 — 사진이 있는 화면을 누른 뒤 다시 누르세요")
            return
        second = None
        if where == "glaucoma" and self.stage != "ou" and self.views[1 - i].row is not None:
            second = self.views[1 - i].row["id"]     # 이전 + 현재: the glaucoma window's 경과 비교
        self.handOff.emit(where, row["id"], second)

    def _menu(self, i: int, gpos: QPoint) -> None:
        if self.views[i].row is None:
            return
        menu = QMenu(self)
        menu.addAction("2D 보기로 열기", lambda: self.hand_off("2d", i))
        menu.addAction("3D 안구로 보기", lambda: self.hand_off("3d", i))
        menu.addAction("녹내장 분석…", lambda: self.hand_off("glaucoma", i))
        menu.addSeparator()
        menu.addAction("화면에 맞춤", self.fit)
        menu.addAction("확대창 끄기" if self.lens.isVisible() else "확대창 켜기",
                       lambda: self.set_lens(not self.lens.isVisible()))
        menu.exec(gpos)

    # -- keeping the controls in step ------------------------------------------------------------------
    def _sync_buttons(self) -> None:
        have = self.active_row() is not None
        for b in (self.btn_2d, self.btn_3d, self.btn_glaucoma):
            b.setEnabled(have)

    def _sync_ui(self) -> None:
        n = self.prior_count()
        self.prior_nav.setVisible(n > 0)
        if n:
            self.lbl_prior.setText(f"이전 검사 {self.prior + 1}/{n}")
            self.btn_older.setEnabled(self.prior < n - 1)
            self.btn_newer.setEnabled(self.prior > 0)
            self._place_prior_nav()
        many = sum(self.stage_ok(k) for k, _ in STAGES) > 1
        self.btn_prev.setEnabled(many)
        self.btn_next.setEnabled(many)
        any_photo = any(v.row is not None for v in self.views)
        for b in (self.btn_fit, self.btn_out, self.btn_in):
            b.setEnabled(any_photo)
        self.timeline.mark_shown(i for i in self.slot_ids() if i is not None)
        self._sync_buttons()
        if self.lens.isVisible():
            self.lens.update()
