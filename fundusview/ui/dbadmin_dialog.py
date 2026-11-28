"""파일 → 데이터베이스 관리…: the backups of the library's database, its check-up, going back to a backup
(dbadmin.py does the work)."""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QVBoxLayout)

from .. import dbadmin
from . import theme


class DatabaseDialog(QDialog):
    def __init__(self, db, settings, parent=None):
        super().__init__(parent)
        self.db, self.settings = db, settings
        self.restore_asked = False                   # 되돌리기 was asked for: the program should start again
        self.setWindowTitle("데이터베이스 관리")
        self.setMinimumSize(620, 480)
        lay = QVBoxLayout(self)
        intro = QLabel("환자 목록과 사진 정보(환자 지정 · 유두 · 황반 위치 · 메모)는 데이터베이스 파일 하나에 들어 있습니다. "
                       "프로그램을 켜는 날마다 한 번 자동으로 백업하고, 최근 "
                       f"{dbadmin.KEEP}개를 보관합니다. 사진 파일 자체는 백업에 들어가지 않습니다.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.lbl_state = QLabel("")
        self.lbl_state.setWordWrap(True)
        self.lbl_state.setObjectName("dbState")
        lay.addWidget(self.lbl_state)
        row = QHBoxLayout()
        self.b_check = QPushButton("지금 점검")
        self.b_check.setToolTip("데이터베이스 파일이 온전한지, 사진 파일이 제자리에 있는지 확인합니다")
        self.b_check.clicked.connect(self.run_check)
        self.b_backup = QPushButton("지금 백업")
        self.b_backup.setObjectName("primary")
        self.b_backup.clicked.connect(self.run_backup)
        self.b_folder = QPushButton("백업 폴더 열기")
        self.b_folder.clicked.connect(self.open_folder)
        for b in (self.b_check, self.b_backup, self.b_folder):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(QLabel("백업 목록 (최근 것이 위)"))
        self.list = QListWidget()
        self.list.setObjectName("dbBackups")
        self.list.currentRowChanged.connect(lambda _r: self._sync())
        lay.addWidget(self.list, 1)
        self.lbl_note = QLabel("")
        self.lbl_note.setWordWrap(True)
        self.lbl_note.setStyleSheet(f"color:{theme.TEXT3}")
        lay.addWidget(self.lbl_note)
        row = QHBoxLayout()
        self.b_restore = QPushButton("고른 백업으로 되돌리기…")
        self.b_restore.setToolTip("프로그램을 다시 시작할 때 이 백업으로 되돌립니다 — 지금의 데이터베이스는 옆에 보관합니다")
        self.b_restore.clicked.connect(self.ask_restore)
        self.b_cancel = QPushButton("되돌리기 취소")
        self.b_cancel.clicked.connect(self.cancel_restore)
        close = QPushButton("닫기")
        close.clicked.connect(self.accept)
        row.addWidget(self.b_restore)
        row.addWidget(self.b_cancel)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        self.fill()
        self.run_check(files=False)

    @property
    def library(self):
        return self.settings.library

    def fill(self) -> None:
        self.backups = [dbadmin.describe(b) for b in dbadmin.list_backups(self.library)]
        self.list.clear()
        for b in self.backups:
            what = (f"환자 {b.patients}명 · 사진 {b.images}장" if b.patients is not None else "읽을 수 없음")
            QListWidgetItem(f"{b.label}    {what}", self.list)
        if self.backups:
            self.list.setCurrentRow(0)
        self._sync()

    def _sync(self) -> None:
        b = self.current()
        self.b_restore.setEnabled(b is not None and b.patients is not None)
        wanted = dbadmin.pending_restore(self.library)
        self.b_cancel.setVisible(wanted is not None)
        if wanted is not None:
            self.lbl_note.setText(f"다음에 프로그램을 시작할 때 백업 「{wanted.name}」으로 되돌립니다.")
        elif not self.backups:
            self.lbl_note.setText("아직 백업이 없습니다 — [지금 백업]을 누르세요.")
        else:
            self.lbl_note.setText("")

    def current(self):
        r = self.list.currentRow()
        return self.backups[r] if 0 <= r < len(self.backups) else None

    def run_check(self, files: bool = True) -> dbadmin.Report:
        rep = dbadmin.check(self.db, files=bool(files))
        color = theme.GREEN if rep.ok else theme.ORANGE
        head = "이상 없음" if rep.ok else "확인이 필요합니다"
        self.lbl_state.setText(f"<b style='color:{color}'>{head}</b><br>" + "<br>".join(rep.lines()))
        self.report = rep
        return rep

    def run_backup(self) -> None:
        try:
            b = dbadmin.backup(self.db, self.library)
        except Exception as exc:
            QMessageBox.warning(self, "백업", f"백업하지 못했습니다.\n{exc}")
            return
        self.fill()
        self.lbl_note.setText(f"백업했습니다: {b.path.name}")

    def open_folder(self) -> None:
        folder = dbadmin.backup_dir(self.library)
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def ask_restore(self) -> None:
        b = self.current()
        if b is None:
            return
        ok = QMessageBox.question(
            self, "백업으로 되돌리기",
            f"{b.label}의 백업(환자 {b.patients}명 · 사진 {b.images}장)으로 되돌릴까요?\n\n"
            "그 뒤에 가져온 사진과 고친 환자 정보는 목록에서 사라집니다 (사진 파일은 그대로 남습니다).\n"
            "지금의 데이터베이스는 지우지 않고 옆에 보관합니다.\n프로그램을 다시 시작하면 적용됩니다.")
        if ok != QMessageBox.StandardButton.Yes:
            return
        try:
            dbadmin.backup(self.db, self.library)          # (what there is now, among the backups too)
            dbadmin.request_restore(self.library, b.path)
        except Exception as exc:
            QMessageBox.warning(self, "백업으로 되돌리기", f"되돌리기를 준비하지 못했습니다.\n{exc}")
            return
        self.restore_asked = True
        self.fill()

    def cancel_restore(self) -> None:
        dbadmin.cancel_restore(self.library)
        self.restore_asked = False
        self._sync()
