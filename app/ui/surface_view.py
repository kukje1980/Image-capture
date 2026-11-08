"""3D 화면: 영상 밝기를 높이로 바꾼 입체 표면 (보기 전용 — 저장 원본은 그대로).

OpenGL 없이 numpy 로 그린다 (어느 PC 그래픽에서도 동작). 격자 칸을 화면에서 차지하는
크기만큼 촘촘한 표본으로 채워 원근 투영하고, 가까운 표본이 이기는 z-버퍼로 찍은 뒤
화면 크기로 부드럽게 키운다.
- 색: 원본 영상 또는 높이 컬러맵(낮음 파랑 → 높음 빨강), 경사에 따른 음영
- 드래그 = 회전, 휠 = 확대/축소, 더블클릭 = 시점 초기화
"""
from __future__ import annotations

import math
import time

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter

from app.ui.video_view import VideoView, scaled_font

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

DEFAULT_CAM = {"yaw": -0.42, "pitch": 0.98, "zoom": 1.0}
_LIGHT = np.array([-0.35, 0.45, 0.82], np.float32) / np.linalg.norm([-0.35, 0.45, 0.82])
_BG_TOP = np.array([11, 8, 6], np.float32)         # BGR (#06080b)
_BG_MID = np.array([43, 32, 23], np.float32)


def _jet(h: np.ndarray) -> np.ndarray:
    """0~1 → BGR float (낮음 파랑 → 청록 → 초록 → 노랑 → 높음 빨강). 웹 3D 화면과 같은 색."""
    t = np.clip(h, 0, 1) * 4.0
    r = np.clip(1.5 - np.abs(t - 3.0), 0, 1)
    g = np.clip(1.5 - np.abs(t - 2.0), 0, 1)
    b = np.clip(1.5 - np.abs(t - 1.0), 0, 1)
    return np.stack([b, g, r], -1) * 255.0


_BG_CACHE: dict = {}


def _background(w: int, h: int) -> np.ndarray:
    bg = _BG_CACHE.get((w, h))
    if bg is not None:
        return bg
    if len(_BG_CACHE) > 8:
        _BG_CACHE.clear()
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.hypot((xx - w * 0.5) / max(w, 1), (yy - h * 0.38) / max(h, 1)) * 1.8
    k = np.clip(1.0 - d, 0, 1)[..., None]
    bg = (_BG_TOP + (_BG_MID - _BG_TOP) * k * 0.55).astype(np.uint8)
    _BG_CACHE[(w, h)] = bg
    return bg


class SurfaceModel:
    """프레임 → 높이·색 격자 (긴 변 grid 개 꼭짓점)."""

    def __init__(self, frame: np.ndarray, grid: int = 200):
        h0, w0 = frame.shape[:2]
        self.aspect = w0 / max(h0, 1)
        if self.aspect >= 1:
            gw, gh = grid, max(2, round(grid / self.aspect))
        else:
            gh, gw = grid, max(2, round(grid * self.aspect))
        if frame.ndim == 2:
            frame = np.dstack([frame] * 3)
        small = cv2.resize(frame, (gw, gh), interpolation=cv2.INTER_AREA) if cv2 is not None else \
            frame[np.linspace(0, h0 - 1, gh).astype(int)][:, np.linspace(0, w0 - 1, gw).astype(int)]
        luma = np.array([0.114, 0.587, 0.299], np.float32)          # BGR
        gray = small.astype(np.float32) @ luma / 255.0
        if cv2 is not None:
            gray = cv2.blur(gray, (3, 3))                 # 센서 잡티로 표면이 거칠어지지 않게
        self.gw, self.gh = gw, gh
        self.height = gray                                 # (gh, gw) 0~1
        self.color = small[..., :3].astype(np.float32)     # BGR
        u = np.linspace(0, 1, gw, dtype=np.float32)
        v = np.linspace(0, 1, gh, dtype=np.float32)
        self.x = np.broadcast_to((u - 0.5) * self.aspect, (gh, gw))
        self.y = np.broadcast_to((0.5 - v)[:, None], (gh, gw))


