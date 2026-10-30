"""질환별 참고 사진 패널 — 환자 배너 바로 아래에 작은 사진들(모식도 + 병원 등록 사진)을 한 줄로 보여 준다.

사진을 누르면 referenceChosen(질환 id, 항목) 이 나가고 메인 창이 비교 창(DxCompareDialog)을 연다.
항목 dict: {kind: 'ill'|'user', path, caption, ref?: ReferenceImage}
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app import dx_library
from app.ui import icons
from app.ui.dx_images import load_pixmap
from app.ui.theme import ICON, ICON_ACCENT, ICON_ON_ACCENT
from app.ui.video_view import scaled_font


class DxCard(QWidget):
    """작은 참고 사진 카드 (사진을 칸에 꽉 채워 자르고, 배지·캡션·삭제 버튼 오버레이)."""
    clicked = Signal(dict)
    deleteRequested = Signal(dict)

    def __init__(self, item: dict, size: QSize = QSize(152, 100), selected: bool = False,
                 deletable: bool = True, parent=None):
        super().__init__(parent)
        self.item = item
        self._pm = load_pixmap(item["path"], 600)
        self._hover = False
        self._selected = selected
        self._deletable = deletable and item.get("kind") == "user"
        self.setFixedSize(size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(item.get("caption", "") + "\n(누르면 촬영 사진과 비교)")
        self.setMouseTracking(True)

    def set_selected(self, on: bool) -> None:
        self._selected = on
        self.update()

    def _del_rect(self) -> QRectF:
        return QRectF(self.width() - 26, 4, 22, 22)

    def enterEvent(self, e) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if self._deletable and self._del_rect().contains(e.position()):
            self.deleteRequested.emit(self.item)
        else:
            self.clicked.emit(self.item)

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QPainterPath()
        clip.addRoundedRect(r, 8, 8)
        p.setClipPath(clip)
        p.fillRect(r, QColor("#000000"))
        if self._pm is not None:
            s = self._pm.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap((self.width() - s.width()) // 2, (self.height() - s.height()) // 2, s)
        else:
            p.drawPixmap(self.width() // 2 - 12, self.height() // 2 - 12, icons.pixmap("image", "#6b7586", 24))
        small = self.height() < 90
        # 캡션
        gh = 30 if small else 40
        g = QLinearGradient(0, self.height() - gh, 0, self.height())
        g.setColorAt(0, QColor(0, 0, 0, 0))
        g.setColorAt(1, QColor(0, 0, 0, 220))
        p.fillRect(QRectF(0, self.height() - gh, self.width(), gh), g)
        p.setFont(scaled_font(self.font(), 0.78 if small else 0.85))
        p.setPen(QColor("#e7eaf0"))
        cap = p.fontMetrics().elidedText(self.item.get("caption", ""), Qt.TextElideMode.ElideRight, self.width() - 12)
        p.drawText(QRectF(6, self.height() - 19, self.width() - 12, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, cap)
        # 배지
        if not small:
            user = self.item.get("kind") == "user"
            text, col = ("참고 사진", "#9fe8dd") if user else ("모식도", "#e7eaf0")
            p.setFont(scaled_font(self.font(), 0.75, True))
            w = p.fontMetrics().horizontalAdvance(text) + 12
            br = QRectF(6, 6, w, 18)
            p.setPen(QPen(QColor(col if user else QColor(255, 255, 255, 40)), 1))
            p.setBrush(QColor(8, 11, 16, 190))
            p.drawRoundedRect(br, 5, 5)
            p.setPen(QColor(col))
            p.drawText(br, Qt.AlignmentFlag.AlignCenter, text)
        # 삭제 버튼 (등록 사진, 마우스 올렸을 때)
        if self._deletable and self._hover:
            dr = self._del_rect()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(8, 11, 16, 200))
            p.drawRoundedRect(dr, 6, 6)
            p.drawPixmap(int(dr.x() + 4), int(dr.y() + 4), icons.pixmap("trash", "#ffb4b4", 14))
        p.setClipping(False)
        p.setBrush(Qt.BrushStyle.NoBrush)
        on = self._hover or self._selected
        p.setPen(QPen(QColor("#33c2b1"), 2) if on else QPen(QColor(255, 255, 255, 22), 1))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)


class AddCard(QPushButton):
    def __init__(self, parent=None):
        super().__init__(icons.gap("참고 사진 추가"), parent)
        self.setObjectName("DxAddCard")
        self.setIcon(icons.icon("plus", ICON, 18))
        self.setIconSize(QSize(18, 18))
        self.setFixedSize(152, 100)
        self.setToolTip("파일에서 이 질환의 참고 사진 등록 (병원 자체 사례 사진)")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class DxPanel(QFrame):
    referenceChosen = Signal(str, dict)       # (질환 id, 항목)
    addRequested = Signal(str)
    deleteRequested = Signal(str, dict)
    compareRequested = Signal(str)
    closed = Signal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.disease: str | None = None
        self.setObjectName("DxPanel")
        self.hide()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 8, 16, 10)
        outer.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(10)
        self.icon = QLabel()
        self.icon.setObjectName("DxPanelIcon")
        self.icon.setFixedSize(34, 34)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(self.icon)
        box = QVBoxLayout()
        box.setSpacing(0)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.lbl_name = QLabel()
        self.lbl_name.setObjectName("DxName")
        self.lbl_en = QLabel()
        self.lbl_en.setObjectName("Muted")
        row.addWidget(self.lbl_name)
        row.addWidget(self.lbl_en)
        row.addStretch(1)
        self.lbl_sum = QLabel()
        self.lbl_sum.setObjectName("Muted")
        box.addLayout(row)
        box.addWidget(self.lbl_sum)
        head.addLayout(box, 1)
        self.lbl_hint = QLabel("사진을 누르면 촬영 사진과 나란히 비교합니다")
        self.lbl_hint.setObjectName("Muted")
        head.addWidget(self.lbl_hint)
        self.btn_add = QPushButton(icons.gap("참고 사진 추가"))
        self.btn_add.setIcon(icons.icon("plus", ICON, 15))
        self.btn_add.setToolTip("파일에서 이 질환의 참고 사진 등록 (병원 자체 사례 사진)")
        self.btn_compare = QPushButton(icons.gap("촬영 사진과 비교"))
        self.btn_compare.setObjectName("Primary")
        self.btn_compare.setIcon(icons.icon("compare", ICON_ON_ACCENT, 15))
        self.btn_compare.setToolTip("첫 참고 사진으로 바로 비교")
        self.btn_close = QPushButton()
        self.btn_close.setObjectName("IconBtn")
        self.btn_close.setIcon(icons.icon("x", ICON, 16))
        self.btn_close.setToolTip("패널 닫기")
        for b in (self.btn_add, self.btn_compare, self.btn_close):
            b.setIconSize(QSize(15, 15))
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            head.addWidget(b)
        outer.addLayout(head)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("DxStrip")
        self._scroll.setWidgetResizable(True)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFixedHeight(116)
        self._strip = QWidget()
        self._strip.setObjectName("DxStripInner")
        self._lay = QHBoxLayout(self._strip)
        self._lay.setContentsMargins(0, 0, 0, 6)
        self._lay.setSpacing(10)
        self._lay.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._scroll.setWidget(self._strip)
        outer.addWidget(self._scroll)

        self.btn_add.clicked.connect(lambda: self.addRequested.emit(self.disease or ""))
        self.btn_compare.clicked.connect(lambda: self.compareRequested.emit(self.disease or ""))
        self.btn_close.clicked.connect(self.close_panel)

    # ---- 공개 API ----
    def show_disease(self, disease_id: str) -> None:
        d = dx_library.get(disease_id)
        if d is None:
            return
        self.disease = disease_id
        self.icon.setPixmap(icons.pixmap(d["icon"], ICON_ACCENT, 20))
        self.lbl_name.setText(d["name"])
        self.lbl_en.setText(d["en"])
        self.lbl_sum.setText(d["summary"])
        self.refresh()
        self.show()

    def close_panel(self) -> None:
        self.hide()
        self.closed.emit()

    def items(self) -> list[dict]:
        return self.store.items(self.disease) if self.disease else []

    def refresh(self) -> None:
        while self._lay.count():
            w = self._lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for it in self.items():
            c = DxCard(it)
            c.clicked.connect(lambda item, did=self.disease: self.referenceChosen.emit(did, item))
            c.deleteRequested.connect(lambda item, did=self.disease: self.deleteRequested.emit(did, item))
            self._lay.addWidget(c)
        add = AddCard()
        add.clicked.connect(lambda: self.addRequested.emit(self.disease or ""))
        self._lay.addWidget(add)
        self._lay.addStretch(1)

    def card_count(self) -> int:
        return sum(1 for i in range(self._lay.count())
                   if isinstance(self._lay.itemAt(i).widget(), DxCard))
