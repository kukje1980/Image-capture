"""Thumbnail strip painting: the eye (OD / OS) on every photo and the multi-view picks.

VK-2 lists the photos newest first and shows which eye each one is. Here every thumbnail gets
a coloured eye badge in its top-left corner (OD blue · OS orange · OU purple · 미상 grey), and
the photos picked for the multi view (plain click) get a yellow frame with their pick number.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

EYE_ROLE = Qt.ItemDataRole.UserRole + 2     # laterality of the photo ("OD" / "OS" / "OU" / "")
PICK_ROLE = Qt.ItemDataRole.UserRole + 3    # pick order for the multi view (0 = not picked)

PICK_COLOR = "#facc15"
_EYES = {"OD": ("OD", "#5aa9ff", "#04192f"), "OS": ("OS", "#f5a524", "#2a1700"),
         "OU": ("OU", "#b18cff", "#1b0f3a")}


def eye_badge(laterality: str | None) -> tuple[str, str, str]:
    """(text, background, text colour) of the eye badge; unknown eye = grey 미상."""
    return _EYES.get(laterality or "", ("미상", "#4b5563", "#e5e7eb"))


def eye_badge_html(laterality: str | None) -> str:
    text, bg, fg = eye_badge(laterality)
    return f"<span style='background:{bg}; color:{fg}; font-weight:700'>&nbsp;{text}&nbsp;</span>"


class ThumbDelegate(QStyledItemDelegate):
    """Default icon + caption, then the eye badge and the pick frame / number on the photo."""

    def paint(self, painter: QPainter, option, index) -> None:
        super().paint(painter, option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        deco = style.subElementRect(QStyle.SubElement.SE_ItemViewItemDecoration, opt, opt.widget)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        size = icon.actualSize(deco.size()) if isinstance(icon, QIcon) and not icon.isNull() else QSize()
        if size.isEmpty():
            photo = QRect(deco)
        else:                                  # the photo itself, centred in the icon cell
            photo = QRect(0, 0, size.width(), size.height())
            photo.moveCenter(deco.center())
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        f = QFont(opt.font)
        f.setBold(True)
        f.setPixelSize(13)
        painter.setFont(f)
        fm = painter.fontMetrics()
        text, bg, fg = eye_badge(index.data(EYE_ROLE))
        badge = QRectF(photo.left() + 3, photo.top() + 3, fm.horizontalAdvance(text) + 12, fm.height() + 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(badge, 4, 4)
        painter.setPen(QColor(fg))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
        rank = int(index.data(PICK_ROLE) or 0)
        if rank:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(PICK_COLOR), 3))
            painter.drawRect(QRectF(photo).adjusted(1.5, 1.5, -1.5, -1.5))
            d = fm.height() + 6
            dot = QRectF(photo.right() - d - 2, photo.top() + 3, d, d)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(PICK_COLOR))
            painter.drawEllipse(dot)
            painter.setPen(QColor("#111827"))
            painter.drawText(dot, Qt.AlignmentFlag.AlignCenter, str(rank))
        painter.restore()
