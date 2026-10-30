"""Pro 모드 인쇄 / PDF 보고서.

A4 한 페이지에 머리말(기관명·제목·출력일시), 환자 정보(이름·차트번호·성별·
생년월일·진단명·담당의), 영상(1장=전체, 2장=좌우, 3~4장=2×2, 그 이상은 4장씩
다음 페이지)과 영상별 캡션, 꼬리말(쪽번호·확인자 서명란)을 배치한다.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPageSize, QPainter, QPen
from PySide6.QtPrintSupport import QPrinter

from app.capture.frame_utils import bgr_to_qimage

_SEX = {"M": "남", "F": "여", "O": "기타"}


def make_pdf_printer(path: str) -> QPrinter:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(path)
    return printer


def patient_line(patient) -> str:
    if patient is None:
        return "환자 미선택"
    parts = [f"{patient.name} ({patient.chart_no or '-'})"]
    if patient.sex:
        parts.append(_SEX.get(patient.sex, patient.sex))
    if patient.birth_date:
        parts.append(patient.birth_date)
    return "  ·  ".join(parts)


def render_report(printer, patient, items: list, title: str = "슬릿램프 영상 보고서",
                  clinic: str = "", rule_color: str = "#0d9488", notes: str = "") -> int:
    """items: [(bgr ndarray, caption str), ...]. 반환값: 출력 페이지 수.

    notes 를 주면 소견란에 그 글을 인쇄하고(줄바꿈 유지), 비어 있으면 손으로 쓸 줄만 그린다."""
    if not items:
        return 0
    pages = [items[i:i + 4] for i in range(0, len(items), 4)] if len(items) > 2 else [items]
    painter = QPainter(printer)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    W, H = printer.width(), printer.height()
    m = W * 0.02
    printed = datetime.now().strftime("%Y-%m-%d %H:%M")

    def font(pt, bold=False):
        f = QFont()
        f.setFamilies(["Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans CJK KR", "sans-serif"])
        f.setPointSizeF(pt)
        f.setBold(bold)
        return f

    for pno, page in enumerate(pages, start=1):
        if pno > 1:
            printer.newPage()
        y = m
        # --- 머리말 ---
        painter.setPen(QColor("#0f172a"))
        painter.setFont(font(15, True))
        fm = painter.fontMetrics()
        head = f"{clinic}  {title}" if clinic else title
        painter.drawText(QRectF(m, y, W - 2 * m, fm.height()), Qt.AlignmentFlag.AlignLeft, head)
        painter.setFont(font(8.5))
        painter.drawText(QRectF(m, y, W - 2 * m, fm.height()),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, f"출력 {printed}")
        y += fm.height() + m * 0.3
        painter.setPen(QPen(QColor(rule_color), max(2.0, W / 900)))
        painter.drawLine(int(m), int(y), int(W - m), int(y))
        y += m * 0.6

        # --- 환자 정보 ---
        painter.setPen(QColor("#0f172a"))
        painter.setFont(font(10.5, True))
        fm = painter.fontMetrics()
        painter.drawText(QRectF(m, y, W - 2 * m, fm.height()), Qt.AlignmentFlag.AlignLeft,
                         "환자: " + patient_line(patient))
        y += fm.height() * 1.25
        painter.setFont(font(9.5))
        fm = painter.fontMetrics()
        diag = (patient.diagnosis if patient and patient.diagnosis else "-")
        doc = (patient.doctor if patient and patient.doctor else "-")
        painter.drawText(QRectF(m, y, W - 2 * m, fm.height()), Qt.AlignmentFlag.AlignLeft,
                         f"진단명: {diag}      담당의: {doc}")
        y += fm.height() * 1.6

        # --- 영상 영역 ---
        footer_h = H * 0.06
        area = QRectF(m, y, W - 2 * m, H - y - footer_h - m)
        n = len(page)
        cols, rows = (1, 1) if n == 1 else (2, 1) if n == 2 else (2, 2)
        gap = m * 0.6
        painter.setFont(font(8.5))
        cap_h = painter.fontMetrics().height() * 1.6
        # 영상 비율에 맞춰 칸 높이를 정해 빈 여백(검은 띠)을 없앤다
        aspect = max(0.2, max(img.shape[1] / img.shape[0] for img, _ in page))
        cw = (area.width() - gap * (cols - 1)) / cols
        ih = min(cw / aspect, (area.height() - gap * (rows - 1)) / rows - cap_h)
        cw = min(cw, ih * aspect)
        x0 = area.x() + (area.width() - (cw * cols + gap * (cols - 1))) / 2
        frame_pen = QPen(QColor("#cbd5e1"), max(1.0, W / 1600))
        for k, (img, caption) in enumerate(page):
            r, c = divmod(k, cols)
            box = QRectF(x0 + c * (cw + gap), area.y() + r * (ih + cap_h + gap), cw, ih)
            qimg = bgr_to_qimage(img)
            s = min(box.width() / qimg.width(), box.height() / qimg.height())
            dw, dh = qimg.width() * s, qimg.height() * s
            target = QRectF(box.x() + (box.width() - dw) / 2, box.y() + (box.height() - dh) / 2, dw, dh)
            painter.drawImage(target, qimg)
            painter.setPen(frame_pen)
            painter.drawRect(target)
            painter.setPen(QColor("#334155"))
            painter.drawText(QRectF(box.x(), box.bottom() + cap_h * 0.15, box.width(), cap_h),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, caption)

        # --- 소견란 (남는 공간) ---
        fy = H - footer_h
        img_bottom = area.y() + rows * (ih + cap_h + gap)
        if fy - img_bottom > H * 0.1:
            painter.setPen(QColor("#0f172a"))
            painter.setFont(font(10, True))
            fm = painter.fontMetrics()
            fy0 = img_bottom + m * 0.4
            painter.drawText(QRectF(m, fy0, W - 2 * m, fm.height()), Qt.AlignmentFlag.AlignLeft, "소견")
            box = QRectF(m, fy0 + fm.height() * 1.3, W - 2 * m, fy - fy0 - fm.height() * 1.3 - m * 0.6)
            painter.setPen(QPen(QColor("#cbd5e1"), max(1.0, W / 1600)))
            painter.drawRoundedRect(box, m * 0.3, m * 0.3)
            if notes:
                painter.setPen(QColor("#0f172a"))
                painter.setFont(font(9))
                painter.drawText(box.adjusted(m * 0.4, m * 0.3, -m * 0.4, -m * 0.3),
                                 Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop, notes)
            else:
                line_gap = max(fm.height() * 1.8, box.height() / 8)
                yl = box.y() + line_gap
                painter.setPen(QPen(QColor("#e2e8f0"), max(1.0, W / 2000)))
                while yl < box.bottom() - line_gap * 0.3:
                    painter.drawLine(int(box.x() + m * 0.4), int(yl), int(box.right() - m * 0.4), int(yl))
                    yl += line_gap

        # --- 꼬리말 ---
        painter.setPen(QPen(QColor("#cbd5e1"), max(1.0, W / 1600)))
        painter.drawLine(int(m), int(fy), int(W - m), int(fy))
        painter.setPen(QColor("#475569"))
        painter.setFont(font(8.5))
        fm = painter.fontMetrics()
        painter.drawText(QRectF(m, fy + m * 0.4, W - 2 * m, fm.height()), Qt.AlignmentFlag.AlignLeft,
                         "확인자 서명: ________________")
        painter.drawText(QRectF(m, fy + m * 0.4, W - 2 * m, fm.height()), Qt.AlignmentFlag.AlignRight,
                         f"{pno} / {len(pages)}")
    painter.end()
    return len(pages)
