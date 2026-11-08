"""슬릿 스캔: the wide-field photo next to the 3D eye, and the scan animation.

``ScanPhotoView`` shows the photo flat (black outside the image circle, so the
name / ID the device burns into a corner stays hidden) with a horizontal slit
that runs from the top to the bottom of the field: above it the photo is
"scanned" (bright), below it dark.

``SlitScanShow`` plays the presentation on an ``EyeView`` and a
``ScanPhotoView`` together:

1. the eye turns to the side and is cut in half along the photo's vertical
   meridian (세로 단면);
2. the field of view opens as two rays from the eye centre, with the angle;
3. the slit runs down the photo while its beam goes through the pupil to the
   same place on the retina (the not yet scanned retina is dark);
4. the eye turns to an oblique view from the front while the cut moves out to
   show the macula and the disc inside, and the outer coats turn see-through
   (망막 투시) — the photo is on the retina, seen from inside and outside;
5. the eye keeps turning slowly until the user takes over.

The timeline is a pure function of time (``frame``), so it is tested without
OpenGL.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np
from PIL import Image
from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget


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
        self.scan: float | None = None   # 0 top … 1 bottom
        self.dim = 1.0                   # darkness of the part below the slit (0 … 1)
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
        crop = rgb[y0:y1, x0:x1, :3].astype(np.float32)
        if alpha is not None:             # black outside the field (hides text burned into the corners)
            crop *= alpha[y0:y1, x0:x1, None].astype(np.float32) / 255.0
        img = Image.fromarray(crop.clip(0, 255).astype(np.uint8))
        s = min(1.0, self.MAX_SIDE / max(img.size))
        if s < 1.0:
            img = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))),
                             Image.Resampling.LANCZOS)
        data = np.ascontiguousarray(np.asarray(img))
        qimg = QImage(data.data, data.shape[1], data.shape[0], 3 * data.shape[1],
                      QImage.Format.Format_RGB888).copy()
        self._pix = QPixmap.fromImage(qimg)
        k = data.shape[0] / float(y1 - y0)
        self._rows = ((cy - r - y0) * k, (cy + r - y0) * k)
        self.update()

    def set_scan(self, s: float | None, dim: float = 1.0) -> None:
        self.scan, self.dim = s, dim
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
            y = min(rect.bottom(), max(rect.top(), self.slit_y(min(1.0, max(0.0, self.scan)))))
            p.fillRect(QRectF(rect.left(), y, rect.width(), rect.bottom() - y), QColor(0, 0, 0, int(190 * self.dim)))
            # a soft afterglow just above the slit, then the slit itself
            glow = QLinearGradient(0.0, y - rect.height() * 0.05, 0.0, y)
            glow.setColorAt(0.0, QColor(255, 110, 50, 0))
            glow.setColorAt(1.0, QColor(255, 110, 50, int(70 * self.dim)))
            p.fillRect(QRectF(rect.left(), y - rect.height() * 0.05, rect.width(), rect.height() * 0.05), glow)
            lw = max(1.5, rect.height() / 260.0)
            for wmul, color in ((6.0, QColor(255, 80, 30, 45)), (3.0, QColor(255, 95, 40, 110)),
                                (1.4, QColor(255, 120, 60, 235)), (0.5, QColor(255, 225, 190, 255))):
                c = QColor(color)
                c.setAlpha(int(c.alpha() * self.dim))
                p.setPen(QPen(c, lw * wmul, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
                p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        if self.hint:
            p.setPen(QColor(120, 120, 120))
            p.drawText(self.rect().adjusted(8, 8, -10, -8),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, self.hint)
        p.end()


# -- the presentation ---------------------------------------------------------------
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


class SlitScanShow(QObject):
    """Plays the slit-scan presentation on an ``EyeView`` and a ``ScanPhotoView``."""

    finished = Signal()          # the timeline is over (the eye keeps turning)
    stopped = Signal()           # the user took over, or stop() was called

    # phase boundaries (seconds)
    T_SIDE = 1.6                 # turned to the side, cut in half
    T_FOV = (1.6, 3.4)           # field of view opens
    T_SCAN = (3.4, 8.6)          # the slit runs down
    T_DONE = 9.1                 # all scanned
    T_TURN = (9.1, 12.4)        # to the oblique 3D view
    END_HALF = 0.62              # the section plane at the end: 40 % of the radius off the axis
    SPIN_RATE = 14.0             # °/s afterwards

    def __init__(self, eye, photo: ScanPhotoView | None = None, parent=None):
        super().__init__(parent)
        self.eye, self.photo = eye, photo
        self._timer = QTimer(self, interval=16, timeout=self._tick)
        self._t0 = 0.0
        self._start_pose: dict = {}
        self._start_half = self._start_xray = 0.0
        self._side: dict = {}
        self._end: dict = {}
        self.show_fov = False           # 화각 표시: the field stays marked after the show
        self.xray_after = False         # 망막 투시 as the viewer had it (restored when stopped early)
        self.playing = False            # the timeline runs (False while only spinning)
        eye.interacted.connect(self._on_user)

    @property
    def total(self) -> float:
        return self.T_TURN[1]

    def active(self) -> bool:
        return self._timer.isActive()

    def start(self) -> None:
        eye = self.eye
        eye.mode = "outside"
        self._start_pose = eye.pose()
        self._start_half, self._start_xray = eye.half, eye.xray
        self._side, self._end = eye.section_pose(), eye.showcase_pose()
        self._t0 = time.monotonic()
        self.playing = True
        self._apply(self.frame(0.0))
        self._timer.start()

    def stop(self) -> None:
        """Stop where it is, leaving a clean 세로 단면 state: cut through the axis before the turn,
        the opened, see-through eye after it."""
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
            eye.half, eye.xray = 1.0, 1.0 if self.xray_after else 0.0
        else:
            eye.half, eye.xray = self.END_HALF, 1.0
        on = 1.0 if self.show_fov else 0.0
        eye.fov_sweep = eye.fov_alpha = eye.fov_ring = on
        eye.update()
        self.stopped.emit()

    def _on_user(self) -> None:
        if self._timer.isActive():
            self.stop()

    def frame(self, t: float) -> Frame:
        """The presentation at time ``t`` (seconds from the start)."""
        side, end = self._side, self._end
        ring = 1.0 if self.show_fov else 0.0
        if t < self.T_SIDE:                                       # 1. to the side, cut in half
            k = ramp(t, 0.0, self.T_SIDE)
            return Frame(lerp_pose(self._start_pose, side, k), lerp(self._start_half, 1.0, ramp(t, 0.2, 1.45)),
                         lerp(self._start_xray, 0.0, ramp(t, 0.0, 0.8)), None, 0.0, 0.0, 0.0, 0.0,
                         lerp(ring, 0.0, k), "side")
        if t < self.T_FOV[1]:                                     # 2. the field of view opens
            t0 = self.T_FOV[0]
            return Frame(side, 1.0, 0.0, 0.0, ramp(t, t0 + 0.2, t0 + 1.4), 0.0,
                         ramp(t, t0, t0 + 1.2), 1.0, 0.0, "fov")
        if t < self.T_DONE:                                       # 3. the slit runs down
            t0, t1 = self.T_SCAN
            s = 0.5 - 0.5 * math.cos(math.pi * min(1.0, max(0.0, (t - t0) / (t1 - t0))))
            beam = ramp(t, t0, t0 + 0.25) * (1.0 - ramp(t, t1, t1 + 0.35))
            return Frame(side, 1.0, 0.0, s, 1.0 - ramp(t, t1, self.T_DONE), beam, 1.0, 1.0, 0.0, "scan")
        t0, t1 = self.T_TURN
        if t < t1:                                                # 4. to the oblique 3D view
            return Frame(lerp_pose(side, end, ramp(t, t0, t1)),
                         lerp(1.0, self.END_HALF, ramp(t, t0 + 0.3, t1 - 0.6)),
                         ramp(t, t0, t0 + 1.8), None, 0.0, 0.0, 1.0, 1.0 - ramp(t, t0, t0 + 0.5),
                         ramp(t, t0 + 1.2, t0 + 2.2), "turn")
        # 5. keep turning (speeding up gently), the field ring fades to what the viewer chose
        ts = t - t1
        spin = self.SPIN_RATE * (ts - 1.5 * (1.0 - math.exp(-ts / 1.5)))
        pose = dict(end, yaw=(end["yaw"] + spin) % 360.0)
        return Frame(pose, self.END_HALF, 1.0, None, 0.0, 0.0, 1.0, 0.0,
                     lerp(1.0, ring, ramp(ts, 1.5, 3.0)), "spin")

    def _apply(self, f: Frame) -> None:
        eye = self.eye
        eye.half, eye.xray = f.half, f.xray
        eye.scan, eye.scan_dim, eye.scan_beam = f.scan, f.scan_dim, f.scan_beam
        eye.fov_sweep, eye.fov_alpha, eye.fov_ring = f.fov_sweep, f.fov_alpha, f.fov_ring
        p = f.pose
        eye.yaw, eye.pitch, eye.dist = p["yaw"], p["pitch"], p["dist"]
        eye.target = np.asarray(p["target"], np.float64)
        eye.update()
        if self.photo is not None:
            self.photo.set_scan(f.scan, f.scan_dim)

    def _tick(self) -> None:
        t = time.monotonic() - self._t0
        self._apply(self.frame(t))
        if self.playing and t >= self.total:
            self.playing = False
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
