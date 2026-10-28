"""3D eyeball view (QOpenGLWidget + PyOpenGL, OpenGL 2.1 / GLSL 1.20).

The fundus photograph is not baked onto a mesh: a fragment shader computes,
for every pixel of the inner sphere surface, its retinal angle ``theta``
(from the posterior pole, at the eye centre) and azimuth ``phi`` and looks
the colour up in the photo with the camera's projection
(``projection.py`` — the Python functions there mirror ``gfun`` below). So
FOV / projection / roll changes are a uniform update, and the mapping is
exact at any zoom.

Modes
  * 외부 (outside): an eyeball (sclera, cornea, iris, optic nerve) that can
    be rotated; the cut-away plane opens the front so the retina is seen
    inside the eye cup.
  * 내부 (inside): the camera sits inside the eye and looks at the retina,
    like an ophthalmoscope with an unlimited field.

Requires OpenGL 2.1. On PCs without a capable driver, start with the
``software`` OpenGL setting (Mesa llvmpipe, bundled with PySide6).
"""
from __future__ import annotations

import ctypes
import math

import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from .. import projection as proj

VERT = """
#version 120
attribute vec3 a_pos;
attribute vec3 a_nrm;
uniform mat4 u_mvp;
varying vec3 v_obj;
varying vec3 v_n;
void main() {
    v_obj = a_pos;
    v_n = a_nrm;
    gl_Position = u_mvp * vec4(a_pos, 1.0);
}
"""

EYE_FRAG = """
#version 120
uniform sampler2D u_tex;
uniform int   u_has_tex;
uniform float u_tmax;     // half internal FOV (rad)
uniform float u_gmax;     // g(u_tmax)
uniform int   u_proj;     // 0 perspective, 1 stereographic, 2 equidistant, 3 orthographic
uniform float u_d;        // viewpoint for perspective
uniform vec2  u_center;   // image centre (texture coords)
uniform vec2  u_radius;   // image-circle radius (texture coords, x and y)
uniform float u_roll;
uniform float u_cut;      // discard object z above this (outside mode)
uniform float u_limbus;   // corneal opening (outside mode)
uniform int   u_inside;
uniform vec3  u_light;
uniform float u_grid;     // > 0: draw 10°/30° retinal angle rings
varying vec3 v_obj;
varying vec3 v_n;

float gfun(float t) {
    if (u_proj == 1) return tan(0.5 * t);
    if (u_proj == 2) return t;
    if (u_proj == 3) return sin(t);
    float den = cos(t) + u_d;
    return den <= 1e-4 ? 1e4 : sin(t) / den;
}

void main() {
    if (u_inside == 0 && (v_obj.z > u_cut || v_obj.z > u_limbus)) discard;
    vec3 n = normalize(v_n);
    if (gl_FrontFacing && u_inside == 0) {           // outer sclera
        float diff = max(dot(n, u_light), 0.0);
        vec3 sclera = vec3(0.93, 0.91, 0.87);
        // faint episcleral vessels toward the limbus
        float ves = smoothstep(0.55, 0.85, v_obj.z) * (0.5 + 0.5 * sin(atan(v_obj.y, v_obj.x) * 23.0
                    + v_obj.z * 18.0)) * 0.12;
        sclera = mix(sclera, vec3(0.85, 0.45, 0.42), ves);
        gl_FragColor = vec4(sclera * (0.32 + 0.68 * diff), 1.0);
        return;
    }
    float theta = acos(clamp(-v_obj.z, -1.0, 1.0));
    // ground colour beyond the photographed field: choroid-orange fading to
    // the darker ora serrata
    vec3 base = mix(vec3(0.70, 0.33, 0.20), vec3(0.36, 0.16, 0.10), smoothstep(1.6, 2.6, theta));
    vec3 col = base;
    if (u_has_tex == 1 && theta <= u_tmax) {
        float r = gfun(theta) / u_gmax;
        float phi = atan(v_obj.y, v_obj.x) + u_roll;
        vec2 uv = u_center + vec2(cos(phi) * u_radius.x, -sin(phi) * u_radius.y) * r;
        vec4 t = texture2D(u_tex, uv);
        col = mix(base, t.rgb, t.a);
    }
    if (u_grid > 0.0) {
        float deg = degrees(theta);
        float ring10 = 1.0 - smoothstep(0.0, 0.35, abs(mod(deg + 5.0, 10.0) - 5.0));
        float ring30 = 1.0 - smoothstep(0.0, 0.5, abs(mod(deg + 15.0, 30.0) - 15.0));
        col = mix(col, vec3(0.3, 0.9, 1.0), max(ring10 * 0.35, ring30 * 0.8) * u_grid);
    }
    float diff = 0.62 + 0.38 * max(dot(-n, u_light), 0.0);
    gl_FragColor = vec4(col * diff, 1.0);
}
"""

