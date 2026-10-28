"""Dialogs: image ↔ patient assignment, patient edit, settings."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QCompleter, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from ..config import ACTIONS, Settings, WatchFolder
from ..db import Database
from ..extract.filename_meta import filename_meta
from ..extract.normalize import norm_date, norm_time
from ..models import FIELD_LABELS, META_FIELDS, MODALITY_LABELS
from ..profiles import AUTO, PROFILES, get_profile

SOURCE_LABELS = {
    "dicom": "DICOM", "apollo": "APOLLO 데이터", "apollo-json": "APOLLO 환자 파일", "folder": "폴더 이름",
    "filename": "파일 이름", "exif": "EXIF", "jpeg-comment": "JPEG 주석", "png-text": "PNG 텍스트",
    "xmp": "XMP", "profile": "프로필 기본값", "file-time": "파일 시각", "disc-estimate": "시신경 위치로 추정",
    "manual": "직접 입력",
}
EYES = [("", "-"), ("OD", "OD (우안)"), ("OS", "OS (좌안)"), ("OU", "OU (양안)")]
SEXES = [("", "-"), ("M", "남"), ("F", "여"), ("O", "기타")]
ACTION_LABELS = {"copy": "복사 (원본 유지)", "move": "이동", "reference": "원본 위치 참조"}


def source_label(src: str | None) -> str:
    if not src:
        return ""
    return SOURCE_LABELS.get(src, src.replace("sidecar", "부속 파일 "))


def _combo(items, current) -> QComboBox:
    cb = QComboBox()
    for key, label in items:
        cb.addItem(label, key)
    i = cb.findData(current or "")
    cb.setCurrentIndex(max(i, 0))
    return cb


class ImageDialog(QDialog):
    """Assign an image to a patient and correct its exam fields."""

    def __init__(self, db: Database, image, parent=None):
        super().__init__(parent)
        self.db = db
        self.image = image
        self.setWindowTitle("환자 지정 / 영상 정보 수정")
        self.setMinimumWidth(520)
        meta = json.loads(image["meta_json"] or "{}")
        sources = meta.get("sources", {})
        patient = db.get_patient(image["patient_ref"]) if image["patient_ref"] else None

        form = QFormLayout()
        self.pid = QComboBox()
        self.pid.setEditable(True)
        ids = [(r["patient_id"], r["name"] or "") for r in db.list_patients()]
        self.pid.addItem("")
        for pid, name in ids:
            self.pid.addItem(f"{pid}", pid)
        self.pid.setCompleter(QCompleter([p for p, _ in ids]))
        self.pid.setCurrentText(patient["patient_id"] if patient else (meta.get("patient_id") or ""))
        self.pid.currentTextChanged.connect(self._fill_patient)
        self.name = QLineEdit(patient["name"] if patient and patient["name"] else (meta.get("name") or ""))
        self.birth = QLineEdit((patient["birth_date"] if patient else None) or (meta.get("birth_date") or ""))
        self.birth.setPlaceholderText("YYYY-MM-DD")
        self.sex = _combo(SEXES, (patient["sex"] if patient else None) or meta.get("sex"))
        self.exam_date = QLineEdit(image["exam_date"] or "")
        self.exam_date.setPlaceholderText("YYYY-MM-DD")
        self.exam_time = QLineEdit(image["exam_time"] or "")
        self.eye = _combo(EYES, image["laterality"])
        self.modality = _combo([("", "-")] + list(MODALITY_LABELS.items()), image["modality"])
        self.note = QLineEdit(image["note"] or "")

        def row(label, w, field):
            src = source_label(sources.get(field))
            if src:
                w.setToolTip(f"추출 근거: {src}")
                label = f"{label}  ·  {src}"
            form.addRow(label, w)

        row("환자 ID", self.pid, "patient_id")
        row("이름", self.name, "name")
        row("생년월일", self.birth, "birth_date")
        row("성별", self.sex, "sex")
        row("검사일", self.exam_date, "exam_date")
        row("검사 시각", self.exam_time, "exam_time")
        row("눈", self.eye, "laterality")
        row("촬영 종류", self.modality, "modality")
        form.addRow("메모", self.note)

        lay = QVBoxLayout(self)
        hint = QLabel("파일에서 추출한 값입니다. 환자 ID를 비우면 '미분류'로 남습니다.\n"
                      "기존 환자 ID를 고르면 그 환자의 기록으로 들어갑니다.")
        hint.setStyleSheet("color:#667")
        lay.addWidget(hint)
        lay.addLayout(form)
        orig = QLabel(f"원본: {image['original_path'] or ''}")
        orig.setWordWrap(True)
        orig.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        orig.setStyleSheet("color:#889; font-size:11px")
        lay.addWidget(orig)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _fill_patient(self, text: str) -> None:
        row = self.db.find_patient(text.strip())
        if row is not None:
            self.name.setText(row["name"] or "")
            self.birth.setText(row["birth_date"] or "")
            i = self.sex.findData(row["sex"] or "")
            self.sex.setCurrentIndex(max(i, 0))

    def _accept(self) -> None:
        for w, kind in ((self.birth, "date"), (self.exam_date, "date")):
            t = w.text().strip()
            if t and not norm_date(t):
                QMessageBox.warning(self, "날짜 형식", f"날짜를 YYYY-MM-DD 형식으로 입력하세요: {t}")
                return
        self.accept()

    def apply(self) -> int | None:
        """Write the dialog's values; returns the image's patient ref."""
        from ..models import ExtractedMeta

        pid = self.pid.currentText().strip()
        name = self.name.text().strip() or None
        birth = norm_date(self.birth.text().strip()) if self.birth.text().strip() else None
        sex = self.sex.currentData() or None
        ref = None
        if pid:
            existing = self.db.find_patient(pid)
            if existing is None:
                ref = self.db.upsert_patient(ExtractedMeta(patient_id=pid, name=name, birth_date=birth, sex=sex))
            else:
                ref = existing["id"]
                changes = {k: v for k, v in (("name", name), ("birth_date", birth), ("sex", sex))
                           if v and v != existing[k]}
                if changes:
                    self.db.update_patient(ref, **changes)
        self.db.update_image(
            self.image["id"], patient_ref=ref,
            exam_date=norm_date(self.exam_date.text().strip()) if self.exam_date.text().strip() else None,
            exam_time=norm_time(self.exam_time.text().strip()) if self.exam_time.text().strip() else None,
            laterality=self.eye.currentData() or None, modality=self.modality.currentData() or None,
            note=self.note.text().strip() or None,
        )
        return ref


class PatientDialog(QDialog):
    def __init__(self, db: Database, patient, parent=None):
        super().__init__(parent)
        self.db, self.patient = db, patient
        self.setWindowTitle("환자 정보 수정")
        form = QFormLayout()
        self.pid = QLineEdit(patient["patient_id"])
        self.name = QLineEdit(patient["name"] or "")
        self.birth = QLineEdit(patient["birth_date"] or "")
        self.birth.setPlaceholderText("YYYY-MM-DD")
        self.sex = _combo(SEXES, patient["sex"])
        self.note = QLineEdit(patient["note"] or "")
        for label, w in (("환자 ID", self.pid), ("이름", self.name), ("생년월일", self.birth),
                         ("성별", self.sex), ("메모", self.note)):
            form.addRow(label, w)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _accept(self) -> None:
        pid = self.pid.text().strip()
        if not pid:
            QMessageBox.warning(self, "환자 ID", "환자 ID는 비울 수 없습니다.")
            return
        birth = self.birth.text().strip()
        if birth and not norm_date(birth):
            QMessageBox.warning(self, "날짜 형식", "생년월일을 YYYY-MM-DD 형식으로 입력하세요.")
            return
        ref = self.patient["id"]
        other = self.db.find_patient(pid)
        if other is not None and other["id"] != ref:
            ok = QMessageBox.question(
                self, "환자 병합",
                f"환자 ID '{pid}' ({other['name'] or '이름 없음'})가 이미 있습니다.\n"
                f"이 환자의 영상을 모두 그 환자로 옮기고 합칠까요?")
            if ok != QMessageBox.StandardButton.Yes:
                return
            self.db.merge_patients(ref, other["id"])
            self.merged_into = other["id"]
            self.accept()
            return
        self.db.update_patient(ref, patient_id=pid, name=self.name.text().strip() or None,
                               birth_date=norm_date(birth) if birth else None,
                               sex=self.sex.currentData() or None, note=self.note.text().strip() or None)
        self.merged_into = None
        self.accept()


class SettingsDialog(QDialog):
    COLS = ("경로", "카메라 프로필", "하위 폴더", "처리 방식", "폴링(네트워크)", "사용")

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("설정")
        self.resize(900, 560)
        tabs = QTabWidget()

        # -- watch folders ------------------------------------------------------
        w1 = QWidget()
        l1 = QVBoxLayout(w1)
        l1.addWidget(QLabel("사진이 저장되는 폴더를 등록하면, 새 파일이 들어올 때 자동으로 가져옵니다.\n"
                            "APOLLO: 장비 공유 폴더(PatientCapture) 또는 MicroClearClient\\ImageData,  "
                            "VK-2: Export Tool 출력 폴더 / DICOM 저장 폴더."))
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        l1.addWidget(self.table)
        btns = QHBoxLayout()
        add = QPushButton("폴더 추가…")
        add.clicked.connect(self._add_folder)
        rem = QPushButton("선택 삭제")
        rem.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()))
        btns.addWidget(add)
        btns.addWidget(rem)
        btns.addStretch()
        l1.addLayout(btns)
        for f in settings.watch_folders:
            self._add_row(f)
        tabs.addTab(w1, "감시 폴더")

        # -- general ------------------------------------------------------------
        w2 = QWidget()
        f2 = QFormLayout(w2)
        lib = QHBoxLayout()
        self.library = QLineEdit(str(settings.library))
        b = QPushButton("찾아보기…")
        b.clicked.connect(self._pick_library)
        lib.addWidget(self.library)
        lib.addWidget(b)
        f2.addRow("라이브러리 폴더 (DB·사본)", lib)
        self.watch_start = QCheckBox("프로그램 시작 시 폴더 감시 시작")
        self.watch_start.setChecked(settings.watch_on_startup)
        f2.addRow("", self.watch_start)
        self.stable = QDoubleSpinBox()
        self.stable.setRange(0.2, 30)
        self.stable.setSuffix(" 초")
        self.stable.setValue(settings.stable_seconds)
        f2.addRow("파일 쓰기 완료 대기", self.stable)
        self.rescan = QSpinBox()
        self.rescan.setRange(0, 3600)
        self.rescan.setSuffix(" 초 (0 = 끔)")
        self.rescan.setValue(settings.rescan_seconds)
        f2.addRow("누락 확인 재검사 주기", self.rescan)
        self.opengl = _combo([("auto", "자동"), ("desktop", "그래픽카드 OpenGL"),
                              ("software", "소프트웨어 렌더링 (호환 모드)")], settings.opengl)
        f2.addRow("3D 렌더링 (재시작 필요)", self.opengl)
        tabs.addTab(w2, "일반")

        # -- filename rules -------------------------------------------------------
        w3 = QWidget()
        l3 = QVBoxLayout(w3)
        l3.addWidget(QLabel(
            "추가 파일명 규칙 (정규식, 한 줄에 하나). 이름 있는 그룹: "
            "pid name birth sex date time eye mode seq\n"
            "예) ^(?P<pid>\\d+)_(?P<name>[가-힣]+)_(?P<date>\\d{8})_(?P<eye>OD|OS)"))
        self.patterns = QPlainTextEdit("\n".join(settings.custom_filename_patterns))
        l3.addWidget(self.patterns)
        test = QHBoxLayout()
        self.test_name = QLineEdit()
        self.test_name.setPlaceholderText("파일 이름을 입력해 규칙 시험 (예: 12345_홍길동_20240305_OD.jpg)")
        self.test_profile = QComboBox()
        for key, p in PROFILES.items():
            self.test_profile.addItem(p.name, key)
        test.addWidget(self.test_name, 3)
        test.addWidget(self.test_profile, 2)
        l3.addLayout(test)
        self.test_out = QLabel()
        self.test_out.setWordWrap(True)
        self.test_out.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        l3.addWidget(self.test_out)
        for sig in (self.test_name.textChanged, self.patterns.textChanged, self.test_profile.currentIndexChanged):
            sig.connect(self._run_test)
        tabs.addTab(w3, "파일명 규칙")

        # -- profiles (read-only help) ---------------------------------------------
        w4 = QWidget()
        l4 = QVBoxLayout(w4)
        txt = QPlainTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText("\n\n".join(
            f"[{p.name}]\n  화각 {p.fov_deg:g}° ({'안구 중심각' if p.fov_type == 'internal' else '외부각(동공)'}), "
            f"투영: {p.projection}\n  {p.notes}" for p in PROFILES.values()))
        l4.addWidget(txt)
        tabs.addTab(w4, "카메라 프로필")

        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _add_row(self, f: WatchFolder) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(f.path))
        prof = QComboBox()
        prof.addItem("자동 감지", AUTO)
        for key, p in PROFILES.items():
            prof.addItem(p.name, key)
        prof.setCurrentIndex(max(prof.findData(f.profile), 0))
        self.table.setCellWidget(r, 1, prof)
        for col, val in ((2, f.recursive), (4, f.polling), (5, f.enabled)):
            cb = QCheckBox()
            cb.setChecked(val)
            self.table.setCellWidget(r, col, cb)
        act = QComboBox()
        for a in ACTIONS:
            act.addItem(ACTION_LABELS[a], a)
        act.setCurrentIndex(max(act.findData(f.action), 0))
        self.table.setCellWidget(r, 3, act)

    def _add_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "감시할 폴더 선택")
        if d:
            from ..watcher import is_network_path
            profile = "apollo" if "PatientCapture" in d or "MicroClear" in d else AUTO
            self._add_row(WatchFolder(path=d, profile=profile, polling=is_network_path(d)))

    def _pick_library(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "라이브러리 폴더 선택", self.library.text())
        if d:
            self.library.setText(d)

    def _run_test(self) -> None:
        name = self.test_name.text().strip()
        if not name:
            self.test_out.clear()
            return
        prof = get_profile(self.test_profile.currentData())
        pats = [p for p in self.patterns.toPlainText().splitlines() if p.strip()]
        meta = filename_meta(Path(name if "." in name else name + ".jpg"),
                             pats + list(prof.filename_patterns), id_only=prof.id_only_filenames)
        parts = [f"{FIELD_LABELS[k]}: <b>{getattr(meta, k)}</b>" for k in META_FIELDS if getattr(meta, k)]
        self.test_out.setText(" · ".join(parts) if parts else "<span style='color:#b44'>인식된 정보 없음</span>")

    def apply(self) -> None:
        s = self.settings
        folders = []
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if not item or not item.text().strip():
                continue
            folders.append(WatchFolder(
                path=item.text().strip(),
                profile=self.table.cellWidget(r, 1).currentData(),
                recursive=self.table.cellWidget(r, 2).isChecked(),
                action=self.table.cellWidget(r, 3).currentData(),
                polling=self.table.cellWidget(r, 4).isChecked(),
                enabled=self.table.cellWidget(r, 5).isChecked(),
            ))
        s.watch_folders = folders
        s.library_dir = self.library.text().strip()
        s.watch_on_startup = self.watch_start.isChecked()
        s.stable_seconds = self.stable.value()
        s.rescan_seconds = self.rescan.value()
        s.opengl = self.opengl.currentData()
        s.custom_filename_patterns = [p for p in self.patterns.toPlainText().splitlines() if p.strip()]
