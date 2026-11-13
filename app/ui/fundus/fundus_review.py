"""안저 검토 화면 — 불러온 안저 사진을 양안 / 이전·현재 비교 배치로 검토.

배치(단계)
  양안     왼쪽 뷰포트 = 우안(OD), 오른쪽 = 좌안(OS). 각 안구의 가장 최근 사진
  OD 비교  왼쪽 = 이전 검사, 오른쪽 = 현재(가장 최근) 검사.  [ / ] 로 이전 검사를 넘긴다
  OS 비교  위와 같음 (좌안). 비교 단계는 그 안구의 이전 검사가 있을 때만 쓸 수 있다
검사(세션) = 촬영 날짜. 같은 날 여러 장이면 가장 늦게 찍은 사진이 기본으로 뜬다.
기타: 확대·이동 연동, 보기(컬러 / 감각망막 / 맥락막), 확대창, 타임라인(클릭·끌어다 놓기).
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.ui import icons
from app.ui.fundus.magnifier import Magnifier
from app.ui.fundus.timeline import FundusTimeline
from app.ui.fundus.viewport import FundusViewport
from app.ui.theme import ICON, ICON_ON_ACCENT

STAGES = ("ou", "od", "os")
_STAGE_TEXT = {"ou": "양안 (OD | OS)", "od": "OD 비교* (이전 | 현재)", "os": "OS 비교* (이전 | 현재)"}
_STAGE_EYE = {"od": "OD", "os": "OS"}
_VIEWS = [("color", "컬러"), ("redfree", "감각망막 (적색 제거)"), ("choroid", "맥락막 (녹색 제거)")]
EMPTY_TEXT = "불러온 안저 사진이 없습니다"


def _day(cap) -> str:
    return (cap.captured_at or "")[:10]


class FundusReview(QWidget):
    importRequested = Signal()             # '안저 불러오기' 눌림
    openInProRequested = Signal(object)    # 활성 뷰포트의 Capture 를 Pro 1화면으로

    def __init__(self, db, config=None, parent=None):
        super().__init__(parent)
        self.setObjectName("FundusReview")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.db = db
        self.config = config
        self._patient = None
        self._caps: list = []              # 안저 사진, 최신 먼저
        self._stage = "ou"
        self._prior_idx = 0                # 비교 단계: 0 = 바로 이전 검사, 1 = 그 이전 …
        self._stale = False
        self._build()
        self._active = self.left
        self.left.set_active(True)
        self._shortcuts()
        self._refresh()

    # ================= UI =================
    def _btn(self, text, tip, checkable=False, obj="ProBtn", icon=None, color=ICON) -> QPushButton:
        b = QPushButton(icons.gap(text) if icon else text)
        b.setObjectName(obj)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setMinimumHeight(34)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if icon:
            ic = icons.icon(icon, color, 18, disabled="#4a5262")
            if checkable:
                ic.addPixmap(icons.pixmap(icon, ICON_ON_ACCENT, 18), ic.Mode.Normal, ic.State.On)
            b.setIcon(ic)
            b.setIconSize(QSize(15, 15))
        return b

    @staticmethod
    def _sep() -> QFrame:
        f = QFrame()
        f.setObjectName("ProSep")
        f.setFixedWidth(1)
        return f

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        bar = QFrame()
        bar.setObjectName("ProToolbar")
        tl = QHBoxLayout(bar)
        tl.setContentsMargins(8, 6, 8, 6)
        tl.setSpacing(4)

        self.b_prev = self._btn("◀ 이전", "이전 배치 (←)")
        self.b_next = self._btn("다음 ▶", "다음 배치 (→)")
        self.c_stage = QComboBox()
        for s in STAGES:
            self.c_stage.addItem(_STAGE_TEXT[s], s)
        self.c_stage.setToolTip("배치 — * 표시는 이전 검사와 비교하는 단계 (이전 검사가 있어야 선택 가능)")
        self.c_stage.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lbl_stage = QLabel("배치")
        lbl_stage.setObjectName("Muted")
        tl.addWidget(self.b_prev)
        tl.addWidget(self.b_next)
        tl.addSpacing(4)
        tl.addWidget(lbl_stage)
        tl.addWidget(self.c_stage)
        tl.addWidget(self._sep())

        self.b_fit = self._btn("맞춤", "화면에 맞춤 (더블클릭)", icon="fit")
        self.b_zin = self._btn("확대", "확대 (마우스 휠)", icon="zin")
        self.b_zout = self._btn("축소", "축소 (마우스 휠)", icon="zout")
        self.b_link = self._btn("연동", "두 뷰포트의 확대·이동을 함께 움직임", True, icon="compare")
        self.b_link.setChecked(True)
        for b in (self.b_fit, self.b_zin, self.b_zout, self.b_link):
            tl.addWidget(b)
        tl.addWidget(self._sep())

        self.c_view = QComboBox()
        for key, text in _VIEWS:
            self.c_view.addItem(text, key)
        self.c_view.setToolTip("보기 — 감각망막: 녹색 채널(적색 제거) · 맥락막: 적색 채널(녹색 제거)")
        self.c_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lbl_view = QLabel("보기")
        lbl_view.setObjectName("Muted")
        self.b_mag = self._btn("확대창", "확대창 켜기/끄기 (뷰포트에서 가운데 버튼 클릭)\n"
                                      "끌어서 이동 · 휠: 배율 · 오른쪽 클릭: 반대쪽 영상", True, icon="lens")
        tl.addWidget(lbl_view)
        tl.addWidget(self.c_view)
        tl.addWidget(self.b_mag)
        tl.addStretch(1)
        self.b_pro = self._btn("Pro에서 열기", "활성 뷰포트의 영상을 Pro 검토 1화면에서 열기 (보정·측정·인쇄)",
                               obj="ProGhost", icon="review")
        self.b_import = self._btn("안저 불러오기", "안저 사진(이미지·DICOM) 파일 불러오기",
                                  obj="ProPrimary", icon="download", color=ICON_ON_ACCENT)
        tl.addWidget(self.b_pro)
        tl.addWidget(self.b_import)
        root.addWidget(bar)

        # 가운데: 뷰포트 2개 (또는 빈 상태 안내)
        self.stack = QStackedWidget()
        self.stack.setObjectName("ProDisplay")
        empty = QWidget()
        el = QVBoxLayout(empty)
        el.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.setSpacing(12)
        self.lbl_empty = QLabel(EMPTY_TEXT)
        self.lbl_empty.setObjectName("FundusEmpty")
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty_sub = QLabel()
        self.lbl_empty_sub.setObjectName("Muted")
        self.lbl_empty_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.b_empty_import = QPushButton(icons.gap("안저 불러오기"))
        self.b_empty_import.setObjectName("Primary")
        self.b_empty_import.setIcon(icons.icon("download", ICON_ON_ACCENT, 18))
        self.b_empty_import.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        el.addWidget(self.lbl_empty)
        el.addWidget(self.lbl_empty_sub)
        el.addWidget(self.b_empty_import, 0, Qt.AlignmentFlag.AlignHCenter)

        self.area = QWidget()
        self.area.setObjectName("FundusArea")
        al = QHBoxLayout(self.area)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(4)
        self.left = FundusViewport()
        self.right = FundusViewport()
        al.addWidget(self.left, 1)
        al.addWidget(self.right, 1)
        self.magnifier = Magnifier(self.area, [self.left, self.right])
        self.stack.addWidget(empty)       # 0
        self.stack.addWidget(self.area)   # 1
        root.addWidget(self.stack, 1)

        self.timeline = FundusTimeline()
        root.addWidget(self.timeline)

        self.b_prev.clicked.connect(lambda: self.step_stage(-1))
        self.b_next.clicked.connect(lambda: self.step_stage(1))
        self.c_stage.activated.connect(lambda i: self.set_stage(STAGES[i]))
        self.b_fit.clicked.connect(self.fit)
        self.b_zin.clicked.connect(lambda: self.zoom(1.25))
        self.b_zout.clicked.connect(lambda: self.zoom(1 / 1.25))
        self.b_link.toggled.connect(self._on_link_toggled)
        self.c_view.currentIndexChanged.connect(lambda i: self.set_view_mode(_VIEWS[i][0]))
        self.b_mag.toggled.connect(self.set_magnifier_visible)
        self.b_pro.clicked.connect(self._open_in_pro)
        self.b_import.clicked.connect(self.importRequested.emit)
        self.b_empty_import.clicked.connect(self.importRequested.emit)
        self.timeline.captureClicked.connect(self.show_capture)
        self.magnifier.visibilityChanged.connect(self._on_magnifier_visibility)
        for vp in (self.left, self.right):
            vp.activated.connect(lambda vp=vp: self.set_active(vp))
            vp.viewChanged.connect(lambda vp=vp: self._on_view_changed(vp))
            vp.magnifierRequested.connect(lambda pos, vp=vp: self._on_magnifier_requested(vp, pos))
            vp.captureDropped.connect(lambda cid, vp=vp: self._on_dropped(vp, cid))
        self.left.priorStep.connect(self.scroll_prior)

    def _shortcuts(self) -> None:
        for key, fn in ((QKeySequence(Qt.Key.Key_Left), lambda: self.step_stage(-1)),
                        (QKeySequence(Qt.Key.Key_Right), lambda: self.step_stage(1)),
                        (QKeySequence(Qt.Key.Key_BracketLeft), lambda: self.scroll_prior(1)),
                        (QKeySequence(Qt.Key.Key_BracketRight), lambda: self.scroll_prior(-1))):
            sc = QShortcut(key, self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)

    # ================= 데이터 =================
    def set_patient(self, patient, reload: bool = True) -> None:
        """환자 변경. reload=False 면 화면이 보일 때(reload 호출) 영상을 읽는다."""
        self._patient = patient
        self._stage = "ou"
        self._prior_idx = 0
        if reload:
            self.reload()
        else:
            self._stale = True
            self._caps = []
            self._refresh()

    def patient(self):
        return self._patient

    def reload(self) -> None:
        """DB 에서 안저 사진 목록을 다시 읽고 현재 배치를 다시 그린다."""
        self._stale = False
        if self._patient is None:
            self._caps = []
        else:
            self._caps = [c for c in self.db.captures.list_by_patient(self._patient.id, order="desc",
                                                                       modality="fundus")
                          if c.media_type == "photo"]
        if not self.stage_enabled(self._stage):
            self._stage = "ou"
        self._prior_idx = min(self._prior_idx, max(0, self.prior_count() - 1))
        self._refresh()

    def reload_if_stale(self) -> None:
        if self._stale:
            self.reload()

    def captures(self) -> list:
        return list(self._caps)

    def sessions(self, eye: str | None = None) -> list[str]:
        """검사일 목록 (최신 먼저). eye 를 주면 그 안구 사진이 있는 날만."""
        days: list[str] = []
        for c in self._caps:
            d = _day(c)
            if (eye is None or c.eye == eye) and d not in days:
                days.append(d)
        return days

    def newest(self, eye: str, day: str | None = None):
        """그 안구의 가장 최근 사진 (day 를 주면 그 검사일 안에서)."""
        for c in self._caps:
            if c.eye == eye and (day is None or _day(c) == day):
                return c
        return None

    # ================= 배치(단계) =================
    def stage(self) -> str:
        return self._stage

    def stage_enabled(self, stage: str) -> bool:
        if stage == "ou":
            return True
        return len(self.sessions(_STAGE_EYE[stage])) >= 2

    def set_stage(self, stage: str) -> bool:
        if stage not in STAGES or not self.stage_enabled(stage):
            self._sync_stage_controls()
            return False
        self._stage = stage
        self._prior_idx = 0
        self._apply_stage()
        return True

    def step_stage(self, delta: int) -> None:
        avail = [s for s in STAGES if self.stage_enabled(s)]
        i = avail.index(self._stage) + (1 if delta > 0 else -1)
        if 0 <= i < len(avail):
            self.set_stage(avail[i])

    def prior_count(self) -> int:
        """현재 비교 단계에서 넘겨 볼 수 있는 이전 검사 수."""
        if self._stage == "ou":
            return 0
        return max(0, len(self.sessions(_STAGE_EYE[self._stage])) - 1)

    def prior_index(self) -> int:
        return self._prior_idx

    def scroll_prior(self, delta: int) -> None:
        """비교 단계의 왼쪽 뷰포트: delta>0 = 더 이전 검사, delta<0 = 더 최근 검사."""
        n = self.prior_count()
        if not n:
            return
        idx = min(max(0, self._prior_idx + (1 if delta > 0 else -1)), n - 1)
        if idx != self._prior_idx:
            self._prior_idx = idx
            self._apply_stage()

    def _refresh(self) -> None:
        has = bool(self._caps)
        self.stack.setCurrentIndex(1 if has else 0)
        self.lbl_empty_sub.setText("‘안저 불러오기’로 이미지·DICOM 파일을 가져오세요" if self._patient is not None
                                   else "환자를 먼저 선택하세요")
        for b in (self.b_import, self.b_empty_import):
            b.setEnabled(self._patient is not None)
        for w in (self.b_fit, self.b_zin, self.b_zout, self.b_link, self.c_view, self.b_mag, self.c_stage):
            w.setEnabled(has)
        if not has:
            self.magnifier.set_shown(False)
        self.timeline.set_captures(self._caps)
        self.timeline.setVisible(has)
        self._apply_stage()

    def _apply_stage(self) -> None:
        """현재 배치의 기본 영상을 두 뷰포트에 올린다."""
        newest_day = self.sessions()[0] if self._caps else ""
        if self._stage == "ou":
            for vp, eye in ((self.left, "OD"), (self.right, "OS")):
                cap = self.newest(eye)
                vp.set_placeholder(f"{eye} 영상 없음")
                self._load(vp, cap, "이전" if cap is not None and _day(cap) != newest_day else "")
            self.left.set_prior_nav(False)
        else:
            eye = _STAGE_EYE[self._stage]
            days = self.sessions(eye)
            priors = days[1:]
            k = min(self._prior_idx, len(priors) - 1)
            self.left.set_placeholder(f"{eye} 이전 영상 없음")
            self.right.set_placeholder(f"{eye} 영상 없음")
            tag = "이전" if len(priors) == 1 else f"이전 {k + 1}/{len(priors)}"
            self._load(self.left, self.newest(eye, priors[k]), tag)
            self._load(self.right, self.newest(eye, days[0]), "현재")
            self.left.set_prior_nav(True, can_older=k < len(priors) - 1, can_newer=k > 0)
        self._sync_stage_controls()
        self._sync_shown()

    def _load(self, vp: FundusViewport, cap, tag: str) -> None:
        cur = vp.capture()
        if cap is not None and cur is not None and cur.id == cap.id and vp.has_image():
            vp.set_tag(tag)                  # 같은 영상이면 파일을 다시 읽지 않는다
            vp.fit()
        else:
            vp.set_capture(cap, tag)

    def _sync_stage_controls(self) -> None:
        model = self.c_stage.model()
        for i, s in enumerate(STAGES):
            item = model.item(i)
            if item is not None:
                item.setEnabled(self.stage_enabled(s))
        blk = self.c_stage.blockSignals(True)
        self.c_stage.setCurrentIndex(STAGES.index(self._stage))
        self.c_stage.blockSignals(blk)
        avail = [s for s in STAGES if self.stage_enabled(s)]
        i = avail.index(self._stage)
        has = bool(self._caps)
        self.b_prev.setEnabled(has and i > 0)
        self.b_next.setEnabled(has and i < len(avail) - 1)
        self.b_pro.setEnabled(self._active.capture() is not None)

    def _sync_shown(self) -> None:
        self.timeline.set_shown_ids(vp.capture().id for vp in (self.left, self.right)
                                    if vp.capture() is not None)
        self.b_pro.setEnabled(self._active.capture() is not None)

    # ================= 뷰포트 =================
    def viewports(self) -> tuple:
        return self.left, self.right

    def active_viewport(self) -> FundusViewport:
        return self._active

    def set_active(self, vp: FundusViewport) -> None:
        self._active = vp
        for v in (self.left, self.right):
            v.set_active(v is vp)
        self.b_pro.setEnabled(vp.capture() is not None)

    def _other(self, vp: FundusViewport) -> FundusViewport:
        return self.right if vp is self.left else self.left

    def show_capture(self, cap, viewport: FundusViewport | None = None) -> None:
        """타임라인에서 고른 영상을 뷰포트에 올린다.

        viewport 를 주지 않으면: 양안 배치는 안구에 맞는 쪽(OD=왼쪽, OS=오른쪽, 미지정=활성),
        비교 배치는 활성 뷰포트.
        """
        if cap is None:
            return
        vp = viewport
        if vp is None:
            if self._stage == "ou" and cap.eye in ("OD", "OS"):
                vp = self.left if cap.eye == "OD" else self.right
            else:
                vp = self._active
        if self._stage == "ou":
            newest_day = self.sessions()[0]
            tag = "이전" if _day(cap) != newest_day else ""
        else:
            eye_days = self.sessions(cap.eye) or self.sessions()
            tag = "현재" if _day(cap) == eye_days[0] else "이전"
        vp.set_capture(cap, tag)
        if vp is self.left:
            self.left.set_prior_nav(self._stage != "ou", *self._prior_nav_state())
        other = self._other(vp)
        if self.linked() and other.has_image():
            vp.set_view_state(*other.view_state())
        self.set_active(vp)
        self._sync_shown()

    def _prior_nav_state(self) -> tuple[bool, bool]:
        n = self.prior_count()
        return self._prior_idx < n - 1, self._prior_idx > 0

    def _on_dropped(self, vp: FundusViewport, cid: int) -> None:
        cap = next((c for c in self._caps if c.id == cid), None)
        if cap is not None:
            self.show_capture(cap, vp)

    def linked(self) -> bool:
        return self.b_link.isChecked()

    def set_linked(self, on: bool) -> None:
        self.b_link.setChecked(on)

    def _on_link_toggled(self, on: bool) -> None:
        if on:
            self._on_view_changed(self._active)

    def _on_view_changed(self, vp: FundusViewport) -> None:
        other = self._other(vp)
        if self.linked() and vp.has_image() and other.has_image():
            other.set_view_state(*vp.view_state())

    def fit(self) -> None:
        for vp in ((self.left, self.right) if self.linked() else (self._active,)):
            vp.fit()

    def zoom(self, factor: float) -> None:
        self._active.zoom_by(factor)

    def view_mode(self) -> str:
        return self.left.view_mode()

    def set_view_mode(self, mode: str) -> None:
        idx = next((i for i, (k, _) in enumerate(_VIEWS) if k == mode), 0)
        blk = self.c_view.blockSignals(True)
        self.c_view.setCurrentIndex(idx)
        self.c_view.blockSignals(blk)
        for vp in (self.left, self.right):
            vp.set_view_mode(_VIEWS[idx][0])

    # ================= 확대창 =================
    def set_magnifier_visible(self, on: bool, center: QPoint | None = None) -> None:
        if on and self._caps:
            if center is None:
                center = self._active.geometry().center()
            self.magnifier.show_at(center)
        else:
            self.magnifier.set_shown(False)
            self._on_magnifier_visibility(False)

    def _on_magnifier_requested(self, vp: FundusViewport, pos: QPoint) -> None:
        if self.magnifier.is_shown():
            self.magnifier.set_shown(False)
        else:
            self.set_magnifier_visible(True, vp.mapTo(self.area, pos))

    def _on_magnifier_visibility(self, on: bool) -> None:
        blk = self.b_mag.blockSignals(True)
        self.b_mag.setChecked(on)
        self.b_mag.blockSignals(blk)

    # ================= 기타 =================
    def _open_in_pro(self) -> None:
        cap = self._active.capture()
        if cap is not None:
            self.openInProRequested.emit(cap)
