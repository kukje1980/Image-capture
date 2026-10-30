"""참고 사진 ↔ 환자 촬영 사진 비교 창 (환자 설명용).

왼쪽: 질환 참고 사진(모식도 또는 병원 등록 사진), 오른쪽: 환자 촬영 사진(또는 지금 실시간 화면),
오른쪽 옆: 세극등 소견 · 환자 설명 · 비교 포인트. 사진을 누르면 그 자리를 확대, 다시 누르면 원래대로.
버튼: 참고 사진으로 등록(환자 사진 → 질환 참고) · 인쇄/PDF · 비교 이미지 저장(두 장을 나란히 합쳐 환자 기록에) · 닫기
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app import brand as app_brand
from app import dx_library
from app.capture.frame_utils import bgr_to_qimage
from app.ui import icons
from app.ui.dx_images import load_bgr, load_pixmap, qimage_to_bgr
from app.ui.dx_panel import DxCard
from app.ui.pro import print_util
from app.ui.theme import ICON, ICON_ACCENT, ICON_ON_ACCENT

log = logging.getLogger(__name__)
_EYE_KO = {"OD": "OD", "OS": "OS", "OU": "OU"}


def _esc(v) -> str:
    return str(v or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def capture_caption(c) -> str:
    eye = _EYE_KO.get(c.eye or "", "")
    return " · ".join(x for x in (c.captured_at or "", eye, c.note or "") if x)


class ImageBox(QWidget):
    """검은 바탕에 비율 유지로 사진을 보여 주고, 누른 자리를 2.4배 확대한다."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pm: QPixmap | None = None
        self._zoom_at: QPointF | None = None
        self.setMinimumSize(240, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._empty = "사진을 고르세요"

    def set_pixmap(self, pm: QPixmap | None, empty: str = "") -> None:
        self._pm = pm
        self._zoom_at = None
        if empty:
            self._empty = empty
        self.update()

    def _fit(self) -> tuple[float, QRectF]:
        w, h = self._pm.width(), self._pm.height()
        s = min(self.width() / w, self.height() / h)
        dw, dh = w * s, h * s
        return s, QRectF((self.width() - dw) / 2, (self.height() - dh) / 2, dw, dh)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if self._pm is None:
            return
        self._zoom_at = None if self._zoom_at is not None else e.position()
        self.setCursor(Qt.CursorShape.CrossCursor if self._zoom_at is None else Qt.CursorShape.SizeAllCursor)
        self.update()

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.fillRect(self.rect(), QColor("#000000"))
        if self._pm is None:
            p.setPen(QColor("#6b7586"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._empty)
            return
        s, target = self._fit()
        if self._zoom_at is not None:
            z = 2.4
            # 누른 자리가 그대로 보이도록 그 점을 기준으로 확대
            ax, ay = self._zoom_at.x(), self._zoom_at.y()
            target = QRectF(ax - (ax - target.x()) * z, ay - (ay - target.y()) * z, target.width() * z, target.height() * z)
        p.drawPixmap(target, self._pm, QRectF(self._pm.rect()))


class DxCompareDialog(QDialog):
    savedCapture = Signal()
    referencesChanged = Signal()

    def __init__(self, store, service, config, disease_id: str, ref_item: dict | None, patient, captures: list,
                 live_frame: np.ndarray | None = None, parent=None):
        super().__init__(parent)
        self.store = store
        self.service = service
        self.config = config
        self.disease = dx_library.get(disease_id) or {"id": disease_id, "name": disease_id, "en": "", "icon": "eye"}
        self.patient = patient
        self.live_frame = live_frame
        self.captures = [c for c in captures if c.media_type == "photo"]
        self.ref: dict | None = ref_item
        self.pt: dict | None = None            # {kind:'capture'|'live', path?, frame?, caption, eye}
        self.setWindowTitle(f"{self.disease['name']} 비교 — 참고 사진 ↔ 촬영 사진")
        self.resize(1380, 860)
        self._build()
        if self.captures:
            self.set_patient_item(self._capture_item(self.captures[0]))
        elif self.live_frame is not None:
            self.set_patient_item(self._live_item())
        self._render()

    # ---------------- UI ----------------
    def _build(self) -> None:
        d = self.disease
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)
        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap(d.get("icon", "eye"), ICON_ACCENT, 22))
        head.addWidget(ic)
        pt = self.patient
        who = f"{pt.name}{(' #' + pt.chart_no) if pt and pt.chart_no else ''}" if pt else "환자 미선택"
        title = QLabel(f"<b style='font-size:16px'>{_esc(d['name'])}</b>&nbsp; <span style='color:#8b95a3'>{_esc(d.get('en', ''))}"
                       f"&nbsp;·&nbsp; {_esc(who)}</span>")
        head.addWidget(title)
        head.addStretch(1)
        tip = QLabel("사진을 누르면 그 자리를 확대 · 다시 누르면 원래대로")
        tip.setObjectName("Muted")
        head.addWidget(tip)
        outer.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(10)
        self.ref_box, self.ref_cap, self.ref_strip, self._ref_lay = self._pane(body, "참고", "#33c2b1")
        self.pt_box, self.pt_cap, self.pt_strip, self._pt_lay = self._pane(body, "환자", "#5aa9ff")
        side = QScrollArea()
        side.setObjectName("DxSide")
        side.setWidgetResizable(True)
        side.setFixedWidth(300)
        self.side = QLabel()
        self.side.setObjectName("DxSideText")
        self.side.setWordWrap(True)
        self.side.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.side.setTextFormat(Qt.TextFormat.RichText)
        self.side.setContentsMargins(12, 10, 12, 10)
        side.setWidget(self.side)
        body.addWidget(side)
        outer.addLayout(body, 1)

        foot = QHBoxLayout()
        self.btn_register = QPushButton(icons.gap("참고 사진으로 등록"))
        self.btn_register.setIcon(icons.icon("image", ICON, 15))
        self.btn_register.setToolTip("오른쪽 환자 사진을 이 질환의 참고 사진으로 등록 (환자 이름은 넣지 않음)")
        self.btn_print = QPushButton(icons.gap("인쇄"))
        self.btn_print.setIcon(icons.icon("printer", ICON, 15))
        self.btn_print.setToolTip("비교 사진과 설명을 A4 로 인쇄")
        self.btn_pdf = QPushButton(icons.gap("PDF 저장"))
        self.btn_pdf.setIcon(icons.icon("download", ICON, 15))
        self.btn_save = QPushButton(icons.gap("비교 이미지 저장"))
        self.btn_save.setIcon(icons.icon("save", ICON, 15))
        self.btn_save.setToolTip("두 사진을 나란히 합친 비교 이미지를 환자 기록에 저장")
        self.btn_close = QPushButton("닫기")
        self.btn_close.setObjectName("Primary")
        foot.addWidget(self.btn_register)
        foot.addStretch(1)
        for b in (self.btn_print, self.btn_pdf, self.btn_save, self.btn_close):
            foot.addWidget(b)
        for b in (self.btn_register, self.btn_print, self.btn_pdf, self.btn_save, self.btn_close):
            b.setIconSize(QSize(15, 15))
        outer.addLayout(foot)
        self.btn_register.clicked.connect(self.register_current)
        self.btn_print.clicked.connect(self.print_current)
        self.btn_pdf.clicked.connect(self.pdf_dialog)
        self.btn_save.clicked.connect(self.save_composite)
        self.btn_close.clicked.connect(self.accept)

    def _pane(self, parent_lay, tag: str, color: str):
        pane = QVBoxLayout()
        pane.setSpacing(6)
        row = QHBoxLayout()
        t = QLabel(tag)
        t.setObjectName("DxTag")
        t.setStyleSheet(f"color:{color}; border:1px solid {color};")
        cap = QLabel("—")
        cap.setObjectName("Muted")
        row.addWidget(t)
        row.addWidget(cap, 1)
        pane.addLayout(row)
        box = ImageBox()
        pane.addWidget(box, 1)
        strip = QScrollArea()
        strip.setObjectName("DxStrip")
        strip.setWidgetResizable(True)
        strip.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        strip.setFixedHeight(86)
        inner = QWidget()
        lay = QHBoxLayout(inner)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.setSpacing(6)
        lay.setAlignment(Qt.AlignmentFlag.AlignLeft)
        strip.setWidget(inner)
        pane.addWidget(strip)
        w = QWidget()
        w.setLayout(pane)
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        parent_lay.addWidget(w, 1)
        return box, cap, strip, lay

    # ---------------- 항목 ----------------
    def _capture_item(self, c) -> dict:
        return {"kind": "capture", "path": c.file_path, "caption": capture_caption(c), "eye": c.eye or "NA", "capture": c}

    def _live_item(self) -> dict:
        return {"kind": "live", "frame": self.live_frame, "eye": "NA",
                "caption": "실시간 화면 " + datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    def ref_items(self) -> list[dict]:
        return self.store.items(self.disease["id"])

    def set_ref_item(self, item: dict | None) -> None:
        self.ref = item
        self._render()

    def set_patient_item(self, item: dict | None) -> None:
        self.pt = item
        self._render()

    def _item_pixmap(self, item: dict | None) -> QPixmap | None:
        if not item:
            return None
        if item.get("kind") == "live":
            return QPixmap.fromImage(bgr_to_qimage(item["frame"]))
        return load_pixmap(item["path"], 1600)

    def _item_bgr(self, item: dict | None):
        if not item:
            return None
        if item.get("kind") == "live":
            return item["frame"]
        return load_bgr(item["path"])

    @staticmethod
    def _clear(lay) -> None:
        while lay.count():
            w = lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()

    def _render(self) -> None:
        d = self.disease
        self.ref_box.set_pixmap(self._item_pixmap(self.ref), "아래에서 참고 사진을 고르세요")
        self.ref_cap.setText(self.ref["caption"] if self.ref else "—")
        self._clear(self._ref_lay)
        for it in self.ref_items():
            c = DxCard(it, QSize(100, 72), selected=bool(self.ref and self.ref["path"] == it["path"]), deletable=False)
            c.clicked.connect(self.set_ref_item)
            self._ref_lay.addWidget(c)

        empty = ("상단에서 환자를 선택하세요" if self.patient is None
                 else "촬영 사진이 없습니다" + ("\n아래 '실시간 화면'을 누르면 지금 화면과 비교합니다" if self.live_frame is not None else ""))
        self.pt_box.set_pixmap(self._item_pixmap(self.pt), empty)
        self.pt_cap.setText(self.pt["caption"] if self.pt else "—")
        self._clear(self._pt_lay)
        if self.live_frame is not None:
            b = QPushButton(icons.gap("실시간 화면"))
            b.setObjectName("DxLiveCard")
            b.setIcon(icons.icon("live", "#9fe8dd", 16))
            b.setFixedSize(100, 72)
            b.setToolTip("지금 카메라 화면을 가져와 비교")
            b.setCheckable(True)
            b.setChecked(bool(self.pt and self.pt["kind"] == "live"))
            b.clicked.connect(lambda: self.set_patient_item(self._live_item()))
            self._pt_lay.addWidget(b)
        for c in self.captures:
            it = self._capture_item(c)
            sel = bool(self.pt and self.pt["kind"] == "capture" and self.pt["capture"].id == c.id)
            card = DxCard(it, QSize(100, 72), selected=sel, deletable=False)
            card.setToolTip(it["caption"])
            card.clicked.connect(self.set_patient_item)
            self._pt_lay.addWidget(card)
        if not self.captures and self.live_frame is None:
            lbl = QLabel("촬영 사진 없음" if self.patient else "환자 미선택")
            lbl.setObjectName("Muted")
            self._pt_lay.addWidget(lbl)

        li = lambda xs: "".join(f"<li>{_esc(x)}</li>" for x in (xs or []))  # noqa: E731
        self.side.setText(
            f"<h4>세극등 소견</h4><ul>{li(d.get('findings'))}</ul>"
            f"<h4>환자에게 설명</h4><p>{_esc(d.get('explain'))}</p>"
            f"<h4>비교 포인트</h4><ul>{li(d.get('compare'))}</ul>"
            f"<p class='note'><small style='color:#8b95a3'>{_esc(dx_library.notice())}</small></p>")
        self.btn_register.setEnabled(self.pt is not None)
        self.btn_save.setEnabled(self.pt is not None and self.ref is not None and self.patient is not None)
        has = self.pt is not None or self.ref is not None
        self.btn_print.setEnabled(has)
        self.btn_pdf.setEnabled(has)

    # ---------------- 동작 ----------------
    def register_current(self) -> None:
        if self.pt is None:
            return
        today = datetime.now().strftime("%Y-%m-%d")
        cap, ok = QInputDialog.getText(self, "참고 사진으로 등록", "참고 사진 설명 (환자 이름은 넣지 마세요):",
                                       text=f"{self.disease['name']} 사례 {today}")
        if not ok:
            return
        try:
            if self.pt["kind"] == "live":
                self.store.add_frame(self.disease["id"], self.pt["frame"], cap)
            else:
                self.store.add_file(self.disease["id"], self.pt["path"], cap)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "등록 실패", str(e))
            return
        self.referencesChanged.emit()
        self._render()
        QMessageBox.information(self, "등록", f"'{self.disease['name']}' 참고 사진으로 등록했습니다.")

    def compose(self) -> np.ndarray | None:
        """두 사진을 같은 높이로 나란히 (위에 라벨) 합친 BGR 이미지."""
        a, b = self._item_bgr(self.ref), self._item_bgr(self.pt)
        if a is None or b is None:
            return None
        h, label, gap, pad = 900, 54, 24, 24
        wa, wb = round(a.shape[1] * h / a.shape[0]), round(b.shape[1] * h / b.shape[0])
        img = QImage(pad * 2 + wa + gap + wb, pad + label + h + pad, QImage.Format.Format_RGB888)
        img.fill(QColor("#000000"))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawImage(QRectF(pad, pad + label, wa, h), bgr_to_qimage(a))
        p.drawImage(QRectF(pad + wa + gap, pad + label, wb, h), bgr_to_qimage(b))
        f = QFont()
        f.setFamilies(["Pretendard", "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans CJK KR", "sans-serif"])
        f.setPixelSize(26)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#e7eaf0"))
        tag = " (모식도)" if self.ref.get("kind") == "ill" else ""
        p.drawText(QRectF(pad, pad, wa, label), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   f"참고 · {self.disease['name']}{tag}")
        p.drawText(QRectF(pad + wa + gap, pad, wb, label), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "환자 촬영")
        f.setPixelSize(20)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor("#a3acba"))
        p.drawText(QRectF(pad + wa + gap, pad, wb, label), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   self.pt["caption"])
        p.end()
        return qimage_to_bgr(img)

    def save_composite(self) -> None:
        if self.patient is None:
            QMessageBox.information(self, "저장", "환자를 먼저 선택하세요.")
            return
        img = self.compose()
        if img is None:
            QMessageBox.warning(self, "저장", "사진을 불러오지 못했습니다.")
            return
        try:
            self.service.save_photo(img, self.patient, eye=self.pt.get("eye") or "NA", note=f"비교: {self.disease['name']}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "저장 실패", str(e))
            return
        self.savedCapture.emit()
        QMessageBox.information(self, "저장", f"비교 이미지를 저장했습니다 (메모 '비교: {self.disease['name']}').")

    def print_items(self) -> list:
        items = []
        a = self._item_bgr(self.ref)
        if a is not None:
            tag = " (모식도)" if self.ref.get("kind") == "ill" else ""
            items.append((a, f"참고 · {self.disease['name']}{tag} — {self.ref['caption']}"))
        b = self._item_bgr(self.pt)
        if b is not None:
            items.append((b, f"환자 촬영 — {self.pt['caption']}"))
        return items

    def notes_text(self) -> str:
        d = self.disease
        bl = lambda xs: "\n".join("· " + x for x in (xs or []))  # noqa: E731
        return (f"[세극등 소견]\n{bl(d.get('findings'))}\n\n[환자에게 설명]\n{d.get('explain', '')}\n\n"
                f"[비교 포인트]\n{bl(d.get('compare'))}\n\n{dx_library.notice()}")

    def _render_to(self, printer) -> int:
        b = app_brand.current()
        return print_util.render_report(printer, self.patient, self.print_items(),
                                        clinic=getattr(self.config, "clinic_name", "") or "",
                                        title=f"{b['report_title']} · {self.disease['name']} 비교 설명",
                                        rule_color=b.get("report_rule", "#0d9488"), notes=self.notes_text())

    def print_current(self) -> None:
        if not self.print_items():
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        if QPrintDialog(printer, self).exec():
            self._render_to(printer)

    def export_pdf(self, path: str) -> int:
        return self._render_to(print_util.make_pdf_printer(path))

    def pdf_dialog(self) -> None:
        if not self.print_items():
            return
        base = getattr(self.config, "export_root", "") or os.path.expanduser("~")
        chart = (self.patient.chart_no if self.patient else None) or "compare"
        default = os.path.join(base, f"{chart}_{self.disease['id']}_{datetime.now():%Y%m%d_%H%M}.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "비교 설명 PDF 저장", default, "PDF (*.pdf)")
        if path:
            self.export_pdf(path)
            QMessageBox.information(self, "PDF", f"비교 설명을 저장했습니다.\n{path}")
