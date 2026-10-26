"""생년월일 입력 칸 — 숫자만 쳐도 되고(19800315 · 800315 · 1980.3.15), 달력에서 고를 수도 있다.

입력이 끝나면(포커스 이동·Enter) 'YYYY-MM-DD' 로 정리한다. 6자리(YYMMDD)는 주민번호 앞자리처럼
해석해 세기를 추정한다(올해 두 자리보다 크면 19xx). 알아볼 수 없는 값은 붉게 표시하고 그대로 둔다.
"""
from __future__ import annotations

import re
from datetime import date

from PySide6.QtCore import QDate, QLocale, QPoint, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCalendarWidget,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui import icons
from app.ui.theme import ICON


def normalize_date(text: str, today: date | None = None) -> str | None:
    """사람이 친 생년월일을 'YYYY-MM-DD' 로. 빈 값은 '', 해석 불가는 None."""
    t = (text or "").strip()
    if not t:
        return ""
    today = today or date.today()
    digits = re.sub(r"\D", "", t)
    parts = [p for p in re.split(r"[^\d]+", t) if p]
    y = m = d = None
    if len(parts) == 3 and len(parts[0]) in (2, 4):           # 1980-3-15 · 80.3.15
        y, m, d = (int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts[0]) == 2:
            y = _century(y, today)
    elif len(digits) == 8:                                     # 19800315
        y, m, d = int(digits[:4]), int(digits[4:6]), int(digits[6:8])
    elif len(digits) == 6:                                     # 800315
        y, m, d = _century(int(digits[:2]), today), int(digits[2:4]), int(digits[4:6])
    else:
        return None
    try:
        v = date(y, m, d)
    except ValueError:
        return None
    if v > today or v.year < 1880:
        return None
    return v.isoformat()


def _century(yy: int, today: date) -> int:
    return 1900 + yy if yy > today.year % 100 else 2000 + yy


class DateField(QWidget):
    """QLineEdit + 달력 버튼. value() 는 'YYYY-MM-DD' 또는 ''(비움). is_valid() 로 검사."""

    changed = Signal(str)

    def __init__(self, value: str = "", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("예) 19800315 · 800315 · 1980-03-15")
        self.edit.setClearButtonEnabled(True)
        self.edit.setMaxLength(12)
        self.btn = QPushButton()
        self.btn.setObjectName("DateBtn")
        self.btn.setIcon(icons.icon("calendar", ICON, 18))
        self.btn.setIconSize(QSize(18, 18))
        self.btn.setToolTip("달력에서 선택")
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.btn)
        self._popup: _CalendarPopup | None = None
        self._valid = True
        self.edit.editingFinished.connect(self.normalize)
        self.edit.textChanged.connect(self._on_text_changed)
        self.btn.clicked.connect(lambda: self.open_calendar())
        self.set_value(value)

    # ---- 값 ----
    def value(self) -> str:
        v = normalize_date(self.edit.text())
        return v or ""

    def set_value(self, text: str | None) -> None:
        self.edit.setText(text or "")
        self.normalize()

    def is_valid(self) -> bool:
        return normalize_date(self.edit.text()) is not None

    def normalize(self) -> None:
        v = normalize_date(self.edit.text())
        if v is not None and v != self.edit.text():
            self.edit.setText(v)
        self._mark(v is not None)

    def _on_text_changed(self, _t: str) -> None:
        if not self._valid:                      # 고치는 중에는 붉은 표시를 지운다
            self._mark(True)
        self.changed.emit(self.edit.text())

    def _mark(self, ok: bool) -> None:
        self._valid = ok
        self.edit.setProperty("invalid", not ok)
        self.edit.setToolTip("" if ok else "생년월일을 알아볼 수 없습니다 (예: 19800315)")
        self.edit.style().unpolish(self.edit)
        self.edit.style().polish(self.edit)

    # ---- 달력 ----
    def open_calendar(self) -> None:
        if self._popup is None:
            self._popup = _CalendarPopup(self)
            self._popup.picked.connect(self._on_picked)
        v = normalize_date(self.edit.text())
        qd = QDate.fromString(v, "yyyy-MM-dd") if v else QDate.currentDate()
        self._popup.show_at(self.mapToGlobal(QPoint(0, self.height() + 4)), qd if qd.isValid() else QDate.currentDate())

    def _on_picked(self, qd: QDate) -> None:
        self.edit.setText(qd.toString("yyyy-MM-dd"))
        self._mark(True)
        self.edit.setFocus()


class _CalendarPopup(QFrame):
    picked = Signal(QDate)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("DatePopup")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self.cal = QCalendarWidget()
        self.cal.setLocale(QLocale(QLocale.Language.Korean, QLocale.Country.SouthKorea))   # 1950년 6월 · 일월화…
        self.cal.setGridVisible(False)
        self.cal.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.cal.setHorizontalHeaderFormat(QCalendarWidget.HorizontalHeaderFormat.SingleLetterDayNames)
        self.cal.setMinimumDate(QDate(1880, 1, 1))
        self.cal.setMaximumDate(QDate.currentDate())
        self.cal.setFirstDayOfWeek(Qt.DayOfWeek.Sunday)
        self.cal.clicked.connect(self._pick)
        self.cal.activated.connect(self._pick)
        lay.addWidget(self.cal)

    def show_at(self, pos: QPoint, qd: QDate) -> None:
        self.cal.setSelectedDate(qd)
        self.cal.setCurrentPage(qd.year(), qd.month())
        self.adjustSize()
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen is not None:
            pos.setX(min(pos.x(), screen.right() - self.width() - 4))
            pos.setY(min(pos.y(), screen.bottom() - self.height() - 4))
        self.move(pos)
        self.show()
        self.cal.setFocus()

    def _pick(self, qd: QDate) -> None:
        self.picked.emit(qd)
        self.hide()