def _project(x, y, z, yaw, pitch, dist, f, ar, w, h):
    """모델 좌표 → 화면 px 와 깊이 (Rz(yaw) → Rx(-pitch) → 뒤로 dist, 원근)."""
    cy_, sy_ = math.cos(yaw), math.sin(yaw)
    x1, y1 = cy_ * x - sy_ * y, sy_ * x + cy_ * y
    ca, sa = math.cos(-pitch), math.sin(-pitch)
    y2, z2 = ca * y1 - sa * z, sa * y1 + ca * z
    depth = dist - z2
    inv = 1.0 / np.maximum(depth, 0.05)
    px = (f / ar * x1 * inv + 1.0) * (0.5 * w)
    py = (1.0 - f * (y2 + 0.04) * inv) * (0.5 * h)
    return px, py, depth


def render_surface(model: SurfaceModel, width: int, height: int, yaw: float = DEFAULT_CAM["yaw"],
                   pitch: float = DEFAULT_CAM["pitch"], zoom: float = 1.0, scale: float = 0.4,
                   colormap: bool = False, background: np.ndarray | None = None,
                   budget: int = 220_000) -> np.ndarray:
    """표면을 width×height BGR 영상으로 그린다 (웹 WebGL 화면과 같은 카메라·조명).

    격자 칸마다 화면에서 차지하는 크기만큼 칸 안을 촘촘히 표본(쌍선형 보간)으로 채운 뒤
    z-버퍼(np.minimum.at)로 가까운 표본만 남긴다 → 가파른 벽(슬릿 빔)도 빈틈 없이 그려진다.
    """
    w, h = max(8, int(width)), max(8, int(height))
    if background is None or background.shape[:2] != (h, w):
        background = _background(w, h)
    img = background.copy()
    m = model
    hh = m.height
    gh, gw = hh.shape
    # 경사 음영 (높이 배율 반영) → 꼭짓점 색
    gx = np.gradient(hh, axis=1) * scale / (m.aspect / max(gw - 1, 1))
    gy = -np.gradient(hh, axis=0) * scale / (1.0 / max(gh - 1, 1))       # 영상 위쪽이 +y
    lam = (-gx * _LIGHT[0] - gy * _LIGHT[1] + _LIGHT[2]) / np.sqrt(gx * gx + gy * gy + 1.0)
    lam = np.clip(lam, 0, 1)
    vcol = (_jet(hh) if colormap else m.color) * (0.42 + 0.7 * lam)[..., None]
    vz = hh * scale - 0.3 * scale

    ar = w / h
    # 표면 전체가 보이는 거리
    fit = max(1.05, 0.62 * m.aspect / ar + 0.55, 1.3 * math.sin(pitch) + 0.55)
    dist = fit * 1.55 * zoom
    f = 1.0 / math.tan(math.radians(38) / 2)
    px, py, dep = _project(m.x, m.y, vz, yaw, pitch, dist, f, ar, w, h)

    # 칸마다 화면 크기(px) → 칸당 표본 수 s×s
    def edge(a, b):
        return np.hypot(a[0] - b[0], a[1] - b[1])
    A = (px[:-1, :-1], py[:-1, :-1])
    B = (px[:-1, 1:], py[:-1, 1:])
    C = (px[1:, :-1], py[1:, :-1])
    D = (px[1:, 1:], py[1:, 1:])
    ext = np.maximum.reduce([edge(A, B), edge(A, C), edge(B, D), edge(C, D), edge(A, D)])
    xs4 = np.stack([A[0], B[0], C[0], D[0]])
    ys4 = np.stack([A[1], B[1], C[1], D[1]])
    visible = ((dep[:-1, :-1] > 0.05) & (ext < 4 * (w + h))          # 화면 밖 칸은 건너뜀
               & (xs4.max(0) >= 0) & (xs4.min(0) < w) & (ys4.max(0) >= 0) & (ys4.min(0) < h))
    step = 1.5
    s = np.clip(np.ceil(ext / step), 1, 64).astype(np.int32)
    total = int((s[visible] ** 2).sum())
    if total > budget and min(w, h) > 64:
        # 크게 확대해 표본이 너무 많으면 작은 해상도로 그린 뒤 키운다 (일의 양을 일정하게)
        r = max(0.25, math.sqrt(budget / total))
        small = render_surface(model, max(8, int(w * r)), max(8, int(h * r)), yaw, pitch, zoom,
                               scale, colormap, None, budget)
        return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR) if cv2 is not None else img
    k = 2                          # 점(splat) 한 변 px — 표본 간격 1.5px 를 빈틈 없이 덮음

    dx = m.aspect / max(gw - 1, 1)
    dy = 1.0 / max(gh - 1, 1)
    xs, ys, zs, cs = [], [], [], []
    for sv in np.unique(s[visible]):
        jj, ii = np.nonzero(visible & (s == sv))
        t = (np.arange(sv, dtype=np.float32) + 0.5) / sv
        uu, vv = np.meshgrid(t, t)                          # (sv, sv)
        uu = uu.ravel()[None, :]
        vv = vv.ravel()[None, :]
        j0, i0 = jj[:, None], ii[:, None]
        w00 = (1 - uu) * (1 - vv)
        w01 = uu * (1 - vv)
        w10 = (1 - uu) * vv
        w11 = uu * vv
        zs.append((vz[j0, i0] * w00 + vz[j0, i0 + 1] * w01
                   + vz[j0 + 1, i0] * w10 + vz[j0 + 1, i0 + 1] * w11).ravel())
        xs.append((m.x[j0, i0] + uu * dx).ravel())
        ys.append((m.y[j0, i0] - vv * dy).ravel())
        c = (vcol[j0, i0] * w00[..., None] + vcol[j0, i0 + 1] * w01[..., None]
             + vcol[j0 + 1, i0] * w10[..., None] + vcol[j0 + 1, i0 + 1] * w11[..., None])
        cs.append(c.reshape(-1, 3))
    if not xs:
        return img
    sx, sy, sd = _project(np.concatenate(xs), np.concatenate(ys), np.concatenate(zs),
                          yaw, pitch, dist, f, ar, w, h)
    col = np.clip(np.concatenate(cs), 0, 255).astype(np.uint8)
    ix0 = np.floor(sx - (k - 1) / 2).astype(np.int32)
    iy0 = np.floor(sy - (k - 1) / 2).astype(np.int32)
    keep = (sd > 0.05) & (ix0 > -k) & (ix0 < w) & (iy0 > -k) & (iy0 < h)
    ix0, iy0, sd, col = ix0[keep], iy0[keep], sd[keep].astype(np.float32), col[keep]
    idx_l, dep_l, src_l = [], [], []
    src = np.arange(ix0.size, dtype=np.int32)
    for oy in range(k):
        for ox in range(k):
            ix, iy = ix0 + ox, iy0 + oy
            v = (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
            idx_l.append(iy[v] * w + ix[v])
            dep_l.append(sd[v])
            src_l.append(src[v])
    idx = np.concatenate(idx_l)
    if idx.size == 0:
        return img
    dpt = np.concatenate(dep_l)
    srcs = np.concatenate(src_l)
    zbuf = np.full(w * h, np.inf, np.float32)
    np.minimum.at(zbuf, idx, dpt)                           # 화소마다 가장 가까운 깊이
    win = dpt <= zbuf[idx]
    img.reshape(-1, 3)[idx[win]] = col[srcs[win]]
    return img


class SurfaceView(VideoView):
    """3D 화면 위젯 (VideoView 의 HUD·대기 화면을 그대로 쓴다)."""

    FULL_W, FULL_BUDGET = 720, 220_000        # 멈춰 있을 때 (화면 크기로 부드럽게 확대)
    FAST_W, FAST_BUDGET = 432, 80_000         # 끄는 동안 (가볍게 → 손을 떼면 다시 선명하게)
    LIVE_MS = 120                              # 라이브 표면 갱신 간격 (약 8 fps)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model: SurfaceModel | None = None
        self._pending = None
        self._img: QImage | None = None
        self.cam = dict(DEFAULT_CAM)
        self.scale = 0.4
        self.colormap = False
        self._drag = None
        self._dirty = True
        self._fast = False
        self._last_build = 0.0
        self._build_timer = QTimer(self)
        self._build_timer.setSingleShot(True)
        self._build_timer.timeout.connect(self._build)
        self._settle = QTimer(self)                # 조작이 멈추면 선명하게 다시 그림
        self._settle.setSingleShot(True)
        self._settle.setInterval(160)
        self._settle.timeout.connect(self._sharpen)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.set_hud(view="3D")

    # ---- 공개 API ----
    def set_frame(self, frame: np.ndarray) -> None:
        """새 프레임 → 표면 갱신 (라이브는 LIVE_MS 간격으로 묶어서)."""
        self._frame = frame
        self._pending = frame
        if not self._build_timer.isActive():
            wait = max(0, int(self.LIVE_MS - (time.time() - self._last_build) * 1000))
            self._build_timer.start(wait)

    def clear(self) -> None:
        self._model = None
        self._pending = None
        self._img = None
        super().clear()

    def set_height(self, v: float) -> None:
        self.scale = max(0.0, min(1.0, float(v)))
        self._invalidate()

    def set_colormap(self, on: bool) -> None:
        self.colormap = bool(on)
        self._invalidate()

    def reset_view(self) -> None:
        self.cam = dict(DEFAULT_CAM)
        self._invalidate()

    def has_image(self) -> bool:
        return self._model is not None or self._pending is not None

    def snapshot(self, width: int = 1600) -> np.ndarray | None:
        """지금 시점의 3D 화면을 BGR 영상으로 (3D 저장용 — 화면보다 큰 해상도)."""
        if self._pending is not None:
            self._build()
        if self._model is None:
            return None
        ar = self.width() / max(1, self.height())
        c = self.cam
        height = max(8, int(round(width / ar)))
        return render_surface(self._model, width, height, c["yaw"], c["pitch"], c["zoom"],
                              self.scale, self.colormap, budget=900_000)

    # ---- 내부 ----
    def _build(self) -> None:
        if self._pending is not None:
            self._model = SurfaceModel(self._pending)
            self._pending = None
            self._last_build = time.time()
            self._invalidate()

    def _invalidate(self, fast: bool = False) -> None:
        self._dirty = True
        self._fast = fast
        if fast:
            self._settle.start()
        self.update()

    def _sharpen(self) -> None:
        if self._drag is None:
            self._invalidate(False)

    def _render(self) -> None:
        if self._model is None:
            self._img = None
            return
        if self._fast:
            mw, budget = self.FAST_W, self.FAST_BUDGET
        else:
            mw, budget = self.FULL_W, self.FULL_BUDGET
        w, h = max(1, self.width()), max(1, self.height())
        k = min(1.0, mw / w)
        rw, rh = max(8, int(w * k)), max(8, int(h * k))
        c = self.cam
        out = render_surface(self._model, rw, rh, c["yaw"], c["pitch"], c["zoom"],
                             self.scale, self.colormap, budget=budget)
        rgb = np.ascontiguousarray(out[..., ::-1])
        self._img = QImage(rgb.data, rw, rh, rw * 3, QImage.Format.Format_RGB888).copy()
        self._dirty = False

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self.has_image():
            p.fillRect(self.rect(), QColor("#000000"))
            self._paint_placeholder(p)
            return
        if self._dirty or self._img is None:
            self._render()
        if self._img is not None:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.drawImage(QRectF(self.rect()), self._img)
        else:
            p.fillRect(self.rect(), QColor("#06080b"))
        if self._compact:                          # 모두 보기의 작은 화면: 표면만
            return
        self._paint_hud(p)
        p.setFont(scaled_font(self.font(), 0.9))
        p.setPen(QColor("#a3acba"))
        p.drawText(QRectF(0, self.height() - 34, self.width(), 22), Qt.AlignmentFlag.AlignCenter,
                   "드래그: 회전 · 휠: 확대 · 더블클릭: 시점 초기화")

    def resizeEvent(self, e) -> None:  # noqa: N802
        self._invalidate(fast=True)
        super().resizeEvent(e)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = QPointF(e.position())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._drag is None:
            return
        d = e.position() - self._drag
        self._drag = QPointF(e.position())
        self.cam["yaw"] += d.x() * 0.008
        self.cam["pitch"] = min(1.45, max(0.0, self.cam["pitch"] + d.y() * 0.006))
        self._invalidate(fast=True)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._settle.start()

    def wheelEvent(self, e) -> None:  # noqa: N802
        dy = e.angleDelta().y()
        if dy:
            self.cam["zoom"] = min(3.0, max(0.35, self.cam["zoom"] * math.exp(-dy / 120 * 0.14)))
            self._invalidate(fast=True)

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        self.reset_view()
