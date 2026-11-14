"""슬릿 스캔: the wide-field photo next to the 3D eye, and the scan animation.

``ScanPhotoView`` shows the photo flat (black outside the image circle, so the
name / ID the device burns into a corner stays hidden) with a slit that crosses
the field — down, up, right or left: behind it the photo is "scanned"
(bright), ahead of it dark.

``SlitScanShow`` plays the presentation on an ``EyeView`` and a
``ScanPhotoView`` together. Down and up (``SLIT``) play on 세로 단면:

1. the eye turns to the side and is cut in half along the photo's vertical
   meridian (세로 단면);
2. the field of view opens as two rays from the eye centre, with the angle;
3. the slit runs down (or up) the photo while its beam goes through the pupil
   to the same place on the retina (the not yet scanned retina is dark);
4. the eye turns to an oblique view from the front while the cut moves out to
   show the macula and the disc inside, and the outer coats turn see-through
   (망막 투시) — the photo is on the retina, seen from inside and outside;
5. the eye keeps turning slowly until the user takes over.

Right and left play on the eye opened at the front, seen from the front: the
slit sweeps over the retina as over the flat photo. 상하좌우 (``"all"``) plays
the four in turn; between down/up and right/left the section closes while the
front opens.

The timeline is a pure function of time (``frame``), so it is tested without
OpenGL.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from .. import imaging


def ease(x: float) -> float:
    """Smoothstep on [0, 1] (clamped)."""
    t = min(1.0, max(0.0, x))
    return t * t * (3.0 - 2.0 * t)


def ramp(t: float, t0: float, t1: float) -> float:
    """0 before ``t0``, 1 after ``t1``, eased in between."""
    return ease((t - t0) / (t1 - t0))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_angle(a: float, b: float, t: float) -> float:
    """Degrees, the short way round."""
    d = (b - a + 180.0) % 360.0 - 180.0
    return a + d * t


def lerp_pose(p0: dict, p1: dict, t: float) -> dict:
    return {"yaw": lerp_angle(p0["yaw"], p1["yaw"], t) % 360.0,
            "pitch": lerp(p0["pitch"], p1["pitch"], t),
            "dist": lerp(p0["dist"], p1["dist"], t),
            "target": tuple(lerp(a, b, t) for a, b in zip(p0["target"], p1["target"]))}


# -- the flat photo ---------------------------------------------------------------
class ScanPhotoView(QWidget):
    """The photo, flat, with the slit of a scan (black background like the 3D presentation)."""

    MAX_SIDE = 1600          # painted every frame while scanning: keep it light

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(160, 120)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._pix: QPixmap | None = None
        self._rows = (0.0, 1.0)          # top and bottom of the image circle in the pixmap (px)
        self._centre = (0.5, 0.5)        # the image circle's centre in the pixmap (px)
        self.scan: float | None = None   # 0 … 1 of the slit's way
        self.dim = 1.0                   # darkness of the part not scanned yet (0 … 1)
        self.direction = (0.0, 1.0)      # the slit's way over the photo (x right, y down)
        self.hint = ""                   # small grey text in the corner (full screen)

    def has_image(self) -> bool:
        return self._pix is not None

    def set_image(self, rgb: np.ndarray | None, alpha: np.ndarray | None = None,
                  circle: tuple[float, float, float] | None = None) -> None:
        if rgb is None:
            self._pix = None
            self.update()
            return
        h, w = rgb.shape[:2]
        cx, cy, r = circle or (w / 2.0, h / 2.0, min(w, h) / 2.0)
        x0, x1 = max(0, int(math.floor(cx - r))), min(w, int(math.ceil(cx + r)))
        y0, y1 = max(0, int(math.floor(cy - r))), min(h, int(math.ceil(cy + r)))
        if x1 - x0 < 2 or y1 - y0 < 2:
            x0, x1, y0, y1 = 0, w, 0, h
        # shrink first, then mask: a 24-megapixel photo is ready in a few ms instead of half a second
        crop = np.ascontiguousarray(rgb[y0:y1, x0:x1, :3])
        mask = np.ascontiguousarray(alpha[y0:y1, x0:x1]) if alpha is not None else None
        s = min(1.0, self.MAX_SIDE / max(crop.shape[:2]))
        if s < 1.0:
            crop = imaging.shrink(crop, s)
            mask = imaging.shrink(mask, s, like=crop) if mask is not None else None
        if mask is not None:              # black outside the field (hides text burned into the corners)
            crop = (crop.astype(np.uint16) * mask.astype(np.uint16)[..., None] // 255).astype(np.uint8)
        data = np.ascontiguousarray(crop)
        qimg = QImage(data.data, data.shape[1], data.shape[0], 3 * data.shape[1],
                      QImage.Format.Format_RGB888).copy()
        self._pix = QPixmap.fromImage(qimg)
        k = data.shape[0] / float(y1 - y0)
        self._rows = ((cy - r - y0) * k, (cy + r - y0) * k)
        self._centre = ((cx - x0) * k, (cy - y0) * k)
        self.update()

    def set_scan(self, s: float | None, dim: float = 1.0, direction=(0.0, 1.0)) -> None:
        self.scan, self.dim, self.direction = s, dim, (float(direction[0]), float(direction[1]))
        self.update()

    def image_rect(self) -> QRectF:
        """Where the photo is drawn (fitted, centred, a small margin)."""
        if self._pix is None:
            return QRectF()
        m = 0.04 * min(self.width(), self.height())
        aw, ah = max(1.0, self.width() - 2 * m), max(1.0, self.height() - 2 * m)
        k = min(aw / self._pix.width(), ah / self._pix.height())
        w, h = self._pix.width() * k, self._pix.height() * k
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def slit_y(self, s: float) -> float:
        """Widget y of the slit at ``s`` (0 top … 1 bottom of the image circle)."""
        rect = self.image_rect()
        k = rect.height() / max(1, self._pix.height()) if self._pix is not None else 1.0
        return rect.top() + (self._rows[0] + (self._rows[1] - self._rows[0]) * s) * k

    def slit_point(self, s: float) -> QPointF:
        """A point of the slit at ``s`` (0 … 1 of its way, along ``direction``) — on the line through
        the circle's centre along the way."""
        rect = self.image_rect()
        k = rect.height() / max(1, self._pix.height()) if self._pix is not None else 1.0
        R = (self._rows[1] - self._rows[0]) / 2.0 * k
        c = QPointF(rect.left() + self._centre[0] * k, rect.top() + self._centre[1] * k)
        w = (2.0 * s - 1.0) * R
        return QPointF(c.x() + self.direction[0] * w, c.y() + self.direction[1] * w)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.GlobalColor.black)
        if self._pix is None:
            p.setPen(QColor(150, 150, 150))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "사진 없음")
            p.end()
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.image_rect()
        p.drawPixmap(rect, self._pix, QRectF(self._pix.rect()))
        if self.scan is not None and self.dim > 0.0:
            # drawn turned so that the slit moves down the page (``direction``: its way on the photo)
            pt = self.slit_point(min(1.0, max(0.0, self.scan)))
            big = 2.0 * math.hypot(self.width(), self.height())
            hgt = rect.height() * 0.05
            p.save()
            p.setClipRect(rect)
            p.translate(pt)
            p.rotate(math.degrees(math.atan2(-self.direction[0], self.direction[1])))
            p.fillRect(QRectF(-big, 0.0, 2 * big, big), QColor(0, 0, 0, int(190 * self.dim)))
            # a soft afterglow just behind the slit, then the slit itself
            glow = QLinearGradient(0.0, -hgt, 0.0, 0.0)
            glow.setColorAt(0.0, QColor(255, 110, 50, 0))
            glow.setColorAt(1.0, QColor(255, 110, 50, int(70 * self.dim)))
            p.fillRect(QRectF(-big, -hgt, 2 * big, hgt), glow)
            lw = max(1.5, rect.height() / 260.0)
            for wmul, color in ((6.0, QColor(255, 80, 30, 45)), (3.0, QColor(255, 95, 40, 110)),
                                (1.4, QColor(255, 120, 60, 235)), (0.5, QColor(255, 225, 190, 255))):
                c = QColor(color)
                c.setAlpha(int(c.alpha() * self.dim))
                p.setPen(QPen(c, lw * wmul, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
                p.drawLine(QPointF(-big, 0.0), QPointF(big, 0.0))
            p.restore()
        if self.hint:
            p.setPen(QColor(120, 120, 120))
            p.drawText(self.rect().adjusted(8, 8, -10, -8),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, self.hint)
        p.end()


# -- the presentation ---------------------------------------------------------------
@dataclass(frozen=True)
class Slit:
    """One way of the slit over the photo, and where it is shown."""
    axis: str                    # "v": along the photo's vertical axis, "h": its horizontal one
    sign: float                  # "v": -1 down, +1 up; "h": +1 to the right, -1 to the left
    stage: str                   # "section": 세로 단면 from the side; "front": the eye opened at the front
    name: str


SLIT = {"down": Slit("v", -1.0, "section", "위에서 아래로"),
        "up": Slit("v", 1.0, "section", "아래에서 위로"),
        "right": Slit("h", 1.0, "front", "왼쪽에서 오른쪽으로"),
        "left": Slit("h", -1.0, "front", "오른쪽에서 왼쪽으로")}
SLIT_ALL = ("down", "up", "right", "left")
FRONT_CUT = 0.25                 # the front opening for the right / left passes


@dataclass
class Frame:
    """Everything the presentation sets at one moment."""
    pose: dict
    half: float
    xray: float
    scan: float | None
    scan_dim: float
    scan_beam: float
    fov_sweep: float
    fov_alpha: float
    fov_ring: float
    phase: str
    cut: float = 1.0
    slit: Slit = SLIT["down"]


class SlitScanShow(QObject):
    """Plays the slit-scan presentation on an ``EyeView`` and a ``ScanPhotoView``."""

    finished = Signal()          # the timeline is over (the eye keeps turning)
    stopped = Signal()           # the user took over, or stop() was called
    passChanged = Signal(str)    # the way of the slit now shown (its name), "" when none

    # phase boundaries (seconds)
    T_SIDE = 1.6                 # turned to the first stage (the side and cut in half, or the front opened)
    T_FOV = (1.6, 3.4)           # field of view opens
    SCAN = 5.2                   # one pass of the slit
    SCAN_ALL = 4.2               # … each of the four (상하좌우)
    GAP = 0.6                    # between two passes on the same stage
    SWITCH = 2.8                 # between 세로 단면 and the front: the section closes, the front opens
    DONE = 0.5                   # all scanned
    TURN = 3.3                   # to the oblique 3D view
    END_HALF = 0.62              # the section plane at the end: 40 % of the radius off the axis
    SPIN_RATE = 14.0             # °/s afterwards

    def __init__(self, eye, photo: ScanPhotoView | None = None, parent=None):
        super().__init__(parent)
        self.eye, self.photo = eye, photo
        self._timer = QTimer(self, interval=16, timeout=self._tick)
        self._t0 = 0.0
        self._start_pose: dict = {}
        self._start_half = self._start_xray = 0.0
        self._start_cut = 1.0
        self._at: dict = {}
        self._end: dict = {}
        self._segs: list = []
        self._last = SLIT["down"]
        self.T_SCAN = (self.T_FOV[1], self.T_FOV[1] + self.SCAN)
        self.T_DONE = self.T_SCAN[1] + self.DONE
        self.T_TURN = (self.T_DONE, self.T_DONE + self.TURN)
        self.direction = "down"         # "down", "up", "right", "left" or "all" (상하좌우)
        self.show_fov = False           # 화각 표시: the field stays marked after the show
        self.xray_after = False         # 망막 투시 as the viewer had it (restored when stopped early)
        self.playing = False            # the timeline runs (False while only spinning)
        self._name = ""
        eye.interacted.connect(self._on_user)

    @property
    def total(self) -> float:
        return self.T_TURN[1]

    def passes(self) -> tuple:
        return SLIT_ALL if self.direction == "all" else (self.direction,)

    def first(self) -> Slit:
        return SLIT[self.passes()[0]]

    def active(self) -> bool:
        return self._timer.isActive()

    def start(self) -> None:
        eye = self.eye
        eye.stop_motion()                     # a flick, a glide or 들어가며 보기 in progress ends here
        eye.journey_end()
        eye.mode, eye.dark, eye.out_fov = "outside", 0.0, 38.0
        self._start_pose = eye.pose()
        self._start_half, self._start_xray, self._start_cut = eye.half, eye.xray, eye.cut
        passes = self.passes()
        first = SLIT[passes[0]]
        eye.slit_axis, eye.scan_sign = first.axis, first.sign
        # the timeline: to the first stage, the field of view, the passes, the turn to the showcase
        segs, dur, t = [], (self.SCAN_ALL if len(passes) > 1 else self.SCAN), self.T_FOV[1]
        for i, key in enumerate(passes):
            if i > 0:
                prev, cur = SLIT[passes[i - 1]], SLIT[key]
                same = prev.stage == cur.stage
                d = self.GAP if same else self.SWITCH
                segs.append(("gap" if same else "switch", t, t + d, prev, cur))
                t += d
            segs.append(("scan", t, t + dur, SLIT[key], i == 0))
            t += dur
        self._segs, self._last = segs, SLIT[passes[-1]]
        self.T_SCAN = (self.T_FOV[1], t)
        self.T_DONE = t + self.DONE
        self.T_TURN = (self.T_DONE, self.T_DONE + self.TURN)
        front = dict(eye.HOME, yaw=0.0, pitch=0.0, dist=eye._fit(eye.DIST0, 1.15))
        self._at = {"section": (eye.section_pose(), 1.0, 1.0), "front": (front, 0.0, FRONT_CUT)}
        self._end = ((eye.showcase_pose(), self.END_HALF, 1.0, 1.0) if self._last.stage == "section"
                     else (dict(eye.HOME), 0.0, FRONT_CUT, 0.0))
        self._t0 = time.monotonic()
        self.playing = True
        self._apply(self.frame(0.0))
        self._timer.start()

    def stop(self) -> None:
        """Stop where it is, leaving a clean state: 세로 단면 cut through the axis (or the front opened)
        before the turn, the end view after it."""
        if not self._timer.isActive():
            return
        self._timer.stop()
        was_playing, self.playing = self.playing, False
        t = time.monotonic() - self._t0
        eye = self.eye
        eye.scan = None
        eye.scan_beam = 0.0
        if self.photo is not None:
            self.photo.set_scan(None)
        if was_playing and t < self.T_DONE:
            if eye.half > 0.01:
                eye.half = 1.0
            eye.xray = 1.0 if self.xray_after else 0.0
        else:
            _, eye.half, eye.cut, eye.xray = self._end
        on = 1.0 if self.show_fov else 0.0
        eye.fov_sweep = eye.fov_alpha = eye.fov_ring = on
        eye.update()
        self._say("")
        self.stopped.emit()

    def _on_user(self) -> None:
        if self._timer.isActive():
            self.stop()

    def frame(self, t: float) -> Frame:
        """The presentation at time ``t`` (seconds from the start)."""
        ring = 1.0 if self.show_fov else 0.0
        first = self.first()
        pose0, half0, cut0 = self._at.get(first.stage, (self._start_pose, 1.0, 1.0))
        if t < self.T_SIDE:                                       # 1. to the first stage
            k, kh = ramp(t, 0.0, self.T_SIDE), ramp(t, 0.2, 1.45)
            return Frame(lerp_pose(self._start_pose, pose0, k), lerp(self._start_half, half0, kh),
                         lerp(self._start_xray, 0.0, ramp(t, 0.0, 0.8)), None, 0.0, 0.0, 0.0, 0.0,
                         lerp(ring, 0.0, k), "side", lerp(self._start_cut, cut0, kh), first)
        if t < self.T_FOV[1]:                                     # 2. the field of view opens
            t0 = self.T_FOV[0]
            return Frame(pose0, half0, 0.0, 0.0, ramp(t, t0 + 0.2, t0 + 1.4), 0.0,
                         ramp(t, t0, t0 + 1.2), 1.0, 0.0, "fov", cut0, first)
        for seg in self._segs:                                    # 3. the slit, pass by pass
            kind, t0, t1 = seg[:3]
            if t >= t1:
                continue
            if kind == "scan":
                slit, first_pass = seg[3], seg[4]
                pose, half, cut = self._at[slit.stage]
                s = 0.5 - 0.5 * math.cos(math.pi * min(1.0, max(0.0, (t - t0) / (t1 - t0))))
                beam = ramp(t, t0, t0 + 0.25) * (1.0 - ramp(t, t1, t1 + 0.35))
                dim = 1.0 if first_pass else ramp(t, t0, t0 + 0.35)   # a later pass: dark again as it starts
                return Frame(pose, half, 0.0, s, dim, beam, 1.0, 1.0, 0.0, "scan", cut, slit)
            prev, cur = seg[3], seg[4]
            (pa, ha, ca), (pb, hb, cb) = self._at[prev.stage], self._at[cur.stage]
            if kind == "gap":
                return Frame(pb, hb, 0.0, 1.0, 1.0 - ramp(t, t0, t0 + 0.3), 0.0, 1.0, 1.0, 0.0, "gap", cb, prev)
            # switch: the section closes as the camera turns to the front and the front opens (or back)
            mid = 0.5 * (t0 + t1)
            half = 1.0 - ramp(t, t0, t0 + 1.2) if ha > hb else ramp(t, t1 - 1.2, t1)
            cut = lerp(ca, cb, ramp(t, t0 + 1.0, t1)) if ca > cb else lerp(ca, cb, ramp(t, t0, t1 - 1.0))
            sweep = 1.0 if t < mid else ramp(t, t1 - 0.9, t1)
            alpha = 1.0 - ramp(t, t0, t0 + 0.6) if t < mid else ramp(t, t1 - 0.9, t1 - 0.3)
            return Frame(lerp_pose(pa, pb, ramp(t, t0 + 0.2, t1 - 0.2)), half, 0.0, None, 0.0, 0.0, sweep, alpha,
                         0.0, "switch", cut, prev if t < mid else cur)
        last = self._last
        pose, half, cut = self._at.get(last.stage, (self._start_pose, 1.0, 1.0))
        end_pose, end_half, end_cut, end_xray = self._end or (pose, half, cut, 1.0)
        if t < self.T_DONE:
            return Frame(pose, half, 0.0, 1.0, 1.0 - ramp(t, self.T_DONE - self.DONE, self.T_DONE), 0.0, 1.0, 1.0,
                         0.0, "done", cut, last)
        t0, t1 = self.T_TURN
        if t < t1:                                                # 4. to the oblique 3D view
            return Frame(lerp_pose(pose, end_pose, ramp(t, t0, t1)), lerp(half, end_half, ramp(t, t0 + 0.3, t1 - 0.6)),
                         end_xray * ramp(t, t0, t0 + 1.8), None, 0.0, 0.0, 1.0, 1.0 - ramp(t, t0, t0 + 0.5),
                         ramp(t, t0 + 1.2, t0 + 2.2), "turn", cut, last)
        # 5. keep turning (speeding up gently), the field ring fades to what the viewer chose
        ts = t - t1
        spin = self.SPIN_RATE * (ts - 1.5 * (1.0 - math.exp(-ts / 1.5)))
        return Frame(dict(end_pose, yaw=(end_pose["yaw"] + spin) % 360.0), end_half, end_xray, None, 0.0, 0.0, 1.0,
                     0.0, lerp(1.0, ring, ramp(ts, 1.5, 3.0)), "spin", end_cut, last)

    def _say(self, name: str) -> None:
        if name != self._name:
            self._name = name
            self.passChanged.emit(name)

    def _apply(self, f: Frame) -> None:
        eye = self.eye
        eye.half, eye.xray, eye.cut = f.half, f.xray, f.cut
        eye.scan, eye.scan_dim, eye.scan_beam = f.scan, f.scan_dim, f.scan_beam
        eye.fov_sweep, eye.fov_alpha, eye.fov_ring = f.fov_sweep, f.fov_alpha, f.fov_ring
        eye.slit_axis, eye.scan_sign = f.slit.axis, f.slit.sign
        p = f.pose
        eye.yaw, eye.pitch, eye.dist = p["yaw"], p["pitch"], p["dist"]
        eye.target = np.asarray(p["target"], np.float64)
        eye.update()
        if self.photo is not None:
            self.photo.set_scan(f.scan, f.scan_dim, eye.scan_dir(f.slit.axis, f.slit.sign))
        if self.playing:
            where = " · 세로 단면" if f.slit.stage == "section" else " · 앞에서 본 망막"
            self._say(f"슬릿 — {f.slit.name}{where}" if f.phase in ("fov", "scan", "gap", "switch") else "")

    def _tick(self) -> None:
        t = time.monotonic() - self._t0
        self._apply(self.frame(t))
        if self.playing and t >= self.total:
            self.playing = False
            self._say("")
            self.finished.emit()


class ViewTween(QObject):
    """Glides the eye to another view (camera, 세로 단면, 망막 투시) instead of jumping."""

    def __init__(self, eye, parent=None):
        super().__init__(parent)
        self.eye = eye
        self._timer = QTimer(self, interval=16, timeout=self._tick)
        self._from: tuple = ()
        self._to: tuple = ()
        self._t0 = 0.0
        self._dur = 0.8
        self._done = None
        eye.interacted.connect(self._finish)

    def go(self, pose: dict | None, half: float, xray: float, duration: float = 0.8, done=None) -> None:
        self._finish()
        eye = self.eye
        eye.stop_motion()
        self._from = (eye.pose(), eye.half, eye.xray)
        self._to = (pose, half, xray)
        self._t0, self._dur, self._done = time.monotonic(), max(duration, 1e-3), done
        self._timer.start()
        self._tick()

    def active(self) -> bool:
        return self._timer.isActive()

    def _tick(self) -> None:
        k = ease((time.monotonic() - self._t0) / self._dur)
        (p0, h0, x0), (p1, h1, x1) = self._from, self._to
        eye = self.eye
        eye.half, eye.xray = lerp(h0, h1, k), lerp(x0, x1, k)
        if p1 is not None:
            p = lerp_pose(p0, p1, k)
            eye.yaw, eye.pitch, eye.dist = p["yaw"], p["pitch"], p["dist"]
            eye.target = np.asarray(p["target"], np.float64)
        eye.update()
        if k >= 1.0:
            self._finish()

    def _finish(self) -> None:
        """End now: the cut and the coats reach their goal, the camera stays where it is."""
        if not self._timer.isActive():
            return
        self._timer.stop()
        _, half, xray = self._to
        self.eye.half, self.eye.xray = half, xray
        self.eye.update()
        self.eye.zoomChanged.emit(self.eye.magnification)
        done, self._done = self._done, None
        if done is not None:
            done()