SOLID_FRAG = """
#version 120
uniform vec4 u_color;
uniform vec3 u_light;
uniform vec3 u_campos;
uniform int  u_kind;      // 0 plain, 1 iris, 2 cornea (specular, translucent)
varying vec3 v_obj;
varying vec3 v_n;
void main() {
    vec3 n = normalize(v_n);
    if (!gl_FrontFacing) n = -n;
    vec3 v = normalize(u_campos - v_obj);
    float diff = max(dot(n, u_light), 0.0);
    vec3 h = normalize(u_light + v);
    float spec = pow(max(dot(n, h), 0.0), 60.0);
    vec3 c = u_color.rgb;
    float a = u_color.a;
    if (u_kind == 1) {
        float rr = length(v_obj.xy);
        float ang = atan(v_obj.y, v_obj.x);
        if (rr < 0.16) { gl_FragColor = vec4(0.015, 0.015, 0.02, 1.0); return; }
        float streak = 0.5 + 0.5 * sin(ang * 70.0 + sin(ang * 11.0) * 4.0 + rr * 30.0);
        c = mix(vec3(0.20, 0.12, 0.06), vec3(0.47, 0.31, 0.15), streak * 0.7);
        c = mix(c, vec3(0.55, 0.38, 0.18), (1.0 - smoothstep(0.16, 0.24, rr)) * 0.6);   // collarette
        c = mix(c, vec3(0.08, 0.06, 0.05), smoothstep(0.42, 0.48, rr));                 // limbal ring
    }
    if (u_kind == 2) {
        a = clamp(u_color.a + spec * 0.9, 0.0, 1.0);
        gl_FragColor = vec4(vec3(0.85, 0.92, 1.0) * 0.4 + vec3(spec), a);
        return;
    }
    gl_FragColor = vec4(c * (0.35 + 0.65 * diff) + vec3(spec * 0.15), a);
}
"""

LIMBUS_Z = 0.877          # corneal opening: limbus radius ≈ 0.48 (11.5 mm cornea / 24 mm eye)
IRIS_Z = 0.83
CORNEA_CENTER_Z, CORNEA_R = 0.439, 0.65


# ---------------------------------------------------------------------------
# meshes (positions, normals, triangle indices)
# ---------------------------------------------------------------------------
def sphere_mesh(n_lat: int = 128, n_lon: int = 256, a_max: float = math.pi,
                center=(0.0, 0.0, 0.0), radius: float = 1.0):
    a = np.linspace(0.0, a_max, n_lat + 1)
    b = np.linspace(0.0, 2 * math.pi, n_lon + 1)
    A, B = np.meshgrid(a, b, indexing="ij")
    nrm = np.stack([np.sin(A) * np.cos(B), np.sin(A) * np.sin(B), np.cos(A)], axis=-1).reshape(-1, 3)
    pos = nrm * radius + np.asarray(center)
    idx = []
    w = n_lon + 1
    for i in range(n_lat):
        r0, r1 = i * w, (i + 1) * w
        j = np.arange(n_lon)
        idx.append(np.stack([r0 + j, r1 + j, r1 + j + 1], axis=1))   # CCW seen from outside
        idx.append(np.stack([r0 + j, r1 + j + 1, r0 + j + 1], axis=1))
    return pos.astype(np.float32), nrm.astype(np.float32), np.concatenate(idx).astype(np.uint32)


def annulus_mesh(r_in: float, r_out: float, z: float, n: int = 160):
    t = np.linspace(0, 2 * math.pi, n + 1)
    rings = []
    for r in (r_in, r_out):
        rings.append(np.stack([r * np.cos(t), r * np.sin(t), np.full_like(t, z)], axis=1))
    pos = np.concatenate(rings).astype(np.float32)
    nrm = np.tile(np.array([[0, 0, 1]], np.float32), (len(pos), 1))
    j = np.arange(n)
    o = n + 1
    idx = np.concatenate([np.stack([j, o + j, o + j + 1], 1), np.stack([j, o + j + 1, j + 1], 1)])
    return pos, nrm, idx.astype(np.uint32)


