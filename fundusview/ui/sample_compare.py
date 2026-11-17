"""질환 샘플과 비교: the patient's photo (as on screen) beside a sample photo of a retinal disease.

The window keeps the sample photos by disease (samples.py): the diseases on the left (how many photos
each), the patient's photo and the chosen sample side by side, the disease's photos in a row under the
sample. Register a sample from a file (사진 추가 · or drop files on the window) or take the patient's photo
on screen as one (보고 있는 사진을 샘플로 — saved as shown, black outside the photo's circle, where cameras
write the patient's name, and under a name of its own: nothing of the patient goes with it); each sample
has a note (설명). With **함께 확대 · 이동** on, zooming or moving one photo
does the same on the other (by the part of the photo shown), so the same place of both is seen.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListView, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSplitter,
                               QToolButton, QVBoxLayout, QWidget)

from .. import imaging
from ..samples import PHOTO_EXTS, SampleLibrary
from .image_view import ImageView, to_qimage

THUMB = QSize(132, 100)
PATH_ROLE = Qt.ItemDataRole.UserRole
NAME_ROLE = Qt.ItemDataRole.UserRole + 1


class SampleCompareDialog(QDialog):
    def __init__(self, library: SampleLibrary, parent=None, take_current=None):
        """``take_current(masked=False)`` → ``(rgb, text)`` of the patient's photo on screen (as shown;
        ``masked``: black outside its circle, for a sample), or None."""
        super().__init__(parent)
        self.setObjectName("sampleCompare")
        self.setWindowTitle("질환 샘플과 비교")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.resize(1440, 880)
        self.setAcceptDrops(True)
        self.lib = library
        self._take_current = take_current
        self._sample: Path | None = None
        self._syncing = False

        # -- the diseases --------------------------------------------------------------------------
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        title = QLabel("질환")
        title.setObjectName("sectionTitle")
        self.diseases = QListWidget()
        self.diseases.setObjectName("diseaseList")
        self.diseases.currentItemChanged.connect(lambda *_: self._fill_samples())
        self.diseases.itemDoubleClicked.connect(lambda _: self._rename_disease())
        row = QHBoxLayout()
        self.b_add_disease = QPushButton("+ 질환")
        self.b_add_disease.setToolTip("질환 추가")
        self.b_add_disease.clicked.connect(self._add_disease)
        self.b_rename = QPushButton("이름 바꾸기")
        self.b_rename.clicked.connect(self._rename_disease)
        self.b_del_disease = QPushButton("삭제")
        self.b_del_disease.setToolTip("이 질환과 그 샘플 사진을 모두 지웁니다")
        self.b_del_disease.clicked.connect(self._remove_disease)
        for b in (self.b_add_disease, self.b_rename, self.b_del_disease):
            row.addWidget(b)
        ll.addWidget(title)
        ll.addWidget(self.diseases, 1)
        ll.addLayout(row)
        where = QLabel(f"보관 폴더: {library.root}")
        where.setWordWrap(True)
        where.setObjectName("hint")
        where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        ll.addWidget(where)

        # -- the two photos ---------------------------------------------------------------------------
        def pane(head: QLabel, view: ImageView) -> QWidget:
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(2)
            head.setObjectName("sampleHead")
            head.setTextFormat(Qt.TextFormat.RichText)
            v.addWidget(head)
            v.addWidget(view, 1)
            return w

        self.lbl_patient = QLabel("환자 사진")
        self.v_patient = ImageView()
        self.lbl_sample = QLabel("샘플")
        self.v_sample = ImageView()
        for v in (self.v_patient, self.v_sample):
            v.set_navigator(False)
            v.zoomChanged.connect(lambda _=None, v=v: self._follow(v))
            v.horizontalScrollBar().valueChanged.connect(lambda _=None, v=v: self._follow(v))
            v.verticalScrollBar().valueChanged.connect(lambda _=None, v=v: self._follow(v))
        self.v_patient.setToolTip("환자 사진 (주 화면에 보이는 대로) — 휠: 배율 · 드래그: 이동")
        self.v_sample.setToolTip("질환 샘플 — 휠: 배율 · 드래그: 이동 · 사진 파일을 끌어다 놓으면 이 질환에 추가")
        photos = QSplitter(Qt.Orientation.Horizontal)
        photos.setChildrenCollapsible(False)
        photos.addWidget(pane(self.lbl_patient, self.v_patient))
        photos.addWidget(pane(self.lbl_sample, self.v_sample))
        photos.setSizes([600, 600])

        # -- the disease's photos, under the sample -------------------------------------------------
        self.strip = QListWidget()
        self.strip.setObjectName("sampleStrip")
        self.strip.setViewMode(QListView.ViewMode.IconMode)
        self.strip.setFlow(QListView.Flow.LeftToRight)
        self.strip.setWrapping(False)
        self.strip.setMovement(QListView.Movement.Static)
        self.strip.setIconSize(THUMB)
        self.strip.setFixedHeight(THUMB.height() + 34)
        self.strip.setSpacing(4)
        self.strip.currentItemChanged.connect(lambda cur, _: self._show_sample(cur))
        self.b_prev = QToolButton()
        self.b_prev.setText("◀")
        self.b_prev.setToolTip("이전 샘플")
        self.b_prev.clicked.connect(lambda: self._step(-1))
        self.b_next = QToolButton()
        self.b_next.setText("▶")
        self.b_next.setToolTip("다음 샘플")
        self.b_next.clicked.connect(lambda: self._step(1))
        srow = QHBoxLayout()
        srow.addWidget(self.b_prev)
        srow.addWidget(self.strip, 1)
        srow.addWidget(self.b_next)

        self.note = QLineEdit()
        self.note.setPlaceholderText("이 샘플의 설명 (예: 증식성 — 시신경 유두 신생혈관)")
        self.note.editingFinished.connect(self._save_note)
        self.b_add = QPushButton("사진 추가…")
        self.b_add.setToolTip("사진 파일을 이 질환의 샘플로 (창에 끌어다 놓아도 됩니다)")
        self.b_add.clicked.connect(self._add_files)
        self.b_take = QPushButton("보고 있는 사진을 샘플로")
        self.b_take.setToolTip("주 화면의 사진(보이는 대로)을 이 질환의 샘플로 — 환자 이름·ID·날짜는 남지 않습니다")
        self.b_take.clicked.connect(self._take)
        self.b_take.setEnabled(take_current is not None)
        self.b_remove = QPushButton("샘플 삭제")
        self.b_remove.clicked.connect(self._remove_sample)
        self.c_sync = QCheckBox("함께 확대 · 이동")
        self.c_sync.setChecked(True)
        self.c_sync.setToolTip("켜면 한쪽 사진을 확대하거나 옮길 때 다른 쪽도 같은 곳을 같은 크기로 보여 줍니다")
        brow = QHBoxLayout()
        brow.addWidget(QLabel("설명"))
        brow.addWidget(self.note, 1)
        brow.addWidget(self.b_add)
        brow.addWidget(self.b_take)
        brow.addWidget(self.b_remove)
        brow.addWidget(self.c_sync)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(photos, 1)
        rl.addLayout(srow)
        rl.addLayout(brow)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([250, 1190])
        lay = QVBoxLayout(self)
        lay.addWidget(split, 1)

        self._fill_diseases()
        self.refresh_patient()

    # -- the patient's photo ---------------------------------------------------------------------
    def refresh_patient(self) -> None:
        """The patient's photo on screen in the main window (as shown there)."""
        got = self._take_current() if self._take_current else None
        if got is None:
            self.v_patient.set_rgb(None)
            self.lbl_patient.setText("환자 사진 — 주 화면에서 사진을 고르세요")
            return
        rgb, text = got
        self.set_patient_photo(rgb, text)

    def set_patient_photo(self, rgb: np.ndarray | None, text: str = "") -> None:
        keep = self.v_patient.has_image() and rgb is not None and self.v_patient._rgb is not None \
            and self.v_patient._rgb.shape == rgb.shape
        self.v_patient.set_rgb(rgb, keep_view=keep)
        self.lbl_patient.setText(f"<b>환자 사진</b>  {text}" if text else "<b>환자 사진</b>")
        if not keep:
            QTimer.singleShot(0, lambda: self._follow(self.v_sample))

    # -- diseases ----------------------------------------------------------------------------------
    def current_disease(self) -> str | None:
        it = self.diseases.currentItem()
        return it.data(NAME_ROLE) if it is not None else None

    def _fill_diseases(self, select: str | None = None) -> None:
        select = select or self.current_disease()
        self.diseases.blockSignals(True)
        self.diseases.clear()
        for name in self.lib.diseases():
            n = self.lib.count(name)
            it = QListWidgetItem(f"{name}  ({n})" if n else name)
            it.setData(NAME_ROLE, name)
            self.diseases.addItem(it)
        self.diseases.blockSignals(False)
        names = self.lib.diseases()
        if not names:
            self._fill_samples()
            return
        if select not in names:   # the first one with photos, else the first
            select = next((d for d in names if self.lib.count(d)), names[0])
        self.diseases.setCurrentRow(names.index(select))
        self._fill_samples()

    def select_disease(self, name: str) -> None:
        names = self.lib.diseases()
        if name in names:
            self.diseases.setCurrentRow(names.index(name))

    def _ask_name(self, title: str, text: str = "") -> str | None:
        name, ok = QInputDialog.getText(self, title, "질환 이름", text=text)
        return name.strip() if ok and name.strip() else None

    def _add_disease(self) -> None:
        name = self._ask_name("질환 추가")
        if name is None:
            return
        try:
            name = self.lib.add_disease(name)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "질환 추가", str(e))
            return
        self._fill_diseases(select=name)

    def _rename_disease(self) -> None:
        old = self.current_disease()
        if old is None:
            return
        new = self._ask_name("질환 이름 바꾸기", old)
        if new is None or new == old:
            return
        try:
            new = self.lib.rename_disease(old, new)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "질환 이름 바꾸기", str(e))
            return
        self._fill_diseases(select=new)

    def _remove_disease(self) -> None:
        name = self.current_disease()
        if name is None:
            return
        n = self.lib.count(name)
        more = f"\n샘플 사진 {n}장도 함께 지워집니다." if n else ""
        if QMessageBox.question(self, "질환 삭제", f"'{name}'을(를) 지울까요?{more}") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.lib.remove_disease(name)
        except OSError as e:
            QMessageBox.warning(self, "질환 삭제", str(e))
        self._fill_diseases()

    def _sync_counts(self) -> None:
        for i in range(self.diseases.count()):
            it = self.diseases.item(i)
            name = it.data(NAME_ROLE)
            n = self.lib.count(name)
            it.setText(f"{name}  ({n})" if n else name)

    # -- the disease's samples ---------------------------------------------------------------------
    def _fill_samples(self, select: Path | None = None) -> None:
        disease = self.current_disease()
        self.strip.blockSignals(True)
        self.strip.clear()
        paths = self.lib.photos(disease) if disease else []
        for p in paths:
            it = QListWidgetItem(p.stem.rsplit("_", 1)[-1])
            it.setData(PATH_ROLE, str(p))
            note = self.lib.note(p)
            it.setToolTip(note or p.name)
            try:
                it.setIcon(QIcon(QPixmap.fromImage(to_qimage(imaging.load_reduced(p, 2 * THUMB.width())))))
            except Exception:                  # (an unreadable file: listed, without a picture)
                pass
            self.strip.addItem(it)
        self.strip.blockSignals(False)
        for b in (self.b_add, self.b_take, self.b_rename, self.b_del_disease):
            b.setEnabled(disease is not None and (b is not self.b_take or self._take_current is not None))
        if paths:
            k = next((i for i, p in enumerate(paths) if select is not None and p == select), 0)
            self.strip.setCurrentRow(k)
            self._show_sample(self.strip.item(k))
        else:
            self._show_sample(None)

    def _show_sample(self, item: QListWidgetItem | None) -> None:
        disease = self.current_disease() or ""
        paths = [Path(self.strip.item(i).data(PATH_ROLE)) for i in range(self.strip.count())]
        path = Path(item.data(PATH_ROLE)) if item is not None else None
        self._sample = path
        self.b_remove.setEnabled(path is not None)
        self.note.setEnabled(path is not None)
        self.b_prev.setEnabled(path is not None and paths.index(path) > 0)
        self.b_next.setEnabled(path is not None and paths.index(path) < len(paths) - 1)
        if path is None:
            self.v_sample.set_rgb(None)
            self.note.setText("")
            self.lbl_sample.setText(f"<b>{disease}</b> — 샘플 사진이 없습니다. [사진 추가…] · 파일을 끌어다 놓기 · "
                                    "[보고 있는 사진을 샘플로]로 등록하세요" if disease else "샘플")
            return
        try:
            rgb = imaging.load_rgb(path)
        except Exception as e:
            self.v_sample.set_rgb(None)
            self.lbl_sample.setText(f"<b>{disease}</b> — 사진을 열 수 없습니다: {e}")
            return
        self.v_sample.set_rgb(rgb)
        note = self.lib.note(path)
        self.note.setText(note)
        k = paths.index(path) + 1
        self.lbl_sample.setText(f"<b>{disease}</b>  {k} / {len(paths)}" + (f"  —  {note}" if note else ""))
        QTimer.singleShot(0, lambda: self._follow(self.v_patient))

    def _step(self, d: int) -> None:
        k = self.strip.currentRow() + d
        if 0 <= k < self.strip.count():
            self.strip.setCurrentRow(k)

    def _save_note(self) -> None:
        if self._sample is None:
            return
        self.lib.set_note(self._sample, self.note.text())
        it = self.strip.currentItem()
        if it is not None:
            it.setToolTip(self.note.text().strip() or self._sample.name)
        self._show_sample(it)

    # -- registering -----------------------------------------------------------------------------
    def add_files(self, files: list[str]) -> int:
        disease = self.current_disease()
        if disease is None or not files:
            return 0
        added, bad, last = 0, [], None
        for f in files:
            try:
                last = self.lib.add_file(disease, f)
                added += 1
            except (ValueError, OSError) as e:
                bad.append(f"{Path(f).name}: {e}")
        self._sync_counts()
        self._fill_samples(select=last)
        if bad:
            QMessageBox.warning(self, "사진 추가", "추가하지 못한 파일:\n" + "\n".join(bad[:10]))
        return added

    def _add_files(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(PHOTO_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, f"'{self.current_disease()}' 샘플 사진", "",
                                                f"영상 ({exts});;모든 파일 (*)")
        self.add_files(files)

    def _take(self) -> None:
        disease = self.current_disease()
        got = self._take_current() if self._take_current else None
        if disease is None or got is None:
            QMessageBox.information(self, "샘플로 등록", "주 화면에서 사진을 먼저 고르세요.")
            return
        rgb, _ = self._take_current(masked=True) or got
        note, ok = QInputDialog.getText(self, "보고 있는 사진을 샘플로", f"'{disease}' 샘플의 설명 (비워 두어도 됩니다)\n"
                                        "사진 원 밖(환자 이름 등이 찍히는 곳)은 검게 저장합니다")
        if not ok:
            return
        path = self.lib.add_rgb(disease, rgb, note)
        self._sync_counts()
        self._fill_samples(select=path)

    def _remove_sample(self) -> None:
        if self._sample is None:
            return
        if QMessageBox.question(self, "샘플 삭제", "이 샘플 사진을 지울까요?") != QMessageBox.StandardButton.Yes:
            return
        k = self.strip.currentRow()
        self.lib.remove_photo(self._sample)
        self._sync_counts()
        paths = self.lib.photos(self.current_disease() or "")
        self._fill_samples(select=paths[min(k, len(paths) - 1)] if paths else None)

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls() and self.current_disease() is not None:
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        files = [f for f in files if Path(f).suffix.lower() in PHOTO_EXTS]
        if files:
            self.add_files(files)
            e.acceptProposedAction()

    # -- 함께 확대 · 이동 ----------------------------------------------------------------------------
    @staticmethod
    def _shown(view: ImageView) -> QRectF | None:
        """The part of the photo shown, as fractions of the photo (0 … 1)."""
        if not view.has_image() or view._rgb is None:
            return None
        h, w = view._rgb.shape[:2]
        r = view.mapToScene(view.viewport().rect()).boundingRect()
        return QRectF(r.x() / w, r.y() / h, r.width() / w, r.height() / h)

    def _follow(self, src: ImageView) -> None:
        """The other photo shows the same part of itself as ``src`` (함께 확대 · 이동)."""
        if self._syncing or not self.c_sync.isChecked():
            return
        dst = self.v_sample if src is self.v_patient else self.v_patient
        part = self._shown(src)
        if part is None or not dst.has_image() or dst._rgb is None:
            return
        h, w = dst._rgb.shape[:2]
        self._syncing = True
        try:
            dst.zoom_to_rect(QRectF(part.x() * w, part.y() * h, part.width() * w, part.height() * h), animate=False)
        finally:
            self._syncing = False
