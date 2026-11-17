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
from . import theme

SOURCE_LABELS = {
    "dicom": "DICOM", "reticam": "RetiCam 데이터", "apollo": "APOLLO 데이터", "apollo-json": "APOLLO 환자 파일", "folder": "폴더 이름",
    "filename": "파일 이름", "exif": "EXIF", "jpeg-comment": "JPEG 주석", "png-text": "PNG 텍스트",
    "xmp": "XMP", "profile": "프로필 기본값", "file-time": "파일 시각", "disc-estimate": "시신경 위치로 추정", "fovea-estimate": "황반 위치로 추정",
    "manual": "직접 입력", "user": "가져올 때 직접 지정",
}
EYES = [("", "-"), ("OD", "OD (우안)"), ("OS", "OS (좌안)"), ("OU", "OU (양안)")]
SEXES = [("", "-"), ("M", "남"), ("F", "여"), ("O", "기타")]
ACTION_LABELS = {"copy": "복사 (원본 유지)", "move": "이동", "reference": "원본 위치 참조"}


def source_label(src: str | None) -> str:
    if not src:
        return ""
    return SOURCE_LABELS.get(src, src.replace("sidecar", "부속 파일 "))


# 설정 → 일반 → 환자를 열면 (Settings.open_view)
OPEN_VIEWS = (("odos", "Simple — 최신 OD | OS 두 장을 나란히, 사진 목록을 클릭하면 더하기 · 빼기"),
              ("grid", "Multi — 사진 16장을 한 화면에 (VK-2 방식), 골라서 [고른 사진 보기]로 모아 보기"))