def nerve_mesh(p: np.ndarray, radius: float = 0.14, length: float = 0.7, n: int = 48):
    """Optic nerve: a slightly tapered tube leaving the globe outward at unit point ``p``."""
    p = p / np.linalg.norm(p)
    helper = np.array([0, 1, 0.0]) if abs(p[1]) < 0.9 else np.array([1, 0, 0.0])
    u = np.cross(p, helper)
    u /= np.linalg.norm(u)
    v = np.cross(p, u)
    t = np.linspace(0, 2 * math.pi, n + 1)
    pos, nrm = [], []
    # The base ring sits just outside the globe (|0.995 p + 0.147 d| > 1) so it
    # never shows through the retina.
    for s, rr in ((0.995, radius * 1.05), (1.0 + length, radius * 0.9)):
        for tt in t:
            d = math.cos(tt) * u + math.sin(tt) * v
            pos.append(p * s + d * rr)
            nrm.append(d)
    cap_center = len(pos)
    pos.append(p * (1.0 + length))
    nrm.append(p)
    for tt in t:
        d = math.cos(tt) * u + math.sin(tt) * v
        pos.append(p * (1.0 + length) + d * radius * 0.9)
        nrm.append(p)
    j = np.arange(n)
    o = n + 1
    side = np.concatenate([np.stack([j, o + j, o + j + 1], 1), np.stack([j, o + j + 1, j + 1], 1)])
    cap = np.stack([np.full(n, cap_center), cap_center + 1 + j, cap_center + 2 + j], 1)
    return (np.asarray(pos, np.float32), np.asarray(nrm, np.float32),
            np.concatenate([side, cap]).astype(np.uint32))


# ---------------------------------------------------------------------------
# matrices
# ---------------------------------------------------------------------------
def perspective(fovy_deg: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1.0 / math.tan(math.radians(fovy_deg) / 2)
    m = np.zeros((4, 4), np.float32)
    m[0, 0], m[1, 1] = f / aspect, f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = 2 * far * near / (near - far)
    m[3, 2] = -1
    return m


def look_at(eye, target, up) -> np.ndarray:
    eye, target, up = (np.asarray(x, np.float64) for x in (eye, target, up))
    f = target - eye
    f /= np.linalg.norm(f)
    s = np.cross(f, up)
    s /= np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.identity(4, np.float32)
    m[0, :3], m[1, :3], m[2, :3] = s, u, -f
    m[:3, 3] = -m[:3, :3] @ eye
    return m


class _Mesh:
    def __init__(self, gl, pos, nrm, idx):
        self.n = int(idx.size)
        self.vbo = gl.glGenBuffers(3)
        for buf, data, target in ((self.vbo[0], pos, gl.GL_ARRAY_BUFFER),
                                  (self.vbo[1], nrm, gl.GL_ARRAY_BUFFER),
                                  (self.vbo[2], idx, gl.GL_ELEMENT_ARRAY_BUFFER)):
            gl.glBindBuffer(target, buf)
            gl.glBufferData(target, data.nbytes, data, gl.GL_STATIC_DRAW)

    def draw(self, gl, prog):
        for i, name in enumerate(("a_pos", "a_nrm")):
            loc = gl.glGetAttribLocation(prog, name)
            if loc < 0:
                continue
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vbo[i])
            gl.glEnableVertexAttribArray(loc)
            gl.glVertexAttribPointer(loc, 3, gl.GL_FLOAT, gl.GL_FALSE, 0, ctypes.c_void_p(0))
        gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, self.vbo[2])
        gl.glDrawElements(gl.GL_TRIANGLES, self.n, gl.GL_UNSIGNED_INT, ctypes.c_void_p(0))

    def delete(self, gl):
        gl.glDeleteBuffers(3, self.vbo)


