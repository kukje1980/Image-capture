"""녹내장 분석 → OD · OS 비교: this eye's disc and the fellow eye's — side by side, and over each other
(the fellow turned left ↔ right) by flicking or fading — with each eye's C/D and their difference
(fellow.py)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer

from .. import fellow as F
from .. import glaucoma as G
from . import theme
from .glaucoma_dialog import DiscTab, _Choice, _Slider, _Tab, _note
from .widgets import card

MODES = (("side", "나란히", "OD 왼쪽 · OS 오른쪽 — 찍은 그대로"),
         ("flick", "깜빡임", "반대쪽 눈을 좌우로 뒤집어 같은 자리에서 번갈아"),
         ("blend", "겹치기", "반대쪽 눈을 좌우로 뒤집어 반투명하게 겹쳐서"))
FLICK_MS = 700
NONE_TEXT = "반대쪽 눈의 유두 사진이 없습니다 — 두 눈을 모두 찍은 환자에서 비교할 수 있습니다"


class FellowTab(_Tab):
    def __init__(self, mine: DiscTab, fellow=None, parent=None, method: str = "hybrid"):
        """``mine``: the 디스크 C/D tab of the eye being analysed (its lines, as fitted or moved by hand);
        ``fellow``: the other eye's photo — a ``Photo``, or a function giving one (read when the tab is
        first shown), or None."""
        super().__init__(NONE_TEXT, parent)
        self.mine, self._fellow, self.method = mine, fellow, method
        self.other: DiscTab | None = None            # the fellow eye's own 디스크 C/D (not on screen)
        self._loaded = False
        self._flip = False                           # 깜빡임: the fellow is the one shown now
        self._pics = None                            # (mine, fellow as taken) of one size
        self.modes = _Choice(MODES)
        self.modes.changed.connect(lambda _k: self._mode_changed())
        self.s_blend = _Slider("겹치는 정도", 0, 100, 50, 5, lambda v: f"{v:.0f}%")
        self.s_blend.changed.connect(lambda _v: self._draw())
        self.side.addWidget(card("보기", self.modes, self.s_blend,
                                 _note("깜빡임 · 겹치기에서는 반대쪽 눈을 좌우로 뒤집어 코쪽이 같은 쪽에 오게 합니다.")))
        self.lbl = _note()
        self.lbl.setTextFormat(Qt.TextFormat.RichText)
        self.side.addWidget(card("두 눈의 C/D", self.lbl,
                                 _note("이 눈의 선은 디스크 C/D 탭에서 맞춘 그대로, 반대쪽 눈의 선은 자동 맞춤입니다 — "
                                       "반대쪽 눈을 고치려면 그 눈의 사진으로 녹내장 분석을 여세요. "
                                       f"수직 C/D 차이 {F.ASYMMETRY:.1f} 이상은 녹내장을 의심하는 단서 중 하나입니다 (참고용).")))
        self.side.addStretch(1)
        self._timer = QTimer(self)
        self._timer.setInterval(FLICK_MS)
        self._timer.timeout.connect(self._tick)
        self.s_blend.setVisible(False)

    # -- the fellow eye ---------------------------------------------------------------------------------
    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        photo = self._fellow() if callable(self._fellow) else self._fellow
        if photo is not None and self.mine.photo is not None and photo.eye == F.other_eye(self.mine.eye_key):
            self.other = DiscTab(photo, method=self.method)
            self.other.hide()

    def refresh(self) -> None:
        """Both discs as they are now (the lines of 디스크 C/D may have been moved)."""
        self._load()
        self._pics = None
        if self.other is None or self.mine.photo is None:
            self.view.set_rgb(None)
            self.lbl.setText(NONE_TEXT if self.mine.photo is not None else "")
            return
        if self.other.field != self.mine.field:
            self.other.set_field(self.mine.field)        # the same number of disc diameters in both
        a, b = self.mine.render(), self.other.render()
        self.other.letters = False                       # the one turned left ↔ right: no S · N · I · T on it
        try:
            plain = self.other.render()
        finally:
            self.other.letters = True
        if a is None or b is None or plain is None:
            self.view.set_rgb(None)
            return
        self._pics = (a, G.match_size(b, a))
        self._turned = F.mirrored(G.match_size(plain, a))
        self._report()
        self._draw()

    def cds(self) -> dict:
        """``{"OD": metrics | None, "OS": …}`` of the two discs."""
        out = {"OD": None, "OS": None}
        if self.mine.eye_key in out:
            out[self.mine.eye_key] = self.mine.metrics()
            if self.other is not None:
                out[F.other_eye(self.mine.eye_key)] = self.other.metrics()
        return out

    def _report(self) -> None:
        m = self.cds()

        def row(eye):
            x = m[eye]
            here = " <span style='color:%s'>(이 눈)</span>" % theme.TEXT3 if eye == self.mine.eye_key else ""
            if not x:
                return f"<tr><td><b>{eye}</b>{here}&nbsp;&nbsp;</td><td>–</td><td></td></tr>"
            return (f"<tr><td><b>{eye}</b>{here}&nbsp;&nbsp;</td><td>수직 <b>{x['vertical']:.2f}</b>&nbsp;&nbsp;</td>"
                    f"<td>면적 {x['area']:.2f}</td></tr>")
        diff, said = F.compare(*(m[e]["vertical"] if m[e] else None for e in ("OD", "OS")))
        text = f"<table>{row('OD')}{row('OS')}</table>"
        if diff is not None:
            color = theme.ORANGE if said else theme.GREEN
            word = f"차이 {F.ASYMMETRY:.1f} 이상 — 두 눈이 다릅니다" if said else "두 눈이 비슷합니다"
            text += f"<br>수직 C/D 차이 <b>{diff:.2f}</b> — <b style='color:{color}'>{word}</b>"
        self.lbl.setText(text)
        self.diff, self.flagged = diff, said

    # -- the picture --------------------------------------------------------------------------------------
    def _mode_changed(self) -> None:
        self.s_blend.setVisible(self.modes.key() == "blend")
        self._flip = False
        self._restart()
        self._draw()

    def _restart(self) -> None:
        on = self.modes.key() == "flick" and self._pics is not None and self.isVisible()
        if on and not self._timer.isActive():
            self._timer.start()
        elif not on:
            self._timer.stop()

    def _tick(self) -> None:
        self._flip = not self._flip
        self._draw()

    def compose(self):
        """The picture of the mode chosen (None: no fellow eye)."""
        if self._pics is None:
            return None
        a, b = self._pics
        mode = self.modes.key()
        if mode == "side":
            od, os_ = (a, b) if self.mine.eye_key == "OD" else (b, a)
            return F.side_by_side(od, os_)
        turned = self._turned
        if mode == "flick":
            return turned if self._flip else a
        return F.blend(a, turned, self.s_blend.value() / 100.0)

    def _draw(self) -> None:
        img = self.compose()
        self.view.set_rgb(img)
        if img is None:
            self.hint.setText("")
            return
        me, it = self.mine.eye_key, F.other_eye(self.mine.eye_key)
        mode = self.modes.key()
        if mode == "side":
            self.hint.setText("왼쪽 OD · 오른쪽 OS — 초록 선: 디스크, 노란 선: 컵")
        elif mode == "flick":
            self.hint.setText(f"지금: {it} (좌우 뒤집음)" if self._flip else f"지금: {me}")
        else:
            self.hint.setText(f"{me} 위에 {it}(좌우 뒤집음)를 {self.s_blend.value():.0f}% 겹침")

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.refresh()
        self._restart()

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self._timer.stop()

    # -- saving (환자 기록에 저장 · 파일 · 복사) ------------------------------------------------------------
    def render(self):
        return self.compose()

    def has_image(self) -> bool:
        return self._pics is not None

    def note(self) -> str:
        m = self.cds()
        bits = [f"{e} {m[e]['vertical']:.2f}" for e in ("OD", "OS") if m[e]]
        return "녹내장 분석 — OD · OS 비교" + (f" (수직 C/D {' · '.join(bits)})" if bits else "")

    def image_ids(self) -> list[int]:
        # (kept with the eye being analysed: a record of two eyes has no one eye to be filed under)
        return [self.mine.photo.image_id] if self.mine.photo is not None else []

    def eye(self) -> str | None:
        return self.mine.eye_key
