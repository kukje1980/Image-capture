"""Pro '분석' 탭 — 영상 품질 · 형광염색 · 결막 충혈 · 마이봄샘 · 수정체 지수 · 이전 영상 정렬 ·
가장 선명한 영상 찾기 · TBUT(동영상) · DICOM 내보내기.

모든 수치는 규칙 기반 영상처리로 구한 '참고 지표'다. 결과는 오버레이로 보여 주고, 의사가 확인한 뒤
코멘트·결과 영상으로 남긴다 (자동으로 기록되지 않는다).
"""
from __future__ import annotations

import html
import logging
import os
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from app.analysis import clinical, dicom_export, tbut

if TYPE_CHECKING:  # pragma: no cover
    from app.ui.pro.pro_workspace import ProWorkspace

log = logging.getLogger(__name__)

DISCLAIMER = ("규칙 기반 영상처리로 구한 참고 지표입니다. 진단·등급 판정은 의사가 영상을 보고 내립니다. "
              "같은 조명·배율로 찍은 영상끼리 비교하세요.")


def rows_html(res: clinical.AnalysisResult) -> str:
    body = "".join(f"<tr><td style='padding-right:10px;color:#8a94a6'>{html.escape(k)}</td>"
                   f"<td><b>{html.escape(v)}</b></td></tr>" for k, v in res.rows)
    return f"<b>{html.escape(res.title)}</b><table cellspacing='0' cellpadding='2'>{body}</table>"