# 3D 안구의 마우스 휠 (Settings.wheel3d): (key, short name, what it does)
WHEEL3D = (("zoom", "확대", "커서가 가리키는 곳으로 확대 · 축소 (깊이는 3D 화면 오른쪽의 깊이 막대로)"),
           ("depth", "깊이", "자르는 깊이 — 앞으로 굴리면 깊게, 뒤로 굴리면 닫힘 (내부에서는 확대)"),
           ("walk", "들어가기", "각막 → 앞방 → 동공 → 수정체 → 유리체 → 망막, 뒤로 굴리면 나오기"))


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
        hint.setStyleSheet(f"color:{theme.TEXT3}")
        lay.addWidget(hint)
        lay.addLayout(form)
        orig = QLabel(f"원본: {image['original_path'] or ''}")
        orig.setWordWrap(True)
        orig.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        orig.setStyleSheet(f"color:{theme.TEXT3}; font-size:11px")
        lay.addWidget(orig)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")     # the blue button
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("확인")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
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
        bb.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")     # the blue button
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("확인")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
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
                            "RetiCam: 장비 PC의 저장 폴더(예: \\\\장비IP\\D\\reticam, 네트워크면 '폴링' 체크),  "
                            "APOLLO: PatientCapture,  VK-2: Export Tool / DICOM 폴더."))
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
        self.watch_start = QCheckBox("프로그램 시작 시 폴더 감시 시작 (자동 가져오기)")
        self.watch_start.setChecked(settings.watch_on_startup)
        f2.addRow("", self.watch_start)
        self.auto_detect = QCheckBox("장비 폴더 자동 찾기 (RetiCam: reticam·레티캠, APOLLO: MicroClearClient)")
        self.auto_detect.setChecked(settings.auto_detect)
        f2.addRow("", self.auto_detect)
        inbox = QHBoxLayout()
        self.inbox = QLineEdit(str(settings.inbox))
        b2 = QPushButton("찾아보기…")
        b2.clicked.connect(lambda: self._pick_dir(self.inbox, "가져오기 폴더 선택"))
        inbox.addWidget(self.inbox)
        inbox.addWidget(b2)
        f2.addRow("가져오기 폴더 (넣으면 자동으로 가져옴)", inbox)
        self.redetect = False
        b3 = QPushButton("지금 장비 폴더 다시 찾기")
        b3.clicked.connect(self._redetect)
        f2.addRow("", b3)
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
        self.wheel3d = _combo([(k, f"{name} — {what}") for k, name, what in WHEEL3D], settings.wheel3d)
        self.wheel3d.setToolTip("3D 안구 위에서 마우스 휠이 하는 일 (3D 탭의 설정 → 마우스 휠에서도 바꿉니다)\n"
                                "어느 것이든 Ctrl+휠 · 확대 바 · 오른쪽 드래그 · + / − 는 확대입니다")
        f2.addRow("3D 마우스 휠", self.wheel3d)
        self.walk_click3d = QCheckBox("각막을 누르면 그동안 휠로 들어가기 (휠이 깊이 · 확대일 때)")
        self.walk_click3d.setToolTip("3D 안구의 각막을 누르면 전안부가 선택되고, 선택한 동안에는 휠이 각막부터 망막까지 "
                                     "들어가기 · 나오기가 됩니다 (Esc · 다른 곳을 누르면 해제)")
        self.walk_click3d.setChecked(bool(settings.walk_click3d))
        f2.addRow("", self.walk_click3d)
        self.wheel3d.currentIndexChanged.connect(          # (들어가기: the wheel goes in anyway)
            lambda _: self.walk_click3d.setEnabled(self.wheel3d.currentData() != "walk"))
        self.walk_click3d.setEnabled(self.wheel3d.currentData() != "walk")
        self.open_view = _combo(OPEN_VIEWS, settings.open_view)
        self.open_view.setToolTip("환자 목록에서 환자를 열 때 처음 나오는 화면\n"
                                  "Simple: 고른 검사의 최신 OD(왼쪽) · OS(오른쪽) 두 장 — 사진 목록을 클릭하면 그 사진을\n"
                                  "더하고(번호) 다시 클릭하면 빼며, 고른 장수에 맞게 화면이 나뉩니다.\n"
                                  "Multi (VK-2 방식): 사진 16장을 한 화면에 — 클릭해 고르고(번호) [고른 사진 보기]를 누르면\n"
                                  "고른 사진만 모아 봅니다. 더블클릭하면 그 사진을 크게 봅니다(Detail).\n"
                                  "어느 쪽이든 왼쪽 툴바의 [Simple] · [Multi]로 바꿀 수 있습니다.")
        f2.addRow("환자를 열면", self.open_view)
        # what is written on the photos of the photo list (also 보기 → 사진 목록 표시)
        self.thumb_date = QCheckBox("날짜")
        self.thumb_date.setChecked(bool(settings.thumb_date))
        self.thumb_kind = QCheckBox("종류 (컬러 · 몽타주 …)")
        self.thumb_kind.setChecked(bool(settings.thumb_kind))
        thumb_row = QHBoxLayout()
        thumb_row.addWidget(self.thumb_date)
        thumb_row.addWidget(self.thumb_kind)
        thumb_row.addStretch(1)
        f2.addRow("사진 목록의 사진 위에 표시", thumb_row)
        tabs.addTab(w2, "일반")

        # -- sharing (share.py) -----------------------------------------------------
        from .. import share
        w5 = QWidget()
        f5 = QFormLayout(w5)
        self.share_mode = _combo([
            (share.MODE_OFF, "이 컴퓨터에서만 사용"),
            (share.MODE_SERVER, "서버 — 이 컴퓨터의 자료를 다른 컴퓨터와 함께 사용"),
            (share.MODE_CLIENT, "서버에 연결 — 서버 컴퓨터의 자료를 사용")], settings.share_mode)
        f5.addRow("함께 쓰기", self.share_mode)
        self.share_port = QSpinBox()
        self.share_port.setRange(1024, 65535)
        self.share_port.setValue(settings.share_port)
        f5.addRow("포트 (서버)", self.share_port)
        self.server_url = QLineEdit(settings.server_url)
        self.server_url.setPlaceholderText(f"서버 컴퓨터의 주소 — 예: 192.168.0.10:{share.DEFAULT_PORT}")
        f5.addRow("서버 주소 (연결)", self.server_url)
        self.share_key = QLineEdit(settings.share_key)
        self.share_key.setPlaceholderText("서버: 비워 두면 자동으로 만듭니다 · 연결: 서버의 접속 암호")
        f5.addRow("접속 암호", self.share_key)
        self.share_test = QPushButton("연결 시험")
        self.share_test.clicked.connect(self._test_share)
        f5.addRow("", self.share_test)
        self.share_info = QLabel()
        self.share_info.setWordWrap(True)
        self.share_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        f5.addRow("", self.share_info)
        self.share_mode.currentIndexChanged.connect(self._share_changed)
        self._share_changed()
        tabs.addTab(w5, "공유")

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
        bb.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")     # the blue button
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("확인")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
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
            low = d.lower()
            profile = ("reticam" if "reticam" in low or "레티캠" in d else
                       "apollo" if "patientcapture" in low or "microclear" in low else AUTO)
            self._add_row(WatchFolder(path=d, profile=profile, polling=is_network_path(d)))

    def _pick_dir(self, edit: QLineEdit, title: str) -> None:
        d = QFileDialog.getExistingDirectory(self, title, edit.text())
        if d:
            edit.setText(d)

    def _redetect(self) -> None:
        """Forget removed auto folders and look again when OK is pressed."""
        self.settings.ignored_auto_folders = []
        self.redetect = True
        QMessageBox.information(self, "장비 폴더", "확인을 누르면 장비 폴더를 다시 찾아 감시 목록에 추가합니다.")

    def accept(self) -> None:
        from .. import autosetup
        msg = autosetup.inbox_problem(self.inbox.text(), self.library.text() or str(self.settings.library))
        if msg:
            QMessageBox.warning(self, "가져오기 폴더", msg)
            self.inbox.setFocus()
            return
        super().accept()

    def _share_changed(self) -> None:
        from .. import share
        mode = self.share_mode.currentData()
        self.share_port.setEnabled(mode == share.MODE_SERVER)
        self.server_url.setEnabled(mode == share.MODE_CLIENT)
        self.share_key.setEnabled(mode != share.MODE_OFF)
        self.share_test.setVisible(mode == share.MODE_CLIENT)
        if mode == share.MODE_SERVER:
            addr = f"{share.lan_address()}:{self.share_port.value()}"
            text = (f"사진과 데이터베이스는 이 컴퓨터에만 저장됩니다. 다른 컴퓨터는\n"
                    f" · 뷰어: 설정 → 공유 → '서버에 연결', 서버 주소 <b>{addr}</b>\n"
                    f" · 웹 브라우저: 주소창에 <b>http://{addr}</b> (보기 · 메모 · 환자 정보)\n"
                    "로 접속합니다. 이 컴퓨터의 뷰어가 켜져 있는 동안 접속할 수 있습니다.\n"
                    "처음 켤 때 Windows 방화벽이 물으면 '액세스 허용'을 누르세요. 병원 안 네트워크에서만 쓰세요.")
        elif mode == share.MODE_CLIENT:
            text = ("이 컴퓨터는 서버 컴퓨터의 환자와 사진을 보여 줍니다. 편집한 내용(환자 정보 · 메모 · 몽타주 …)은\n"
                    "서버에 저장되고, 사진 자동 가져오기는 서버 컴퓨터가 합니다. 이 컴퓨터의 감시 폴더 · 라이브러리\n"
                    "설정은 쓰이지 않습니다. 바꾼 뒤 프로그램을 다시 시작하면 적용됩니다.")
        else:
            text = "환자와 사진을 이 컴퓨터에서만 봅니다."
        self.share_info.setText(text.replace("\n", "<br>"))

    def _test_share(self) -> None:
        from .. import share
        url = share.normalize_url(self.server_url.text())
        if not url:
            self.share_info.setText("서버 주소를 입력하세요 (예: 192.168.0.10:8765).")
            return
        remote = share.RemoteDatabase(url, self.share_key.text().strip(), timeout=5)
        try:
            info = remote.ping()
            self.share_info.setText(f"<span style='color:#34d399'>연결되었습니다</span> — {url} (버전 {info.get('version', '?')})")
        except share.ShareError as exc:
            self.share_info.setText(f"<span style='color:#ff6961'>연결하지 못했습니다</span> — {exc}")
        finally:
            remote.close()

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
        self.test_out.setText(" · ".join(parts) if parts else "<span style='color:#ff6961'>인식된 정보 없음</span>")

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
        s.auto_detect = self.auto_detect.isChecked()
        s.inbox_dir = self.inbox.text().strip()
        s.stable_seconds = self.stable.value()
        s.rescan_seconds = self.rescan.value()
        s.opengl = self.opengl.currentData()
        s.wheel3d = self.wheel3d.currentData()
        s.walk_click3d = self.walk_click3d.isChecked()
        s.open_view = self.open_view.currentData()
        s.thumb_date = self.thumb_date.isChecked()
        s.thumb_kind = self.thumb_kind.isChecked()
        s.custom_filename_patterns = [p for p in self.patterns.toPlainText().splitlines() if p.strip()]
        from .. import share
        s.share_mode = self.share_mode.currentData()
        s.share_port = self.share_port.value()
        s.server_url = share.normalize_url(self.server_url.text())
        s.share_key = self.share_key.text().strip()
        if s.share_mode == share.MODE_SERVER and not s.share_key:
            s.share_key = share.new_key()
        if s.share_mode == share.MODE_CLIENT and not s.server_url:
            s.share_mode = share.MODE_OFF