class EyeView(QOpenGLWidget):
    """Interactive 3D eyeball with the fundus photo on its retina."""

    glError = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        fmt = QSurfaceFormat()
        fmt.setVersion(2, 1)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
        fmt.setDepthBufferSize(24)
        fmt.setSamples(4)
        self.setFormat(fmt)
        self.setMinimumSize(320, 240)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # image + mapping
        self._rgba: np.ndarray | None = None
        self._tex_dirty = False
        self._tex = None
        self._center = (0.5, 0.5)
        self._radius = (0.5, 0.5)
        self.fov_deg, self.fov_type = 135.0, "internal"
        self.projection, self.viewpoint = "equidistant", proj.DEFAULT_VIEWPOINT
        self.roll_deg = 0.0
        self.disc_dir: np.ndarray | None = None
        self.laterality: str | None = None
        # view
        self.mode = "outside"
        self.cut = 0.25
        self.show_nerve = True
        self.show_grid = False
        self.yaw, self.pitch, self.dist = 38.0, 18.0, 3.3
        self.in_yaw, self.in_pitch, self.in_fov, self.in_z = 0.0, 0.0, 85.0, 0.35
        self._drag: QPointF | None = None
        self._ok = False
        self._meshes: dict = {}

    # -- public API ----------------------------------------------------------
    def set_image(self, rgb: np.ndarray | None, alpha: np.ndarray | None = None,
                  circle: tuple[float, float, float] | None = None) -> None:
        if rgb is None:
            self._rgba = None
        else:
            h, w = rgb.shape[:2]
            a = alpha if alpha is not None else np.full((h, w), 255, np.uint8)
            rgba = np.dstack([rgb, a]).astype(np.uint8)
            step = max(1, int(math.ceil(max(h, w) / 4096)))
            rgba = np.ascontiguousarray(rgba[::step, ::step])
            self._rgba = rgba
            cx, cy, r = circle or (w / 2, h / 2, min(w, h) / 2)
            self._center = (cx / w, cy / h)
            self._radius = (r / w, r / h)
        self._tex_dirty = True
        self.update()

    def set_mapping(self, *, fov_deg=None, fov_type=None, projection=None, viewpoint=None,
                    roll_deg=None) -> None:
        if fov_deg is not None:
            self.fov_deg = float(fov_deg)
        if fov_type is not None:
            self.fov_type = fov_type
        if projection is not None:
            self.projection = projection
        if viewpoint is not None:
            self.viewpoint = float(viewpoint)
        if roll_deg is not None:
            self.roll_deg = float(roll_deg)
        self.update()

    def set_disc(self, laterality: str | None, disc_px: tuple[float, float] | None,
                 circle: tuple[float, float, float] | None) -> None:
        """Place the optic nerve behind the disc (detected, or anatomical default)."""
        self.laterality = laterality
        tmax = self.theta_max
        p = None
        if disc_px is not None and circle is not None:
            p = proj.image_to_sphere(disc_px[0], disc_px[1], circle[0], circle[1], circle[2], tmax,
                                     self.projection, self.viewpoint, math.radians(self.roll_deg))
        if p is None:
            # disc ≈ 4.5 mm nasal of the fovea ≈ 21.5° at the eye centre, slightly superior
            phi = 0.0 if laterality != "OS" else math.pi
            p = proj.sphere_point(math.radians(21.5), phi + (0.06 if laterality != "OS" else -0.06))
        self.disc_dir = np.asarray(p, np.float64)
        self._meshes.pop("nerve", None)
        self.update()

    def reset_view(self) -> None:
        self.yaw, self.pitch, self.dist = 38.0, 18.0, 3.3
        self.in_yaw, self.in_pitch, self.in_fov = 0.0, 0.0, 85.0
        self.update()

    def front_view(self) -> None:
        self.yaw, self.pitch, self.dist = 0.0, 0.0, 3.3
        self.update()

    @property
    def theta_max(self) -> float:
        return proj.theta_max(self.fov_deg, self.fov_type, self.viewpoint)

    # -- GL ------------------------------------------------------------------
    def initializeGL(self) -> None:
        try:
            from OpenGL import GL as gl
            self.gl = gl
            self._prog_eye = self._program(VERT, EYE_FRAG)
            self._prog_solid = self._program(VERT, SOLID_FRAG)
            self._meshes["eye"] = _Mesh(gl, *sphere_mesh())
            self._meshes["iris"] = _Mesh(gl, *annulus_mesh(0.0, 0.5, IRIS_Z))
            a_max = math.acos((LIMBUS_Z - CORNEA_CENTER_Z) / CORNEA_R)
            self._meshes["cornea"] = _Mesh(gl, *sphere_mesh(24, 96, a_max, (0, 0, CORNEA_CENTER_Z), CORNEA_R))
            self._max_tex = int(gl.glGetIntegerv(gl.GL_MAX_TEXTURE_SIZE))
            self._ok = True
        except Exception as exc:  # no usable OpenGL
            self._ok = False
            self.glError.emit(f"OpenGL 초기화 실패: {exc}")

    def _program(self, vs: str, fs: str):
        gl = self.gl

        def compile_(src, kind):
            sh = gl.glCreateShader(kind)
            gl.glShaderSource(sh, src)
            gl.glCompileShader(sh)
            if not gl.glGetShaderiv(sh, gl.GL_COMPILE_STATUS):
                raise RuntimeError(gl.glGetShaderInfoLog(sh).decode(errors="replace"))
            return sh

        prog = gl.glCreateProgram()
        gl.glAttachShader(prog, compile_(vs, gl.GL_VERTEX_SHADER))
        gl.glAttachShader(prog, compile_(fs, gl.GL_FRAGMENT_SHADER))
        gl.glBindAttribLocation(prog, 0, "a_pos")
        gl.glBindAttribLocation(prog, 1, "a_nrm")
        gl.glLinkProgram(prog)
        if not gl.glGetProgramiv(prog, gl.GL_LINK_STATUS):
            raise RuntimeError(gl.glGetProgramInfoLog(prog).decode(errors="replace"))
        return prog

    def _upload_texture(self) -> None:
        gl = self.gl
        if self._tex is not None:
            gl.glDeleteTextures([self._tex])
            self._tex = None
        self._tex_dirty = False
        if self._rgba is None:
            return
        data = self._rgba
        h, w = data.shape[:2]
        if max(h, w) > self._max_tex:
            step = int(math.ceil(max(h, w) / self._max_tex))
            data = np.ascontiguousarray(data[::step, ::step])
            h, w = data.shape[:2]
        self._tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._tex)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        mip = True
        try:
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_GENERATE_MIPMAP, gl.GL_TRUE)  # GL 1.4+
        except Exception:
            mip = False
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER,
                           gl.GL_LINEAR_MIPMAP_LINEAR if mip else gl.GL_LINEAR)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, w, h, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, data)

    def _camera(self, aspect: float):
        if self.mode == "inside":
            cy_, sy = math.cos(math.radians(self.in_yaw)), math.sin(math.radians(self.in_yaw))
            cp, sp = math.cos(math.radians(self.in_pitch)), math.sin(math.radians(self.in_pitch))
            eye = np.array([0.0, 0.0, self.in_z])
            direction = np.array([sy * cp, sp, -cy_ * cp])
            view = look_at(eye, eye + direction, (0, 1, 0))
            return perspective(self.in_fov, aspect, 0.01, 10.0) @ view, eye
        cy_, sy = math.cos(math.radians(self.yaw)), math.sin(math.radians(self.yaw))
        cp, sp = math.cos(math.radians(self.pitch)), math.sin(math.radians(self.pitch))
        eye = self.dist * np.array([sy * cp, sp, cy_ * cp])
        up = (0, 1, 0) if abs(self.pitch) < 89 else (0, 0, -1)
        return perspective(38.0, aspect, 0.05, 50.0) @ look_at(eye, (0, 0, 0), up), eye

    def paintGL(self) -> None:
        if not self._ok:
            return
        gl = self.gl
        if self._tex_dirty:
            self._upload_texture()
        dpr = self.devicePixelRatioF()
        w, h = max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr))
        gl.glViewport(0, 0, w, h)
        gl.glClearColor(0.105, 0.115, 0.13, 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glDisable(gl.GL_BLEND)
        mvp, campos = self._camera(w / h)
        light = campos / (np.linalg.norm(campos) or 1.0) + np.array([-0.35, 0.55, 0.0])
        if self.mode == "inside":
            light = np.array([0.0, 0.0, 1.0])
        light = (light / np.linalg.norm(light)).astype(np.float32)
        closed = self.cut >= 0.999

        # -- globe + retina ----------------------------------------------------
        p = self._prog_eye
        gl.glUseProgram(p)
        U = lambda name: gl.glGetUniformLocation(p, name)  # noqa: E731
        gl.glUniformMatrix4fv(U("u_mvp"), 1, gl.GL_TRUE, mvp)
        tmax = self.theta_max
        gl.glUniform1f(U("u_tmax"), tmax)
        gl.glUniform1f(U("u_gmax"), proj.g(tmax, self.projection, self.viewpoint))
        gl.glUniform1i(U("u_proj"), proj.PROJECTION_INDEX.get(self.projection, 0))
        gl.glUniform1f(U("u_d"), self.viewpoint)
        gl.glUniform2f(U("u_center"), *self._center)
        gl.glUniform2f(U("u_radius"), *self._radius)
        gl.glUniform1f(U("u_roll"), math.radians(self.roll_deg))
        gl.glUniform1f(U("u_cut"), 2.0 if closed else self.cut)
        gl.glUniform1f(U("u_limbus"), LIMBUS_Z if closed else 2.0)
        gl.glUniform1i(U("u_inside"), 1 if self.mode == "inside" else 0)
        gl.glUniform3f(U("u_light"), *light)
        gl.glUniform1f(U("u_grid"), 1.0 if self.show_grid else 0.0)
        gl.glUniform1i(U("u_has_tex"), 1 if self._tex is not None else 0)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._tex or 0)
        gl.glUniform1i(U("u_tex"), 0)
        self._meshes["eye"].draw(gl, p)

        if self.mode == "inside":
            return
        # -- optic nerve / anterior segment --------------------------------------
        s = self._prog_solid
        gl.glUseProgram(s)
        S = lambda name: gl.glGetUniformLocation(s, name)  # noqa: E731
        gl.glUniformMatrix4fv(S("u_mvp"), 1, gl.GL_TRUE, mvp)
        gl.glUniform3f(S("u_light"), *light)
        gl.glUniform3f(S("u_campos"), *campos.astype(np.float32))
        if self.show_nerve and self.disc_dir is not None:
            if "nerve" not in self._meshes:
                self._meshes["nerve"] = _Mesh(gl, *nerve_mesh(self.disc_dir))
            gl.glUniform1i(S("u_kind"), 0)
            gl.glUniform4f(S("u_color"), 0.92, 0.86, 0.74, 1.0)
            self._meshes["nerve"].draw(gl, s)
        if closed:
            gl.glUniform1i(S("u_kind"), 1)
            gl.glUniform4f(S("u_color"), 1, 1, 1, 1)
            self._meshes["iris"].draw(gl, s)
            gl.glEnable(gl.GL_BLEND)
            # Keep destination alpha at 1: QOpenGLWidget composites its FBO as
            # premultiplied, so alpha < 1 here shows as colour artifacts.
            gl.glBlendFuncSeparate(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA, gl.GL_ZERO, gl.GL_ONE)
            gl.glDepthMask(gl.GL_FALSE)
            gl.glUniform1i(S("u_kind"), 2)
            gl.glUniform4f(S("u_color"), 1, 1, 1, 0.12)
            self._meshes["cornea"].draw(gl, s)
            gl.glDepthMask(gl.GL_TRUE)
            gl.glDisable(gl.GL_BLEND)

    # -- interaction -----------------------------------------------------------
    def mousePressEvent(self, e):
        self._drag = e.position()

    def mouseReleaseEvent(self, e):
        self._drag = None

    def mouseMoveEvent(self, e):
        if self._drag is None:
            return
        d = e.position() - self._drag
        self._drag = e.position()
        if self.mode == "inside":
            k = self.in_fov / max(self.height(), 1)
            self.in_yaw = max(-150.0, min(150.0, self.in_yaw - d.x() * k))
            self.in_pitch = max(-85.0, min(85.0, self.in_pitch + d.y() * k))
        else:
            self.yaw = (self.yaw - d.x() * 0.4) % 360.0
            self.pitch = max(-89.0, min(89.0, self.pitch + d.y() * 0.4))
        self.update()

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120.0
        if self.mode == "inside":
            self.in_fov = max(20.0, min(140.0, self.in_fov * (0.92 ** steps)))
        else:
            self.dist = max(1.6, min(12.0, self.dist * (0.9 ** steps)))
        self.update()

    def mouseDoubleClickEvent(self, e):
        self.reset_view()

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            dx = {Qt.Key.Key_Left: -10, Qt.Key.Key_Right: 10}.get(k, 0)
            dy = {Qt.Key.Key_Up: -10, Qt.Key.Key_Down: 10}.get(k, 0)
            if self.mode == "inside":
                self.in_yaw = max(-150.0, min(150.0, self.in_yaw - dx * 0.5))
                self.in_pitch = max(-85.0, min(85.0, self.in_pitch + dy * 0.5))
            else:
                self.yaw = (self.yaw - dx) % 360
                self.pitch = max(-89.0, min(89.0, self.pitch + dy))
            self.update()
        else:
            super().keyPressEvent(e)