class TBUTPlot(QWidget):
    """밝기(회색)·건조 반점 비율(주황) 그래프 + 깜빡임 끝/파괴 시점 표시."""

    def __init__(self, res: tbut.TBUTResult, parent=None):
        super().__init__(parent)
        self.res = res
        self.setMinimumSize(520, 200)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#0b1220"))
        r = self.res
        if not r.times:
            return
        m = 28.0
        W, H = self.width() - 2 * m, self.height() - 2 * m
        t_end = max(r.times[-1], 1e-6)

        def x(t):
            return m + W * t / t_end

        def path(vals, vmax):
            pp = QPainterPath(QPointF(x(r.times[0]), m + H * (1 - vals[0] / vmax)))
            for t, v in zip(r.times, vals):
                pp.lineTo(QPointF(x(t), m + H * (1 - min(v, vmax) / vmax)))
            return pp

        p.setPen(QPen(QColor("#334155"), 1))
        p.drawRect(QRectF(m, m, W, H))
        p.setPen(QPen(QColor("#94a3b8"), 1.5))
        p.drawPath(path(r.brightness, max(max(r.brightness), 1.0)))
        if r.dark_frac:
            vmax = max(0.05, max(r.dark_frac) * 1.1)
            p.setPen(QPen(QColor("#f59e0b"), 2))
            p.drawPath(path(r.dark_frac, vmax))
        for t, col, label in ((r.blink_end_s, "#38bdf8", "깜빡임 끝"), (r.breakup_s, "#f43f5e", "파괴")):
            if t is None:
                continue
            p.setPen(QPen(QColor(col), 1.5, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(x(t), m), QPointF(x(t), m + H))
            p.drawText(QPointF(x(t) + 4, m + 12), f"{label} {t:.1f}s")
        p.setPen(QColor("#94a3b8"))
        p.drawText(QPointF(m, self.height() - 8), "0s")
        p.drawText(QPointF(m + W - 30, self.height() - 8), f"{t_end:.0f}s")
        p.drawText(QPointF(m + 40, self.height() - 8), "— 밝기   ")
        p.setPen(QColor("#f59e0b"))
        p.drawText(QPointF(m + 110, self.height() - 8), "— 건조 반점 비율")


class TBUTDialog(QDialog):
    def __init__(self, res: tbut.TBUTResult, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TBUT 분석")
        lay = QVBoxLayout(self)
        head = QLabel(f"<h2 style='margin:0'>{html.escape(res.message)}</h2>")
        lay.addWidget(head)
        lay.addWidget(TBUTPlot(res))
        note = QLabel("형광염색 동영상의 녹색 밝기로 계산한 참고값입니다. 그래프와 파괴 시점 영상을 보고 확인하세요.\n"
                      "분석 영역: 화면 중앙 50% · 깜빡임 = 밝기 60% 이하 · 건조 반점 = 깜빡임 직후보다 40% 이상 어두워진 곳")
        note.setWordWrap(True)
        note.setObjectName("Muted")
        lay.addWidget(note)
        btns = QDialogButtonBox()
        self.b_save = btns.addButton("파괴 시점 영상 저장", QDialogButtonBox.ButtonRole.AcceptRole)
        self.b_save.setEnabled(res.ok and res.breakup_frame is not None)
        btns.addButton("닫기", QDialogButtonBox.ButtonRole.RejectRole)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)


class AnalysisPanel(QWidget):
    def __init__(self, ws: "ProWorkspace"):
        super().__init__()
        self.ws = ws
        self.setObjectName("ProTabPage")
        self.result: Optional[clinical.AnalysisResult] = None
        self._result_canvas = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 8, 4, 4)
        lay.setSpacing(6)

        lay.addWidget(ws._sub("영상 분석"))
        tip = QLabel("편집 탭의 '원' 도구로 영역(각막·결막·눈꺼풀·수정체)을 그리면 그 안만 분석합니다. 없으면 전체.")
        tip.setWordWrap(True)
        tip.setObjectName("Muted")
        lay.addWidget(tip)
        self.c_kind = QComboBox()
        for k in clinical.KINDS:
            self.c_kind.addItem(clinical.KIND_LABELS[k], k)
        lay.addWidget(self.c_kind)
        self.chk_dark = QCheckBox("샘이 어둡게 보임 (투과 조명)")
        self.chk_dark.setVisible(False)
        lay.addWidget(self.chk_dark)
        g = QGridLayout()
        g.setSpacing(4)
        self.b_run = ws._btn("분석 실행", "현재 영상(1화면·비교·LIVE 정지)을 분석", obj="ProPrimary")
        self.b_clear = ws._btn("표시 지우기", "분석 오버레이 지우기")
        self.b_note = ws._btn("코멘트에 추가", "분석 요약을 이 영상의 코멘트에 덧붙임")
        self.b_save = ws._btn("결과 영상 저장", "오버레이·주석을 합성한 새 영상으로 저장 (원본 보존)")
        g.addWidget(self.b_run, 0, 0)
        g.addWidget(self.b_clear, 0, 1)
        g.addWidget(self.b_note, 1, 0)
        g.addWidget(self.b_save, 1, 1)
        lay.addLayout(g)
        self.lbl_result = QLabel("분석할 영상을 1화면이나 비교에서 여세요.")
        self.lbl_result.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_result.setWordWrap(True)
        self.lbl_result.setObjectName("AnalysisResult")
        lay.addWidget(self.lbl_result)
        self.lbl_warn = QLabel("")
        self.lbl_warn.setWordWrap(True)
        self.lbl_warn.setStyleSheet("color:#f5b94a;")
        lay.addWidget(self.lbl_warn)

        lay.addWidget(ws._sub("이전 영상 비교 · 선택"))
        g2 = QGridLayout()
        g2.setSpacing(4)
        self.b_align = ws._btn("자동 정렬", "비교 화면에서 오른쪽 영상을 왼쪽에 맞춰 회전·확대·이동")
        self.b_best = ws._btn("가장 선명한 영상", "MULTI 선택(없으면 최근 촬영일) 중 가장 선명한 영상을 엶")
        g2.addWidget(self.b_align, 0, 0)
        g2.addWidget(self.b_best, 0, 1)
        lay.addLayout(g2)

        lay.addWidget(ws._sub("동영상 · 내보내기"))
        g3 = QGridLayout()
        g3.setSpacing(4)
        self.b_tbut = ws._btn("TBUT 분석", "형광염색 동영상에서 눈물막 파괴 시간 측정")
        self.b_dicom = ws._btn("DICOM 저장", "Ophthalmic Photography(OP) DICOM 파일로 내보내기 — PACS 연동")
        g3.addWidget(self.b_tbut, 0, 0)
        g3.addWidget(self.b_dicom, 0, 1)
        lay.addLayout(g3)

        disc = QLabel(DISCLAIMER)
        disc.setWordWrap(True)
        disc.setObjectName("Muted")
        lay.addWidget(disc)
        lay.addStretch(1)

        self.c_kind.currentIndexChanged.connect(self._on_kind)
        self.b_run.clicked.connect(self.run)
        self.b_clear.clicked.connect(self.clear)
        self.b_note.clicked.connect(self.add_to_comment)
        self.b_save.clicked.connect(self.save_result_image)
        self.b_align.clicked.connect(self.align_compare)
        self.b_best.clicked.connect(self.open_sharpest)
        self.b_tbut.clicked.connect(self._tbut_dialog)
        self.b_dicom.clicked.connect(self._dicom_dialog)
        self.sync()

    # ---- 상태 ----
    def kind(self) -> str:
        return self.c_kind.currentData()

    def set_kind(self, kind: str) -> None:
        self.c_kind.setCurrentIndex(list(clinical.KINDS).index(kind))

    def _on_kind(self, *_) -> None:
        self.chk_dark.setVisible(self.kind() == "meibography")

    def sync(self) -> None:
        """모드·영상이 바뀔 때 버튼 상태를 맞춘다."""
        ws = self.ws
        cv = ws.active_canvas()
        has = cv is not None and cv.image() is not None
        self.b_run.setEnabled(has)
        valid = self.result is not None and self._result_canvas is cv
        self.b_clear.setEnabled(bool(self.result))
        self.b_note.setEnabled(bool(valid and ws.mode() == "single"))
        self.b_save.setEnabled(bool(valid and ws.mode() in ("single", "compare")))
        self.b_align.setEnabled(ws.mode() == "compare")
        self.b_best.setEnabled(len(ws.captures()) >= 2)
        self.b_tbut.setEnabled(ws._patient is not None)
        self.b_dicom.setEnabled(ws._patient is not None and bool(ws.captures()))

    # ---- 분석 ----
    def run(self) -> Optional[clinical.AnalysisResult]:
        ws = self.ws
        cv = ws.active_canvas()
        img = cv.image() if cv is not None else None
        if img is None:
            return None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            res = clinical.analyze(self.kind(), img, cv.annotations(), ws.config.px_per_mm or 0.0,
                                   glands_dark=self.chk_dark.isChecked())
        except Exception as e:  # noqa: BLE001
            log.exception("analysis failed")
            QMessageBox.warning(self, "분석", f"분석하지 못했습니다.\n{e}")
            return None
        finally:
            QApplication.restoreOverrideCursor()
        for other in ws._canvases():
            if other is not cv:
                other.set_analysis_overlay(None)
        cv.set_analysis_overlay(res.overlay)
        self.result, self._result_canvas = res, cv
        self.lbl_result.setText(rows_html(res))
        self.lbl_warn.setText(res.warning)
        self.sync()
        return res

    def clear(self) -> None:
        for cv in self.ws._canvases():
            cv.set_analysis_overlay(None)
        self.result = self._result_canvas = None
        self.lbl_result.setText("")
        self.lbl_warn.setText("")
        self.sync()

    def on_view_changed(self) -> None:
        """다른 영상·모드로 바뀌면 이전 분석 결과는 그 영상의 것이 아니므로 지운다."""
        if self.result is not None:
            self.result = self._result_canvas = None
            self.lbl_result.setText("")
            self.lbl_warn.setText("")
        self.sync()

    def add_to_comment(self) -> None:
        ws = self.ws
        if self.result is None or ws.mode() != "single" or not (0 <= ws._idx < len(ws._caps)):
            return
        cap = ws._caps[ws._idx]
        res = self.result
        text = f"{cap.note} / {res.summary}" if cap.note else res.summary
        ws.set_comment(text)                    # 영상을 다시 읽으므로 결과·오버레이를 되살린다
        ws.single_canvas.set_analysis_overlay(res.overlay)
        self.result, self._result_canvas = res, ws.single_canvas
        self.lbl_result.setText(rows_html(res))
        self.lbl_warn.setText(res.warning)
        self.sync()

    def save_result_image(self):
        ws = self.ws
        cv = self._result_canvas
        if self.result is None or cv is None or cv.image() is None or not ws._require_patient():
            return None
        if ws.mode() == "single" and 0 <= ws._idx < len(ws._caps):
            eye = ws._caps[ws._idx].eye or "NA"
        elif ws.mode() == "compare":
            src = ws._pair[0] if cv is ws.cmp_left else ws._pair[1]
            eye = (src.eye if src else None) or "NA"
        else:
            eye = ws.current_eye()
        try:
            cap = ws.service.save_photo(cv.render_to_bgr(), ws._patient, eye=eye,
                                        note=f"분석 · {self.result.summary}")
        except Exception as e:  # noqa: BLE001
            log.exception("analysis image save failed")
            QMessageBox.warning(self, "저장 실패", f"결과 영상을 저장하지 못했습니다.\n{e}")
            return None
        ws.reload(select_last=False)
        ws.savedCapture.emit()
        return cap

    # ---- 이전 영상 비교 ----
    def align_compare(self) -> Optional[clinical.AlignResult]:
        ws = self.ws
        if ws.mode() != "compare":
            return None
        ref, mov = ws.cmp_left.image(), ws.cmp_right.image()
        if ref is None or mov is None:
            return None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            res = clinical.align(ref, mov)
        finally:
            QApplication.restoreOverrideCursor()
        gap = clinical.exposure_gap(ref, mov)
        msg = res.message
        if gap > 25:
            msg += f"<br>밝기 차이가 큽니다(Δ{gap:.0f}) — 조명·노출이 달라 변화처럼 보일 수 있습니다"
        if res.ok:
            ws.cmp_right.set_image(res.image, keep_view=True)
            ws.cmp_right.set_adjust(ws.adjust())
            ws.cmp_right.set_caption("정렬됨 · " + (ws._pair[1].captured_at if ws._pair[1] else ""))
        self.lbl_result.setText(f"<b>이전 영상 자동 정렬</b><br>{msg}")
        self.lbl_warn.setText("" if res.ok else "정렬하지 못해 원래 영상을 그대로 둡니다")
        return res

    def open_sharpest(self) -> Optional[int]:
        ws = self.ws
        caps = ws.captures()
        sel = ws.multi.selection()
        if len(sel) >= 2:
            idx = list(sel)
        else:
            last_day = (caps[-1].captured_at or "")[:10] if caps else ""
            idx = [i for i, c in enumerate(caps) if (c.captured_at or "")[:10] == last_day]
        if len(idx) < 2:
            return None
        from app.ui.pro.pro_workspace import load_bgr
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            scores = []
            for i in idx:
                img = load_bgr(caps[i].file_path)
                if img is not None:
                    scores.append((clinical.sharpness_of(img), i))
        finally:
            QApplication.restoreOverrideCursor()
        if not scores:
            return None
        scores.sort(reverse=True)
        best = scores[0][1]
        ws.open_index(best)
        rank = "".join(f"<tr><td>{n + 1}.</td><td>{html.escape(caps[i].captured_at or '')}</td>"
                       f"<td align='right'><b>{s:.1f}</b></td></tr>" for n, (s, i) in enumerate(scores[:8]))
        self.lbl_result.setText(f"<b>선명도 순위 ({len(scores)}장)</b><table cellpadding='2'>{rank}</table>")
        self.lbl_warn.setText("")
        self.sync()
        return best

    # ---- TBUT ----
    def videos(self) -> list:
        ws = self.ws
        if ws._patient is None:
            return []
        return [c for c in ws.db.captures.list_by_patient(ws._patient.id, order="desc") if c.media_type == "video"]

    def run_tbut(self, path: str) -> tbut.TBUTResult:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            return tbut.analyze_video(path)
        finally:
            QApplication.restoreOverrideCursor()

    def save_tbut(self, res: tbut.TBUTResult, video=None):
        ws = self.ws
        if res.breakup_frame is None or not ws._require_patient():
            return None
        eye = (video.eye if video else None) or ws.current_eye()
        cap = ws.service.save_photo(res.breakup_frame, ws._patient, eye=eye, note=f"TBUT {res.tbut_s:.1f}초 (파괴 시점)")
        ws.reload(select_last=False)
        ws.savedCapture.emit()
        return cap

    def _tbut_dialog(self) -> None:
        vids = self.videos()
        video = None
        if vids:
            items = [f"{v.captured_at}  {v.eye or ''}  {(v.duration_ms or 0) // 1000}초" for v in vids] + ["파일에서 선택…"]
            item, ok = QInputDialog.getItem(self, "TBUT 분석", "형광염색 동영상:", items, 0, False)
            if not ok:
                return
            if item != items[-1]:
                video = vids[items.index(item)]
        path = video.file_path if video else QFileDialog.getOpenFileName(
            self, "형광염색 동영상", "", "동영상 (*.mp4 *.avi *.mov *.mkv)")[0]
        if not path or not os.path.exists(path):
            return
        res = self.run_tbut(path)
        self.lbl_result.setText(f"<b>TBUT</b><br>{html.escape(res.message)}")
        dlg = TBUTDialog(res, self)
        if dlg.exec() and res.ok:
            self.save_tbut(res, video)

    # ---- DICOM ----
    def dicom_targets(self) -> list:
        """(이미지, capture, derived) — 1화면은 화면 그대로(보정·주석 반영 시 파생본), MULTI 는 선택 원본."""
        from app.ui.pro.pro_workspace import load_bgr
        ws = self.ws
        if ws.mode() == "single" and 0 <= ws._idx < len(ws._caps):
            cv = ws.single_canvas
            if cv.image() is None:
                return []
            derived = cv.is_modified() or cv.has_analysis_overlay()
            img = cv.render_to_bgr() if derived else cv.original()
            return [(img, ws._caps[ws._idx], derived)]
        if ws.mode() == "compare":
            return [(load_bgr(c.file_path), c, False) for c in ws._pair if c is not None]
        sel = ws.multi.selection() or ws.multi.page_indices()
        return [(load_bgr(ws._caps[i].file_path), ws._caps[i], False) for i in sel]

    def export_dicom(self, folder: str) -> list:
        ws = self.ws
        out = []
        inst = getattr(ws.config, "clinic_name", "") or ""
        for img, cap, derived in self.dicom_targets():
            if img is None:
                continue
            name = dicom_export.default_name(ws._patient, cap)
            if derived:
                name = name.replace(".dcm", "_derived.dcm")
            out.append(dicom_export.export(img, ws._patient, os.path.join(folder, name), cap, inst, derived))
        return out

    def _dicom_dialog(self) -> None:
        ws = self.ws
        if not ws._require_patient():
            return
        base = os.path.join(getattr(ws.config, "export_root", "") or os.path.expanduser("~"), "dicom")
        folder = QFileDialog.getExistingDirectory(self, "DICOM 저장 폴더", base)
        if not folder:
            return
        try:
            paths = self.export_dicom(folder)
        except Exception as e:  # noqa: BLE001
            log.exception("dicom export failed")
            QMessageBox.warning(self, "DICOM", f"내보내지 못했습니다.\n{e}")
            return
        QMessageBox.information(self, "DICOM", f"{len(paths)}개 파일을 저장했습니다.\n{folder}")

