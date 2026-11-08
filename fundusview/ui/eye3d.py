"""3D eyeball view (QOpenGLWidget + PyOpenGL, OpenGL 2.1 / GLSL 1.20).

The fundus photograph is not baked onto a mesh: a fragment shader computes,
for every pixel of the retina, its angle ``theta`` (from the posterior pole,
at the eye centre) and azimuth ``phi`` and looks the colour up in the photo
with the camera's projection (``projection.py`` — the Python functions there
mirror ``gfun`` below). So FOV / projection / roll changes are a uniform
update, and the mapping is exact at any zoom.

The rest of the eye is an anatomical model (``eye_model.py``, 1 = 12 mm):

* outer coat — wet sclera with conjunctival, episcleral, anterior ciliary,
  vortex and short posterior ciliary vessels (procedural stereographic maps)
* cornea — ray traced per pixel: Fresnel reflection of a studio soft box
  (the catchlight), refraction (n = 1.336) onto the iris, the dark pupil
  with the faint reflex of the anterior lens surface, the limbal transition
* iris — crypts, collarette, furrows and ruff with relief shading
* eye wall with thickness — the section face shows sclera, choroid, RPE
  and the retinal layers, or the ciliary body in front of the ora serrata
* inside — retina (photo + procedural periphery), the scalloped ora,
  pars plana, 72 ciliary processes, zonules, lens (nucleus in section),
  back of the iris, chamber angle; the rim of the cut casts its shadow
* optic nerve in its dural sheath (cut end: central retinal artery and
  vein, fascicles), optional extraocular muscle stumps

Looks (``detail``)
  * 간단히 ("simple"): the original light-weight model — one sphere with the
    photo inside, a flat iris, a glassy cornea and a plain nerve.
  * 자세히 ("detailed"): the anatomical model above.

Modes
  * 외부 (outside): the eyeball can be rotated; the front cut opens the eye
    so the retina is seen inside the eye cup.
  * 내부 (inside): the camera sits inside the eye and looks at the retina,
    like an ophthalmoscope with an unlimited field.

Outside views (besides the front cut)
  * 세로 단면 (``half``): the eye cut in half along the vertical meridian of
    the photo, seen from the side — the section face shows the wall layers,
    iris, lens and cornea (one analytic shader over a quad in the plane), the
    far half shows the photo on its retina. The field of view is drawn as
    two rays from the eye centre with the angle (e.g. "176°").
  * 망막 투시 (``xray``): the outer coats behind the ora are see-through, so the
    retina with the photo is seen on the globe from outside (mirrored, as it
    would be); in front of the ora the eye keeps its sclera, cornea and iris.
  * 슬릿 스캔 (``scan``): a horizontal slit runs down the photo; on the retina
    the unscanned part is dark and the slit glows, and in the section view
    the slit beam goes through the pupil to the retina.

Requires OpenGL 2.1. On PCs without a capable driver, start with the
``software`` OpenGL setting (Mesa llvmpipe, bundled with PySide6).
"""
from __future__ import annotations

import ctypes
import math
import threading

import numpy as np
from PySide6.QtCore import QEvent, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from .. import projection as proj
from ..config import config_dir
from . import eye_model as em

# kept for callers of the former module-level names
LIMBUS_Z, IRIS_Z = em.LIMBUS_Z, em.IRIS_Z
CORNEA_CENTER_Z, CORNEA_R = em.CORNEA_CENTER_Z, em.CORNEA_R

_CONSTS = {
    "PI": math.pi,
    "SCLERA_T": em.SCLERA_T, "CHOROID_T": em.CHOROID_T, "RETINA_T": em.RETINA_T,
    "LIMBUS_R": em.LIMBUS_R, "LIMBUS_Z": em.LIMBUS_Z, "CORNEA_CZ": em.CORNEA_CENTER_Z, "N_AQ": em.N_AQUEOUS,
    "IRIS_Z": em.IRIS_Z, "IRIS_ROOT_R": em.IRIS_ROOT_R, "PUPIL_R": em.PUPIL_R,
    "IRIS_K": 1.0 / (2 * em.IRIS_ROOT_R), "IRIS_TEXEL": 2 * em.IRIS_ROOT_R / 1024, "IRIS_RELIEF": 0.009,
    "LENS_FRONT_Z": em.LENS_FRONT_Z, "LENS_CURV": em.LENS_FRONT_CURV,
    "ORA": em.ORA_THETA, "NPROC": float(em.CILIARY_PROCESSES),
    "PLIC0": em.PLICATA_Z[0], "PLIC1": em.PLICATA_Z[1],
    "SCL_K": 1.0 / (2 * em.SCLERA_MAP_XMAX), "PERI_K": 1.0 / (2 * em.PERI_MAP_XMAX),
    # section face (세로 단면)
    "R_RET": em.R_RET, "Z_ORA": em.Z_ORA, "IRIS_BACK_Z": em.IRIS_BACK_Z, "LIMBUS_IN_R": em.LIMBUS_INNER_R,
    "CORNEA_R": em.CORNEA_R, "CORNEA_T": 0.55 * em.MM,
    "LENS_R": em.LENS_R, "LENS_EQ": em.LENS_EQ_Z, "LENS_FH": em.LENS_FRONT_H, "LENS_BH": em.LENS_BACK_H,
    "PROC_H": em.PROCESS_HEIGHT,
}


def _glsl(*parts: str) -> str:
    src = "#version 120\n" + "\n".join(parts)
    for k, v in _CONSTS.items():
        src = src.replace(f"@{k}@", f"{float(v):.7f}")
    return src


def _wall_radius_glsl(n: int = 32) -> str:
    """``float wall_base_r(float z)``: the inner wall radius from the ora to the iris root
    (``eye_model.wall_base_radius``) as a piecewise-linear GLSL function."""
    z = np.linspace(em.Z_ORA, em.IRIS_BACK_Z, n + 1)
    r = em.wall_base_radius(z)
    lines = ["float wall_base_r(float z) {",
             f"    if (z <= {z[0]:.7f}) return sqrt(max({em.R_RET ** 2:.7f} - z * z, 0.0));"]
    for i in range(n):
        lines.append(f"    if (z < {z[i + 1]:.7f}) return mix({r[i]:.7f}, {r[i + 1]:.7f}, "
                     f"(z - {z[i]:.7f}) / {z[i + 1] - z[i]:.7f});")
    lines += [f"    return {r[-1]:.7f};", "}"]
    return "\n".join(lines)


VERT = """
attribute vec3 a_pos;
attribute vec3 a_nrm;
attribute vec2 a_uv;
uniform mat4 u_mvp;
varying vec3 v_obj;
varying vec3 v_n;
varying vec2 v_uv;
void main() {
    v_obj = a_pos;
    v_n = a_nrm;
    v_uv = a_uv;
    gl_ClipVertex = vec4(a_pos, 1.0);    // the front cut as a clip plane (object space)
    gl_Position = u_mvp * vec4(a_pos, 1.0);
}
"""

BG_VERT = """
attribute vec3 a_pos;
varying vec2 v_p;
void main() {
    v_p = a_pos.xy;
    gl_Position = vec4(a_pos.xy, 0.99999, 1.0);   // behind everything: fills only the empty pixels
}
"""

BG_FRAG = """
uniform float u_aspect;
uniform int u_black;      // presentation (사진 나란히): plain black like the photo panel
varying vec2 v_p;
void main() {
    if (u_black == 1) { gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0); return; }
    vec2 q = vec2(v_p.x * u_aspect, v_p.y + 0.12);
    float r = length(q) / max(u_aspect, 1.0);
    vec3 c = mix(vec3(0.205, 0.215, 0.235), vec3(0.07, 0.075, 0.085), smoothstep(0.0, 1.3, r));
    gl_FragColor = vec4(c, 1.0);
}
"""

# Lighting shared by every program: a dim studio with a large soft box (key,
# above-left of the camera) and a narrow strip light (fill, right). env() is
# what a mirror-smooth surface reflects (cornea, lens), env_soft() a wet but
# rough one (conjunctiva, sheath).
COMMON = """
uniform vec3 u_key;
uniform vec3 u_kx;
uniform vec3 u_ky;
uniform vec3 u_fill;
uniform vec3 u_fx;
uniform vec3 u_fy;
uniform vec3 u_campos;
uniform float u_cut;
uniform int u_mirror;
uniform vec3 u_hk;        // 세로 단면: points with dot(p, u_hk) < -u_hoff are cut away (u_hk = 0: none)
uniform float u_hoff;
varying vec3 v_obj;
varying vec3 v_n;
varying vec2 v_uv;

bool cut_away(vec3 p) { return dot(p, u_hk) < -u_hoff - 1e-4; }
vec3 lin(vec3 c) { return pow(max(c, vec3(0.0)), vec3(2.2)); }
vec3 tonemap(vec3 x) {
    vec3 y = (x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14);
    return pow(clamp(y, 0.0, 1.0), vec3(1.0 / 2.2));
}
float hash1(float n) { return fract(sin(n) * 43758.5453); }
float vnoise1(float x) {
    float i = floor(x);
    float f = fract(x);
    return mix(hash1(i), hash1(i + 1.0), f * f * (3.0 - 2.0 * f));
}
float softbox(vec3 r, vec3 d, vec3 ax, vec3 ay, vec2 halfsize, float corner, float soft) {
    float k = dot(r, d);
    if (k <= 0.05) return 0.0;
    vec2 q = abs(vec2(dot(r, ax), dot(r, ay)) / k);
    float sd = length(max(q - halfsize + corner, 0.0)) - corner;    // rounded rectangle
    return (1.0 - smoothstep(-soft, soft, sd)) * (1.0 - 0.2 * clamp(q.y / halfsize.y, 0.0, 1.0));
}
vec3 env(vec3 r) {
    vec3 c = mix(vec3(0.012, 0.013, 0.015), vec3(0.055, 0.06, 0.07), smoothstep(-0.5, 0.9, r.y));
    c += vec3(22.0, 21.5, 20.5) * softbox(r, u_key, u_kx, u_ky, vec2(0.24, 0.17), 0.05, 0.03);
    c += vec3(2.6, 2.7, 3.0) * softbox(r, u_fill, u_fx, u_fy, vec2(0.07, 0.24), 0.03, 0.04);
    return c;
}
vec3 env_soft(vec3 r) {
    vec3 c = mix(vec3(0.02), vec3(0.06, 0.065, 0.075), smoothstep(-0.5, 0.9, r.y));
    c += vec3(1.9, 1.85, 1.75) * pow(max(dot(r, u_key), 0.0), 24.0);
    c += vec3(0.25, 0.26, 0.30) * pow(max(dot(r, u_fill), 0.0), 10.0);
    return c;
}
vec3 lighting(vec3 alb, vec3 n, float wrap) {
    float d = max((dot(n, u_key) + wrap) / (1.0 + wrap), 0.0);
    vec3 amb = mix(vec3(0.045, 0.045, 0.05), vec3(0.15, 0.16, 0.18), 0.5 + 0.5 * n.y);
    return alb * (1.45 * d + 0.28 * max(dot(n, u_fill), 0.0) + amb);
}
vec3 wet(vec3 alb, vec3 n, vec3 v, float gloss, float wrap) {
    vec3 c = lighting(alb, n, wrap);
    float F = 0.03 + 0.97 * pow(1.0 - max(dot(n, v), 0.0), 5.0);
    vec3 h = normalize(u_key + v);
    c += gloss * (env_soft(reflect(-v, n)) * F + vec3(1.0) * pow(max(dot(n, h), 0.0), 220.0) * (0.25 + F));
    return c;
}
"""

# The photo on the retina — shared by both looks. ``photo(d)`` is the colour
# of the fundus photo in direction ``d`` from the eye centre (alpha = coverage).
MAPPING_LIB = """
uniform sampler2D u_tex;
uniform int   u_has_tex;
uniform float u_tmax;     // half internal FOV (rad)
uniform float u_gmax;     // g(u_tmax)
uniform int   u_proj;     // 0 perspective, 1 stereographic, 2 equidistant, 3 orthographic, 4 radial
uniform float u_d;        // viewpoint for perspective
uniform float u_c;        // cubic share for radial
uniform vec2  u_center;   // image centre (texture coords)
uniform vec2  u_radius;   // image-circle radius (texture coords, x and y)
uniform float u_roll;
uniform float u_grid;     // > 0: draw 10°/30° retinal angle rings
uniform vec2  u_scan;     // slit scan: (slit row in texture v, darkness of the unscanned part); y = 0: off
uniform float u_fovring;  // > 0: mark the edge of the photographed field

float cbrt_(float x) { return sign(x) * pow(abs(x), 1.0 / 3.0); }

float gfun(float t) {
    if (u_proj == 1) return tan(0.5 * t);
    if (u_proj == 2) return t;
    if (u_proj == 3) return sin(t);
    if (u_proj == 4) {                       // invert s = (1-c) r + c r^3 (Cardano)
        float s = t / u_tmax;
        if (u_c < 1e-6) return s;
        float p = (1.0 - u_c) / u_c, q = -s / u_c;
        float dsc = sqrt(q * q * 0.25 + p * p * p / 27.0);
        return cbrt_(-0.5 * q + dsc) + cbrt_(-0.5 * q - dsc);
    }
    float den = cos(t) + u_d;
    return den <= 1e-4 ? 1e4 : sin(t) / den;
}

vec4 photo(vec3 d) {
    float theta = acos(clamp(-d.z, -1.0, 1.0));
    if (u_has_tex == 0 || theta > u_tmax) return vec4(0.0);
    float r = gfun(theta) / u_gmax;
    float ph = atan(d.y, d.x) + u_roll;
    vec2 uv = u_center + vec2(cos(ph) * u_radius.x, -sin(ph) * u_radius.y) * r;
    vec4 t = texture2D(u_tex, uv);
    if (u_scan.y > 0.0) {                    // below the slit: not scanned yet; the slit glows
        float dv = (uv.y - u_scan.x) / max(u_radius.y, 1e-4);
        t.rgb *= 1.0 - 0.76 * u_scan.y * smoothstep(-0.004, 0.004, dv);
        t.rgb += vec3(1.0, 0.42, 0.16) * (exp(-dv * dv / 0.00006) * 1.1 + exp(-dv * dv / 0.0012) * 0.25) * u_scan.y;
    }
    return t;
}

vec3 retina_marks(vec3 c, float theta) {
    if (u_grid > 0.0) {
        float deg = degrees(theta);
        float ring10 = 1.0 - smoothstep(0.0, 0.35, abs(mod(deg + 5.0, 10.0) - 5.0));
        float ring30 = 1.0 - smoothstep(0.0, 0.5, abs(mod(deg + 15.0, 30.0) - 15.0));
        c = mix(c, vec3(0.3, 0.9, 1.0), max(ring10 * 0.35, ring30 * 0.8) * u_grid);
    }
    if (u_fovring > 0.0 && u_has_tex == 1) {
        float e = degrees(abs(theta - u_tmax));
        c = mix(c, vec3(0.16, 0.80, 1.0), (1.0 - smoothstep(0.35, 0.9, e)) * u_fovring);
    }
    return c;
}
"""

# Detailed fundus: the photo over the procedural periphery, the ora serrata and
# the ciliary body (``w`` = 1 on the retina, 0 on the ciliary body).
RETINA_LIB = """
uniform sampler2D u_peri;
vec3 fundus(vec3 d, float z, out float w) {
    float theta = acos(clamp(-d.z, -1.0, 1.0));
    float phi = atan(d.y, d.x);
    float dx = u_mirror == 1 ? -d.x : d.x;
    float phim = u_mirror == 1 ? (phi > 0.0 ? @PI@ - phi : -@PI@ - phi) : phi;   // anatomical azimuth
    vec3 ret = texture2D(u_peri, vec2(dx, d.y) / max(1.0 - d.z, 0.05) * @PERI_K@ + 0.5).rgb;
    vec4 t = photo(d);
    ret = retina_marks(mix(ret, t.rgb, t.a), theta);
    w = 1.0;
    if (theta <= @ORA@ - 0.04) return ret;
    // ora serrata: dentate processes reaching forward between the bays
    float ora = @ORA@ + 0.035 * pow(max(cos(phim * 24.0), 0.0), 8.0) + 0.008 * sin(phim * 7.0);
    ret = mix(ret, vec3(0.42, 0.33, 0.27), smoothstep(ora - 0.025, ora, theta) * 0.55);
    // ciliary body: pars plana, then the 72 processes (whitish crests on black)
    vec3 cil = vec3(0.15, 0.095, 0.065) * (0.88 + 0.12 * sin(phim * 150.0 + sin(phim * 13.0) * 2.0));
    float u = clamp((z - @PLIC0@) / (@PLIC1@ - @PLIC0@), 0.0, 1.0);
    float c = 0.5 + 0.5 * cos(@NPROC@ * phi);
    float crest = c * c * pow(max(sin(@PI@ * u), 0.0), 1.5);
    vec3 proc = mix(vec3(0.06, 0.04, 0.028), vec3(0.27, 0.20, 0.16), smoothstep(0.30, 0.95, crest));
    cil = mix(cil, proc, smoothstep(@PLIC0@ - 0.015, @PLIC0@ + 0.025, z));
    cil = mix(cil, vec3(0.05, 0.035, 0.025), smoothstep(0.772, 0.795, z));
    w = 1.0 - smoothstep(ora - 0.003, ora + 0.003, theta);
    return mix(cil, ret, w);
}
"""

SCLERA_LIB = """
uniform sampler2D u_scl_a;
uniform sampler2D u_scl_p;
vec3 sclera_albedo(vec3 p) {
    vec3 q = p;
    if (u_mirror == 1) q.x = -q.x;
    vec3 ca = texture2D(u_scl_a, q.xy / max(1.0 + q.z, 0.05) * @SCL_K@ + 0.5).rgb;
    vec3 cp = texture2D(u_scl_p, q.xy / max(1.0 - q.z, 0.05) * @SCL_K@ + 0.5).rgb;
    return mix(cp, ca, smoothstep(-0.15, 0.15, q.z));
}
vec3 sclera_shade(vec3 alb, vec3 n, vec3 v, float gloss) {
    vec3 c = wet(alb, n, v, gloss, 0.12);
    // light scattered through the outer coats warms the terminator
    float nl = dot(n, u_key);
    return c + alb * vec3(0.30, 0.09, 0.06) * (1.0 - abs(nl)) * 0.5 * step(-0.3, nl);
}
"""

IRIS_LIB = """
uniform sampler2D u_iris;
vec4 iris_tex(vec2 xy) {
    vec2 q = xy;
    if (u_mirror == 1) q.x = -q.x;
    return texture2D(u_iris, q * @IRIS_K@ + 0.5);
}
// stroma lit from L (unit, toward the light) and seen from V; light = key visibility
vec3 iris_lit(vec2 xy, vec3 L, vec3 V, float light) {
    vec4 t = iris_tex(xy);
    float e = @IRIS_TEXEL@ * 1.5;
    float gx = (iris_tex(xy + vec2(e, 0.0)).a - t.a) * @IRIS_RELIEF@ / e;
    float gy = (iris_tex(xy + vec2(0.0, e)).a - t.a) * @IRIS_RELIEF@ / e;
    vec3 nb = normalize(vec3(-gx, -gy, 1.0));
    float ao = mix(0.35, 1.0, smoothstep(0.1, 0.75, t.a));
    float under = mix(1.0, 0.35, smoothstep(@IRIS_ROOT_R@ * 0.80, @IRIS_ROOT_R@ * 0.97, length(xy)));
    vec3 amb = vec3(mix(0.08, 0.22, 0.5 + 0.5 * nb.y)) + 0.2 * max(dot(nb, u_fill), 0.0);
    vec3 c = lin(t.rgb) * ao * under * (light * 1.6 * max(dot(nb, L), 0.0) + amb);
    vec3 h = normalize(L + V);
    return c + vec3(0.05) * pow(max(dot(nb, h), 0.0), 20.0) * light * ao * under;
}
"""

SCLERA_FRAG = """
uniform float u_clip;
uniform vec3 u_disc;
// short posterior ciliary arteries piercing the sclera around the optic nerve
float spca(vec3 p, float d) {
    if (d < 0.25 || d > 0.43) return 0.0;
    vec3 e1 = normalize(cross(u_disc, vec3(0.0, 1.0, 0.0)));
    vec3 e2 = cross(u_disc, e1);
    float a = atan(dot(p, e2), dot(p, e1));
    float sec = floor((a + @PI@) / (2.0 * @PI@) * 18.0);
    float ac = (sec + 0.5 + (hash1(sec * 7.13) - 0.5) * 0.5) / 18.0 * 2.0 * @PI@ - @PI@;
    float da = (a - ac) * sin(d);
    float dd = d - (0.28 + hash1(sec * 3.7) * 0.10);
    return step(0.3, hash1(sec * 1.91 + 3.0)) * exp(-(da * da) / 0.00006 - (dd * dd) / 0.0003);
}
uniform float u_xray;     // 망막 투시: 0 sclera … 1 the retina seen through see-through coats
void main() {
    if (!gl_FrontFacing || v_obj.z > u_clip || cut_away(v_obj)) discard;
    vec3 p = normalize(v_obj);
    vec3 v = normalize(u_campos - v_obj);
    vec3 n = normalize(v_n);
    float dn = acos(clamp(dot(p, u_disc), -1.0, 1.0));     // angle from the optic nerve
    vec3 alb = mix(sclera_albedo(p), vec3(0.36, 0.11, 0.10), spca(p, dn) * 0.6);
    float ao = mix(0.55, 1.0, smoothstep(0.235, 0.36, dn));
    vec3 c = sclera_shade(lin(alb) * ao, n, v, 1.0);
    if (u_xray > 0.0) {   // only where the retina lies behind: the front keeps its white sclera
        float w;
        vec3 f = lin(fundus(p, v_obj.z, w)) * mix(0.75, 1.0, smoothstep(0.235, 0.36, dn));
        float theta = acos(clamp(-p.z, -1.0, 1.0));
        c = mix(c, wet(f, n, v, 0.35, 0.35) * 1.15, u_xray * (1.0 - smoothstep(@ORA@ - 0.12, @ORA@ + 0.01, theta)));
    }
    gl_FragColor = vec4(tonemap(c), 1.0);
}
"""

CORNEA_FRAG = """
// The view ray is refracted at the cornea and followed to the iris plane:
// the iris and pupil are seen magnified and shifted with the view angle,
// as through a real cornea.
vec3 pupil_view(vec3 Q, vec3 T) {
    vec3 c = vec3(0.0022, 0.0018, 0.0018);
    vec3 C = vec3(0.0, 0.0, @LENS_FRONT_Z@ - @LENS_CURV@);
    vec3 oc = Q - C;
    float b = dot(oc, T);
    float dsc = b * b - (dot(oc, oc) - @LENS_CURV@ * @LENS_CURV@);
    if (dsc > 0.0) {
        float t = -b - sqrt(dsc);
        if (t > 0.0) c += env(reflect(T, normalize(Q + T * t - C))) * 0.0035;   // Purkinje III
    }
    return c;
}
void main() {
    if (cut_away(v_obj)) discard;
    vec3 P = v_obj;
    vec3 N = normalize(P - vec3(0.0, 0.0, @CORNEA_CZ@));
    vec3 I = normalize(P - u_campos);
    float F = 0.025 + 0.975 * pow(1.0 - clamp(-dot(I, N), 0.0, 1.0), 5.0);
    vec3 refl = env(reflect(I, N));
    vec3 T = refract(I, N, 1.0 / @N_AQ@);
    float lk = dot(N, u_key);
    vec3 Lin = lk > 0.0 ? -refract(-u_key, N, 1.0 / @N_AQ@) : u_key;
    vec3 trans = vec3(0.0);
    if (T.z < -1e-4) {
        vec3 Q = P + T * ((@IRIS_Z@ - P.z) / T.z);
        vec3 ir = iris_lit(Q.xy, normalize(Lin), -T, smoothstep(-0.05, 0.2, lk));
        trans = mix(pupil_view(Q, T), ir, smoothstep(@PUPIL_R@ - 0.0025, @PUPIL_R@ + 0.0025, length(Q.xy)));
    }
    vec3 col = trans * vec3(0.97, 0.98, 0.99) * (1.0 - F) + refl * F;
    float m = smoothstep(0.90, 1.0, length(P.xy) / @LIMBUS_R@);
    if (m > 0.0) {
        vec3 pn = normalize(P);
        col = mix(col, sclera_shade(lin(sclera_albedo(pn)), pn, -I, 1.0), m * m);
    }
    gl_FragColor = vec4(tonemap(col), 1.0);
}
"""

WALL_FRAG = """
uniform int   u_inside;
uniform vec3  u_light;
uniform vec3  u_open_n;   // the opening (outside mode): points q with dot(q, u_open_n) > u_open
uniform float u_open;     // are open, so the rim of the cut shadows the wall

void main() {
    if (v_obj.z > u_cut + 1e-4 || cut_away(v_obj)) discard;   // section faces lie exactly at the cut
    vec3 d = normalize(v_obj);
    vec3 n = normalize(v_n);
    float on_ret;
    vec3 col = fundus(d, v_obj.z, on_ret);

    float diff = max(dot(n, u_light), 0.0);
    float lit = 1.0;
    if (u_inside == 0) {   // where the light ray from this point meets the wall again
        vec3 q = v_obj - 2.0 * dot(v_obj, u_light) * u_light;
        lit = smoothstep(u_open - 0.05, u_open + 0.05, dot(q, u_open_n));
    }
    vec3 outc = col * (0.62 + 0.38 * diff * lit);
    if (u_inside == 0) {   // inner limiting membrane / ciliary sheen
        vec3 h = normalize(u_light + normalize(u_campos - v_obj));
        outc += vec3(0.10) * pow(max(dot(n, h), 0.0), 60.0) * lit * mix(0.4, 1.0, on_ret);
    }
    gl_FragColor = vec4(outc, 1.0);
}
"""

# The eye wall in section: sclera, choroid, RPE and retinal layers behind the
# ora serrata (``post``), sclera and ciliary body in front of it (``epith``:
# the pigmented epithelium at the inner edge).
WALL_LAYERS_LIB = """
vec3 wall_layers(vec3 p, bool post, bool epith) {
    float dd = 1.0 - length(p);              // depth below the outer surface
    float phi = atan(p.y, p.x);
    if (dd < @SCLERA_T@) {                   // sclera: interwoven collagen lamellae
        float lam = 0.5 + 0.5 * sin(dd * 520.0 + sin(phi * 37.0) * 2.0 + sin(phi * 11.0) * 1.5);
        return mix(vec3(0.84, 0.81, 0.75), vec3(0.92, 0.90, 0.86), 0.7 + 0.3 * lam);
    }
    if (!post) {                             // ciliary body in front of the ora
        if (epith) return vec3(0.09, 0.055, 0.04);                 // pigmented epithelium
        return vec3(0.46, 0.29, 0.25) * (0.9 + 0.1 * sin(phi * 300.0 + dd * 500.0));
    }
    float e = dd - @SCLERA_T@;
    if (e < 0.004) return vec3(0.36, 0.21, 0.14);                  // suprachoroid
    if (e < @CHOROID_T@ - 0.003) {                                 // choroid: vessels in pigmented stroma
        vec2 g = vec2(phi * length(p.xy) / 0.008, e / 0.006);
        vec2 ci = floor(g);
        vec2 f = fract(g) - 0.5;
        float h = hash1(ci.x * 17.0 + ci.y * 113.0);
        vec2 off = vec2(hash1(ci.x * 5.1 + ci.y * 7.7), hash1(ci.x * 3.3 + ci.y * 9.1)) - 0.5;
        float lumen = 1.0 - smoothstep(0.18 + 0.16 * h, 0.24 + 0.16 * h, length((f - off * 0.4) * vec2(1.0, 0.75)));
        return mix(vec3(0.19, 0.075, 0.05), vec3(0.50, 0.08, 0.06) * (0.75 + 0.4 * h), lumen * 0.85);
    }
    if (e < @CHOROID_T@) return vec3(0.05, 0.03, 0.02);            // retinal pigment epithelium
    float b = clamp((e - @CHOROID_T@) / @RETINA_T@, 0.0, 1.0);     // retina, outer → inner
    vec3 c = vec3(0.80, 0.56, 0.47);                               // photoreceptors
    c = mix(c, vec3(0.60, 0.40, 0.38), smoothstep(0.16, 0.20, b)); // outer nuclear layer
    c = mix(c, vec3(0.88, 0.78, 0.72), smoothstep(0.41, 0.44, b)); // outer plexiform
    c = mix(c, vec3(0.64, 0.45, 0.43), smoothstep(0.48, 0.51, b)); // inner nuclear
    c = mix(c, vec3(0.88, 0.80, 0.74), smoothstep(0.63, 0.66, b)); // inner plexiform
    c = mix(c, vec3(0.70, 0.52, 0.48), smoothstep(0.77, 0.80, b)); // ganglion cells
    return mix(c, vec3(0.86, 0.78, 0.72), smoothstep(0.87, 0.90, b)); // nerve fibre layer
}
"""

TISSUE_FRAG = """
uniform int u_kind;   // 0 wall section, 1 iris section, 2 iris, 3 chamber angle, 4 optic nerve, 5 muscle
uniform int u_rim_post;

float cell_edge(vec2 x) {           // distance to the nearest Voronoi border (fascicles)
    vec2 i = floor(x);
    vec2 f = fract(x);
    float d1 = 8.0, d2 = 8.0;
    for (int a = -1; a <= 1; a++) {
        for (int b = -1; b <= 1; b++) {
            vec2 g = vec2(float(a), float(b));
            vec2 o = vec2(hash1(dot(i + g, vec2(7.1, 157.3))), hash1(dot(i + g, vec2(113.5, 31.7))));
            float dd = length(g + o - f);
            if (dd < d1) { d2 = d1; d1 = dd; } else if (dd < d2) { d2 = dd; }
        }
    }
    return d2 - d1;
}

vec3 gonio(float z) {                        // chamber angle bands, root → cornea
    float t = clamp((z - @IRIS_Z@) / (@LIMBUS_Z@ - @IRIS_Z@), 0.0, 1.0);
    vec3 c = vec3(0.22, 0.14, 0.10);                               // ciliary body band
    c = mix(c, vec3(0.86, 0.84, 0.80), smoothstep(0.20, 0.24, t)); // scleral spur
    c = mix(c, vec3(0.34, 0.24, 0.19), smoothstep(0.30, 0.34, t)); // pigmented meshwork
    c = mix(c, vec3(0.62, 0.57, 0.52), smoothstep(0.60, 0.64, t)); // non-pigmented meshwork
    c = mix(c, vec3(0.92, 0.90, 0.86), smoothstep(0.80, 0.83, t)); // Schwalbe's line
    return mix(c, vec3(0.76, 0.79, 0.82), smoothstep(0.88, 0.92, t));
}

vec3 nerve(vec3 n, vec3 v) {
    if (v_uv.x > 2.5) {                      // cut end
        vec2 q = vec2(v_uv.x - 4.0, v_uv.y);
        float rho = length(q);
        vec3 c = mix(vec3(0.62, 0.58, 0.50), vec3(0.86, 0.83, 0.74), smoothstep(0.02, 0.09, cell_edge(q * 7.0)));
        float cra = length(q - vec2(0.10, 0.05)), crv = length(q - vec2(-0.08, -0.04));
        c = mix(c, vec3(0.86, 0.58, 0.52), 1.0 - smoothstep(0.075, 0.085, cra));
        c = mix(c, vec3(0.70, 0.10, 0.08), 1.0 - smoothstep(0.045, 0.055, cra));
        c = mix(c, vec3(0.38, 0.06, 0.08), 1.0 - smoothstep(0.075, 0.085, crv));
        c = mix(c, vec3(0.80, 0.70, 0.66), smoothstep(0.80, 0.82, rho));   // pia
        c = mix(c, vec3(0.62, 0.48, 0.45), smoothstep(0.83, 0.85, rho));   // subarachnoid space
        c = mix(c, vec3(0.90, 0.88, 0.83), smoothstep(0.88, 0.90, rho));   // dura
        return wet(lin(c), n, v, 0.6, 0.2);
    }
    float s = v_uv.x, a = v_uv.y * 2.0 * @PI@;
    float fib = 0.5 + 0.25 * sin(a * 70.0 + sin(s * 23.0 + a * 3.0) * 2.0) + 0.25 * sin(a * 31.0 - s * 9.0);
    vec3 c = mix(vec3(0.83, 0.76, 0.66), vec3(0.87, 0.82, 0.74), fib) * (0.96 + 0.04 * sin(s * 40.0 + a * 5.0));
    for (int k = 0; k < 3; k++) {            // fine dural vessels
        float ak = float(k) * 2.1 + 0.15 * sin(s * 9.0 + float(k) * 3.0);
        float da = mod(a - ak + @PI@, 2.0 * @PI@) - @PI@;
        c = mix(c, vec3(0.70, 0.26, 0.22), exp(-da * da / 0.00025) * 0.55);
    }
    c = mix(c, vec3(0.82, 0.64, 0.60), (1.0 - smoothstep(0.0, 0.12, s)) * 0.5);
    c *= mix(0.6, 1.0, smoothstep(0.0, 0.06, s));               // contact shadow at the globe
    return wet(lin(c), n, v, 0.45, 0.15);
}

vec3 muscle(vec3 n, vec3 v) {
    if (v_uv.x > 2.5) {                      // cut end: fascicles in perimysium
        vec2 q = vec2(v_uv.x - 4.0, v_uv.y);
        vec3 c = mix(vec3(0.66, 0.42, 0.38), vec3(0.42, 0.11, 0.09), smoothstep(0.03, 0.12, cell_edge(q * 13.0)));
        return wet(lin(c), n, v, 0.5, 0.2);
    }
    float x = v_uv.x, a = v_uv.y * 2.0 * @PI@;
    float tendon = 1.0 - smoothstep(-0.025, 0.025, x - 0.06 * (vnoise1(a * 4.0) - 0.5) - 0.025 * vnoise1(a * 17.0));
    vec3 belly = vec3(0.47, 0.15, 0.12) * (0.82 + 0.18 * sin(a * 160.0 + sin(x * 30.0) * 0.5));
    vec3 tend = vec3(0.92, 0.90, 0.86) * (0.94 + 0.06 * sin(a * 120.0));
    return wet(lin(mix(belly, tend, tendon)), n, v, mix(0.6, 1.0, tendon), 0.2);
}

void main() {
    if (v_obj.z > u_cut + 1e-4 || cut_away(v_obj)) discard;   // section faces lie exactly at u_cut
    vec3 v = normalize(u_campos - v_obj);
    vec3 n = normalize(v_n);
    if (dot(n, v) < 0.0) n = -n;             // meshes are seen from both sides
    vec3 col;
    if (u_kind == 0) col = wet(lin(wall_layers(v_obj, u_rim_post == 1, v_uv.x < 0.05)), n, v, 0.35, 0.3);
    else if (u_kind == 1) col = lighting(lin(vec3(0.30, 0.18, 0.09)), n, 0.3);
    else if (u_kind == 2) {
        if (n.z > 0.7) col = iris_lit(v_obj.xy, u_key, v, 1.0);
        else if (n.z < -0.7) {               // posterior pigment epithelium with radial folds
            float a = atan(v_obj.y, v_obj.x);
            col = lighting(lin(vec3(0.06, 0.035, 0.025) * (0.8 + 0.2 * sin(a * 110.0))), n, 0.2);
        } else col = lighting(lin(vec3(0.07, 0.045, 0.03)), n, 0.2);
    }
    else if (u_kind == 3) col = wet(lin(gonio(v_obj.z)), n, v, 0.3, 0.3);
    else if (u_kind == 4) col = nerve(n, v);
    else col = muscle(n, v);
    gl_FragColor = vec4(tonemap(col), 1.0);
}
"""

CLEAR_FRAG = """
uniform int u_kind;   // 0 lens surface, 1 lens section, 2 zonules, 3 cornea (세로 단면: a clear shell)
void main() {
    if (v_obj.z > u_cut + 1e-4 || cut_away(v_obj)) discard;   // section faces lie exactly at u_cut
    vec3 v = normalize(u_campos - v_obj);
    if (u_kind == 3) {
        vec3 n = normalize(v_n);
        float F = 0.03 + 0.97 * pow(1.0 - abs(dot(n, v)), 5.0);
        vec3 refl = tonemap(env(reflect(-v, n * sign(dot(n, v)))) * F);
        float lr = clamp(dot(refl, vec3(0.333)), 0.0, 1.0);
        float a = clamp(0.07 + lr, 0.0, 0.9);
        gl_FragColor = vec4((vec3(0.80, 0.86, 0.92) * 0.07 + refl * lr) / max(a, 1e-3), a);
        return;
    }
    if (u_kind == 2) {
        gl_FragColor = vec4(tonemap(lighting(lin(vec3(0.92, 0.91, 0.86)), vec3(0.0, 0.0, 1.0), 1.0)), 0.35);
        return;
    }
    if (u_kind == 1) {                       // section: yellowish nucleus, lamellar cortex, capsule
        float rho = v_uv.x;
        float nuc = 1.0 - smoothstep(0.48, 0.62, rho);
        vec3 c = mix(vec3(0.94, 0.93, 0.89), vec3(0.88, 0.79, 0.58), nuc) * (0.98 + 0.02 * sin(rho * 90.0));
        float a = mix(0.20, 0.38, nuc);
        float cap = smoothstep(0.95, 0.99, rho);
        gl_FragColor = vec4(tonemap(lighting(lin(mix(c, vec3(0.97), cap)), vec3(0.0, 0.0, 1.0), 0.3)),
                            mix(a, 0.75, cap));
        return;
    }
    vec3 n = normalize(v_n);
    if (!gl_FrontFacing) n = -n;
    float F = 0.02 + 0.98 * pow(1.0 - abs(dot(n, v)), 5.0);
    vec3 refl = tonemap(env(reflect(-v, n)) * F * 0.6);
    vec3 body = tonemap(lighting(lin(vec3(0.93, 0.88, 0.70)), n, 0.5) * 0.3);
    float ab = 0.14 + 0.5 * F;
    float lr = clamp(dot(refl, vec3(0.333)), 0.0, 1.0);
    float a = clamp(ab + lr, 0.0, 1.0);
    gl_FragColor = vec4((body * ab + refl * lr) / max(a, 1e-3), a);
}
"""

# -- 세로 단면: the section face ----------------------------------------------------
# A quad in the section plane; each pixel finds the tissue at its position from
# the model's dimensions (the same as the meshes in eye_model.py), so any plane
# through the eye gets its section without building geometry. Vitreous and
# aqueous are discarded: the far half of the eye shows through. The lens is
# drawn apart, translucent like the real one (``u_part`` 1, with the clear media).
SECTION_FRAG = """
uniform int u_part;       // 0: the opaque tissues (wall, iris, cornea), 1: the lens
@WALL_R@
float relief(float z, float phi) {           // ciliary processes (eye_model.ciliary_relief)
    float u = clamp((z - @PLIC0@) / (@PLIC1@ - @PLIC0@), 0.0, 1.0);
    float ridge = 0.5 + 0.5 * cos(@NPROC@ * phi);
    return @PROC_H@ * pow(max(sin(@PI@ * u), 0.0), 1.5) * ridge * ridge;
}
vec3 lens_layers(float rl) {                 // 0 centre … 1 capsule
    float nuc = 1.0 - smoothstep(0.48, 0.62, rl);
    vec3 c = mix(vec3(0.94, 0.93, 0.89), vec3(0.88, 0.79, 0.58), nuc) * (0.98 + 0.02 * sin(rl * 90.0));
    return mix(c, vec3(0.97), smoothstep(0.95, 0.99, rl));
}
void main() {
    vec3 p = v_obj;
    float rho = length(p), ra = length(p.xy), z = p.z, phi = atan(p.y, p.x);
    float dc = length(p - vec3(0.0, 0.0, @CORNEA_CZ@));
    int kind = -1;                           // 0 wall behind the ora, 1 in front of it, 2 iris, 3 lens, 4 cornea
    float aux = 0.0;
    if (z > @LIMBUS_Z@ || rho > 1.0) {
        if (z > @LIMBUS_Z@ - 0.02 && dc <= @CORNEA_R@ && dc >= @CORNEA_R@ - @CORNEA_T@) kind = 4;
    } else if (z > @IRIS_Z@) {               // chamber angle up to the limbus
        float t = (z - @IRIS_Z@) / (@LIMBUS_Z@ - @IRIS_Z@);
        if (ra >= @IRIS_ROOT_R@ + (@LIMBUS_IN_R@ - @IRIS_ROOT_R@) * pow(t, 1.25)) kind = 1;
    } else if (z >= @IRIS_BACK_Z@) {
        if (ra >= @IRIS_ROOT_R@) kind = 1;
        else if (ra >= @PUPIL_R@) { kind = 2; aux = z - @IRIS_BACK_Z@; }
    } else {
        float h = z >= @LENS_EQ@ ? @LENS_FH@ : @LENS_BH@;
        float u = (z - @LENS_EQ@) / h;
        float rl = sqrt(u * u + (ra / @LENS_R@) * (ra / @LENS_R@));
        if (rl <= 1.0) { kind = 3; aux = rl; }
        else {
            float ri = z <= @Z_ORA@ ? sqrt(max(@R_RET@ * @R_RET@ - z * z, 0.0)) : wall_base_r(z) - relief(z, phi);
            if (ra >= ri) { kind = z <= @Z_ORA@ ? 0 : 1; aux = ra - ri; }
        }
    }
    if (kind < 0 || (kind == 3) != (u_part == 1)) discard;
    vec3 v = normalize(u_campos - v_obj);
    vec3 n = normalize(v_n);
    if (dot(n, v) < 0.0) n = -n;
    if (kind == 3) {                         // lens: clear cortex, yellowish nucleus, glossy capsule
        float nuc = 1.0 - smoothstep(0.48, 0.62, aux);
        float cap = smoothstep(0.95, 0.99, aux);
        vec3 c = tonemap(lighting(lin(mix(lens_layers(aux), vec3(0.97), cap)), n, 0.3));
        gl_FragColor = vec4(c, mix(mix(0.16, 0.42, nuc), 0.7, cap));
        return;
    }
    vec3 c;
    float gloss = 0.35;
    if (kind == 0 || kind == 1) c = wall_layers(p, kind == 0, aux < 0.008);
    else if (kind == 2) {                    // iris: stroma over the dark pigment epithelium
        float a = atan(p.y, p.x) + p.z;
        c = aux < 0.007 ? vec3(0.06, 0.035, 0.025)
                        : vec3(0.30, 0.18, 0.09) * (0.85 + 0.15 * sin(ra * 260.0 + sin(a * 40.0) * 2.0));
    } else {                                 // cornea: epithelium, lamellar stroma, endothelium
        float t = (@CORNEA_R@ - dc) / @CORNEA_T@;
        c = vec3(0.86, 0.88, 0.90) * (0.97 + 0.03 * sin(dc * 3000.0));
        c = mix(c, vec3(0.93, 0.92, 0.90), (1.0 - smoothstep(0.06, 0.1, t)) + smoothstep(0.93, 0.97, t));
        gloss = 0.8;
    }
    gl_FragColor = vec4(tonemap(wet(lin(c), n, v, gloss, 0.3)), 1.0);
}
""".replace("@WALL_R@", _wall_radius_glsl())

# -- simple view: the original light-weight model ------------------------------
# One sphere (outside: plain sclera, inside: the retina with the photo), a
# flat iris, a glassy cornea and a plain nerve tube. Fast on any PC, also with
# software OpenGL.
SIMPLE_EYE_FRAG = """
uniform float u_cut;      // discard object z above this (outside mode)
uniform float u_limbus;   // corneal opening (outside mode)
uniform int   u_inside;
uniform vec3  u_light;
uniform int   u_side;     // 0 both faces (outer: sclera), 1 the outer surface only, 2 the retina only
                          // (wall mesh, normals toward the centre)
uniform float u_xray;     // 망막 투시: the outer surface shows the retina instead of the sclera
uniform vec3  u_hk;       // 세로 단면 (see COMMON)
uniform float u_hoff;
varying vec3 v_obj;
varying vec3 v_n;

vec3 fundus_s(vec3 d, out float theta) {
    theta = acos(clamp(-d.z, -1.0, 1.0));
    // ground colour beyond the photographed field: choroid-orange fading to
    // the darker ora serrata
    vec3 base = mix(vec3(0.70, 0.33, 0.20), vec3(0.36, 0.16, 0.10), smoothstep(1.6, 2.6, theta));
    vec4 t = photo(d);
    return retina_marks(mix(base, t.rgb, t.a), theta);
}

void main() {
    if (u_inside == 0 && (v_obj.z > u_cut || v_obj.z > u_limbus)) discard;
    if (dot(v_obj, u_hk) < -u_hoff - 1e-4) discard;
    vec3 n = normalize(v_n);
    vec3 d = normalize(v_obj);
    float theta;
    bool outer = u_side != 2 && gl_FrontFacing && u_inside == 0;
    if (u_side == 1 && !outer) discard;
    if (outer) {                                     // outer sclera
        float diff = max(dot(n, u_light), 0.0);
        vec3 sclera = vec3(0.93, 0.91, 0.87);
        // faint episcleral vessels toward the limbus
        float ves = smoothstep(0.55, 0.85, v_obj.z) * (0.5 + 0.5 * sin(atan(v_obj.y, v_obj.x) * 23.0
                    + v_obj.z * 18.0)) * 0.12;
        sclera = mix(sclera, vec3(0.85, 0.45, 0.42), ves) * (0.32 + 0.68 * diff);
        if (u_xray > 0.0) {   // only where the retina lies behind: the front keeps its white sclera
            vec3 f = fundus_s(d, theta);
            sclera = mix(sclera, f * (0.45 + 0.65 * diff), u_xray * (1.0 - smoothstep(@ORA@ - 0.12, @ORA@ + 0.01, theta)));
        }
        gl_FragColor = vec4(sclera, 1.0);
        return;
    }
    vec3 col = fundus_s(d, theta);
    float diff = 0.62 + 0.38 * max(dot(u_side == 2 ? n : -n, u_light), 0.0);
    gl_FragColor = vec4(col * diff, 1.0);
}
"""

SIMPLE_SOLID_FRAG = """
uniform vec4 u_color;
uniform vec3 u_light;
uniform vec3 u_campos;
uniform int  u_kind;      // 0 plain, 1 iris, 2 cornea (specular, translucent)
uniform vec3 u_hk;        // 세로 단면 (see COMMON)
uniform float u_hoff;
varying vec3 v_obj;
varying vec3 v_n;
void main() {
    if (dot(v_obj, u_hk) < -u_hoff - 1e-4) discard;
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

# texture units
_UNITS = {"tex": 0, "iris": 1, "scl_a": 2, "scl_p": 3, "peri": 4}

_TEX_LOCK = threading.Lock()
_TEXTURES: dict | None = None


def model_textures() -> dict:
    """The anatomical textures, generated (or read from the cache) once per process."""
    global _TEXTURES
    with _TEX_LOCK:
        if _TEXTURES is None:
            _TEXTURES = em.load_textures(config_dir() / "cache")
        return _TEXTURES


def warm_up_textures() -> None:
    """Prepare the textures in the background so the first 3D view opens without delay."""
    if _TEXTURES is None:
        threading.Thread(target=model_textures, name="eye-textures", daemon=True).start()


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


def _unit(v) -> np.ndarray:
    v = np.asarray(v, np.float64)
    return v / (np.linalg.norm(v) or 1.0)


def studio_lights(campos, cam_up=(0.0, 1.0, 0.0)) -> dict:
    """Key soft box above-left of the camera and a fill strip to its right, with their axes."""
    c = _unit(campos)
    right = np.cross(-c, cam_up)
    right = _unit(right if np.linalg.norm(right) > 1e-6 else (1.0, 0.0, 0.0))
    up = np.cross(right, -c)
    key = _unit(c - 0.85 * right + 0.75 * up)
    fill = _unit(c + 1.0 * right - 0.2 * up)
    out = {"key": key, "fill": fill}
    for name, d in (("k", key), ("f", fill)):
        ax = _unit(np.cross(up, d))
        out[name + "x"], out[name + "y"] = ax, np.cross(d, ax)
    return out


class _Mesh:
    """Vertex buffers of a ``MeshData`` (attributes 0 = position, 1 = normal, 2 = uv)."""

    def __init__(self, gl, m: em.MeshData):
        self.n = int(m.idx.size)
        self.mode = gl.GL_LINES if m.lines else gl.GL_TRIANGLES
        arrays = [m.pos, m.nrm] + ([m.uv] if m.uv is not None else [])
        ids = gl.glGenBuffers(len(arrays) + 1)
        self.vbo = [int(i) for i in ids]
        for buf, data in zip(self.vbo, arrays):
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, buf)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, data.nbytes, data, gl.GL_STATIC_DRAW)
        self.ibo = self.vbo.pop()
        gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, self.ibo)
        gl.glBufferData(gl.GL_ELEMENT_ARRAY_BUFFER, m.idx.nbytes, m.idx, gl.GL_STATIC_DRAW)

    def draw(self, gl) -> None:
        for loc, size in ((0, 3), (1, 3), (2, 2)):
            if loc >= len(self.vbo):
                gl.glDisableVertexAttribArray(loc)
                continue
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vbo[loc])
            gl.glEnableVertexAttribArray(loc)
            gl.glVertexAttribPointer(loc, size, gl.GL_FLOAT, gl.GL_FALSE, 0, ctypes.c_void_p(0))
        gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, self.ibo)
        gl.glDrawElements(self.mode, self.n, gl.GL_UNSIGNED_INT, ctypes.c_void_p(0))

    def delete(self, gl) -> None:
        gl.glDeleteBuffers(len(self.vbo) + 1, self.vbo + [self.ibo])


def _smooth(e0: float, e1: float, x: float) -> float:
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * (3.0 - 2.0 * t)


class EyeView(QOpenGLWidget):
    """Interactive 3D eyeball with the fundus photo on its retina."""

    glError = Signal(str)
    zoomChanged = Signal(float)        # magnification relative to the start view
    interacted = Signal()              # the user dragged, zoomed or pressed a view key

    DETAILS = ("simple", "detailed")
    DIST0, FOV0 = 3.3, 85.0            # start distance (outside) / field of view (inside)
    FOV_COLOR = QColor(56, 200, 255)   # field-of-view rays and label (세로 단면)
    BEAM_COLOR = QColor(255, 128, 64)  # slit light

    def __init__(self, parent=None):
        super().__init__(parent)
        fmt = QSurfaceFormat()
        fmt.setVersion(2, 1)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
        fmt.setDepthBufferSize(24)
        fmt.setStencilBufferSize(8)        # QPainter fills and strokes paths with the stencil
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
        self.radial_c = proj.DEFAULT_RADIAL_C
        self.roll_deg = 0.0
        self.disc_dir: np.ndarray | None = None
        self.laterality: str | None = None
        # view
        self.detail = "simple"
        self.mode = "outside"
        self.cut = 0.25
        self.show_nerve = True
        self.show_muscles = False
        self.show_grid = False
        # 세로 단면 / 망막 투시 / 슬릿 스캔 (all 0 / None: the plain outside view)
        self.half = 0.0                # 0 … 1: the section plane slides in until half the eye is cut away
        self.xray = 0.0                # 0 … 1: the outer coats turn see-through (retina seen from outside)
        self.scan: float | None = None # slit position: 0 top … 1 bottom of the photo
        self.scan_dim = 1.0            # darkness of the not yet scanned part (0 … 1)
        self.scan_beam = 1.0           # opacity of the slit beam in the section view
        self.fov_sweep = 0.0           # 0 … 1: the field-of-view rays open from the posterior pole
        self.fov_alpha = 0.0           # opacity of the rays and the angle label (section view)
        self.fov_ring = 0.0            # the edge of the photographed field marked on the retina
        self.black = False             # plain black background (presentation)
        self.yaw, self.pitch, self.dist = 38.0, 18.0, self.DIST0
        self.target = np.zeros(3)      # orbit pivot (outside): moves toward what is zoomed into
        self.in_yaw, self.in_pitch, self.in_fov, self.in_z = 0.0, 0.0, self.FOV0, 0.35
        self._drag: QPointF | None = None
        self._drag_kind = ""
        self._ok = False
        self._meshes: dict = {}
        self._keys: dict = {}          # what the dynamic meshes were built for
        self._stale: list = []         # meshes to delete once a context is current
        self._loc: dict = {}
        self._model_tex: dict = {}
        self._rim_cache: tuple = (None, {})
        self._clip_ok = False
        warm_up_textures()

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
                    roll_deg=None, radial_c=None) -> None:
        if radial_c is not None:
            self.radial_c = float(radial_c)
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
                                     self.projection, self.viewpoint, math.radians(self.roll_deg),
                                     c=self.radial_c)
        if p is None:
            # disc ≈ 4.5 mm nasal of the fovea ≈ 21.5° at the eye centre, slightly superior
            phi = 0.0 if laterality != "OS" else math.pi
            p = proj.sphere_point(math.radians(21.5), phi + (0.06 if laterality != "OS" else -0.06))
        self.disc_dir = np.asarray(p, np.float64)
        self.update()

    def set_detail(self, detail: str) -> None:
        """간단히 ("simple") or 자세히 ("detailed")."""
        if detail in self.DETAILS and detail != self.detail:
            self.detail = detail
            self.update()

    def set_mode(self, mode: str) -> None:
        """외부 ("outside") or 내부 ("inside")."""
        self.mode = mode
        self._view_changed()

    def reset_view(self) -> None:
        self.yaw, self.pitch, self.dist = 38.0, 18.0, self.DIST0
        self.target = np.zeros(3)
        self.in_yaw, self.in_pitch, self.in_fov = 0.0, 0.0, self.FOV0
        self._view_changed()

    def front_view(self) -> None:
        self.yaw, self.pitch, self.dist = 0.0, 0.0, self.DIST0
        self.target = np.zeros(3)
        self._view_changed()

    # -- 세로 단면 · 망막 투시 · 슬릿 스캔 ------------------------------------------
    def meridian(self) -> np.ndarray:
        """Direction of the photo's vertical meridian (image up) on the eye: +y turned by the roll."""
        r = math.radians(self.roll_deg)
        return np.array([math.sin(r), math.cos(r), 0.0])

    def half_plane(self) -> tuple[np.ndarray, float]:
        """Section plane of 세로 단면: unit normal ``k`` into the kept half and offset ``off``;
        points with ``p·k < -off`` are cut away. The plane holds the optical axis and the
        vertical meridian, and the half with the optic disc stays."""
        m = self.meridian()
        k = np.cross(m, (0.0, 0.0, 1.0))
        if self.disc_dir is not None and abs(float(self.disc_dir @ k)) > 1e-6:
            k = k if float(self.disc_dir @ k) > 0 else -k
        elif self.laterality == "OS":
            k = -k
        return k, 1.05 * (1.0 - min(1.0, max(0.0, self.half)))

    def _half_on(self) -> bool:
        return self.mode == "outside" and self.half > 1e-3

    def pose(self) -> dict:
        return {"yaw": self.yaw, "pitch": self.pitch, "dist": self.dist, "target": tuple(self.target)}

    def set_pose(self, yaw: float, pitch: float, dist: float, target=(0.0, 0.0, 0.0)) -> None:
        self.yaw, self.pitch, self.dist = yaw % 360.0, max(-89.0, min(89.0, pitch)), dist
        self.target = np.asarray(target, np.float64)
        self._view_changed()

    def _fit(self, dist: float, half_width: float) -> float:
        """``dist``, or farther when the view is too narrow for ``half_width`` (eye radii) across."""
        aspect = max(self.width(), 1) / max(self.height(), 1)
        return max(dist, half_width / (math.tan(math.radians(19.0)) * aspect) + 0.45)

    @staticmethod
    def _pose_from(d, dist: float, target=(0.0, 0.0, 0.0)) -> dict:
        d = _unit(d)
        return {"yaw": math.degrees(math.atan2(d[0], d[2])) % 360.0,
                "pitch": math.degrees(math.asin(max(-1.0, min(1.0, d[1])))), "dist": dist,
                "target": tuple(float(x) for x in target)}

    def section_pose(self) -> dict:
        """Side view onto the section face: the posterior pole on one side, the cornea on the other
        (OD: cornea to the right), image up = up — so the slit runs down the photo and the eye alike."""
        k, _ = self.half_plane()
        return self._pose_from(-k, self._fit(3.6, 1.3), (0.0, 0.0, 0.12))

    def showcase_pose(self) -> dict:
        """Oblique view from the front, below and the cut side: the retina with the macula and the disc
        inside the opened eye, the iris and cornea beside it (the end of the 슬릿 스캔 presentation)."""
        k, _ = self.half_plane()
        return self._pose_from(-0.70 * k + np.array([0.0, -0.25, 0.65]), self._fit(3.8, 1.2))

    def scan_theta(self, s: float) -> tuple[float, float]:
        """Retinal angle (from the posterior pole) and side (+1 superior, -1 inferior) that the
        slit at ``s`` (0 top … 1 bottom of the photo) reaches on the vertical meridian."""
        dy = 1.0 - 2.0 * min(1.0, max(0.0, s))
        tmax = self.theta_max
        th = proj.theta_of_rho(min(1.0, abs(dy)), tmax, self.projection, self.viewpoint, c=self.radial_c)
        return th, (1.0 if dy >= 0 else -1.0)

    @property
    def magnification(self) -> float:
        """How much larger than in the start view things appear (outside: distance, inside: field)."""
        if self.mode == "inside":
            return math.tan(math.radians(self.FOV0) / 2) / math.tan(math.radians(self.in_fov) / 2)
        return self.DIST0 / self.dist

    def _view_changed(self) -> None:
        self.zoomChanged.emit(self.magnification)
        self.update()

    @property
    def theta_max(self) -> float:
        return proj.theta_max(self.fov_deg, self.fov_type, self.viewpoint)

    # -- GL ------------------------------------------------------------------
    def initializeGL(self) -> None:
        try:
            from OpenGL import GL as gl
            self.gl = gl
            # a new context (e.g. after re-parenting) owns none of the old buffers
            self._loc.clear()
            self._meshes, self._keys, self._stale = {}, {}, []
            self._tex = None
            self._prog = {
                "bg": self._program(_glsl(BG_VERT), _glsl(BG_FRAG)),
                "sclera": self._program(_glsl(VERT), _glsl(COMMON, SCLERA_LIB, MAPPING_LIB, RETINA_LIB,
                                                            SCLERA_FRAG)),
                "cornea": self._program(_glsl(VERT), _glsl(COMMON, SCLERA_LIB, IRIS_LIB, CORNEA_FRAG)),
                "wall": self._program(_glsl(VERT), _glsl(COMMON, MAPPING_LIB, RETINA_LIB, WALL_FRAG)),
                "tissue": self._program(_glsl(VERT), _glsl(COMMON, IRIS_LIB, WALL_LAYERS_LIB, TISSUE_FRAG)),
                "clear": self._program(_glsl(VERT), _glsl(COMMON, CLEAR_FRAG)),
                "section": self._program(_glsl(VERT), _glsl(COMMON, WALL_LAYERS_LIB, SECTION_FRAG)),
                "simple_eye": self._program(_glsl(VERT), _glsl(MAPPING_LIB, SIMPLE_EYE_FRAG)),
                "simple_solid": self._program(_glsl(VERT), _glsl(SIMPLE_SOLID_FRAG)),
            }
            for p in self._prog.values():
                gl.glUseProgram(p)
                for name, unit in _UNITS.items():
                    loc = gl.glGetUniformLocation(p, "u_" + name)
                    if loc >= 0:
                        gl.glUniform1i(loc, unit)
            self._max_tex = int(gl.glGetIntegerv(gl.GL_MAX_TEXTURE_SIZE))
            self._model_tex = {}          # made on the first detailed frame
            quad = em.MeshData(np.array([[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]], np.float32),
                               np.zeros((4, 3), np.float32), np.array([0, 1, 2, 0, 2, 3], np.uint32))
            for name, mesh in (("bg", quad), ("sclera", em.sphere_mesh()), ("cornea", em.cornea_mesh()),
                               ("wall", em.inner_wall_mesh()), ("iris", em.iris_mesh()),
                               ("angle", em.angle_mesh()), ("lens", em.lens_mesh()),
                               ("zonules", em.zonule_lines()),
                               # out to the iris root: in the closed eye the limbus hides the edge,
                               # in 세로 단면 it meets the wall without a gap
                               ("simple_iris", em._annulus(0.0, em.IRIS_ROOT_R + 0.004, em.IRIS_Z, 160))):
                self._meshes[name] = _Mesh(gl, mesh)
            try:                                  # fixed-function clip planes (compatibility profile)
                gl.glMatrixMode(gl.GL_MODELVIEW)
                gl.glLoadIdentity()
                gl.glClipPlane(gl.GL_CLIP_PLANE0, (0.0, 0.0, -1.0, 2.0))
                gl.glClipPlane(gl.GL_CLIP_PLANE1, (1.0, 0.0, 0.0, 2.0))
                self._clip_ok = True
            except Exception:
                self._clip_ok = False
            self._tex_dirty = True
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
        for loc, name in enumerate(("a_pos", "a_nrm", "a_uv")):
            gl.glBindAttribLocation(prog, loc, name)
        gl.glLinkProgram(prog)
        if not gl.glGetProgramiv(prog, gl.GL_LINK_STATUS):
            raise RuntimeError(gl.glGetProgramInfoLog(prog).decode(errors="replace"))
        return prog

    def _make_texture(self, data: np.ndarray):
        gl = self.gl
        h, w = data.shape[:2]
        if max(h, w) > self._max_tex:
            step = int(math.ceil(max(h, w) / self._max_tex))
            data = data[::step, ::step]
            h, w = data.shape[:2]
        data = np.ascontiguousarray(data)
        fmt = gl.GL_RGBA if data.shape[2] == 4 else gl.GL_RGB
        tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
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
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, fmt, w, h, 0, fmt, gl.GL_UNSIGNED_BYTE, data)
        return tex

    def _ensure_model_textures(self) -> None:
        """Anatomical textures of the detailed look (waits for the warm-up thread once)."""
        if not self._model_tex:
            tex = model_textures()
            self._model_tex = {"iris": self._make_texture(tex["iris"]),
                               "scl_a": self._make_texture(tex["sclera_a"]),
                               "scl_p": self._make_texture(tex["sclera_p"]),
                               "peri": self._make_texture(tex["periphery"])}

    def _upload_texture(self) -> None:
        gl = self.gl
        if self._tex is not None:
            gl.glDeleteTextures([self._tex])
            self._tex = None
        self._tex_dirty = False
        if self._rgba is not None:
            self._tex = self._make_texture(self._rgba)

    def _set(self, prog, **values) -> None:
        """Set uniforms ``u_<name>``: int → 1i, float → 1f, 2/3-vectors, 4×4 matrices."""
        gl = self.gl
        for name, v in values.items():
            loc = self._loc.get((prog, name))
            if loc is None:
                loc = self._loc[(prog, name)] = gl.glGetUniformLocation(prog, "u_" + name)
            if loc < 0:
                continue
            if isinstance(v, (bool, int)):
                gl.glUniform1i(loc, int(v))
            elif isinstance(v, float):
                gl.glUniform1f(loc, v)
            else:
                a = np.asarray(v, np.float32)
                if a.shape == (4, 4):
                    gl.glUniformMatrix4fv(loc, 1, gl.GL_TRUE, a)
                elif a.size == 4:
                    gl.glUniform4f(loc, *(float(x) for x in a))
                elif a.size == 2:
                    gl.glUniform2f(loc, float(a[0]), float(a[1]))
                else:
                    gl.glUniform3f(loc, float(a[0]), float(a[1]), float(a[2]))

    def _dynamic(self, name: str, key, build):
        """Mesh ``name`` rebuilt by ``build()`` whenever ``key`` changes (None: no mesh)."""
        if self._keys.get(name, ()) != key or name not in self._meshes:
            old = self._meshes.pop(name, None)
            if old is not None:
                self._stale.append(old)
            self._keys[name] = key
            data = build()
            if data is not None:
                self._meshes[name] = _Mesh(self.gl, data)
        return self._meshes.get(name)

    def _rim(self, part: str):
        """Section face ``part`` of the current cut (the set is built once per cut)."""
        if self._rim_cache[0] != self.cut:
            self._rim_cache = (self.cut, em.rim_meshes(self.cut))
        return self._rim_cache[1].get(part)

    # -- camera, picking, zoom ------------------------------------------------
    def _view_basis(self):
        """Camera position, forward / right / up unit vectors and vertical field of view (°)."""
        if self.mode == "inside":
            cy_, sy = math.cos(math.radians(self.in_yaw)), math.sin(math.radians(self.in_yaw))
            cp, sp = math.cos(math.radians(self.in_pitch)), math.sin(math.radians(self.in_pitch))
            eye = np.array([0.0, 0.0, self.in_z])
            f, up, fovy = np.array([sy * cp, sp, -cy_ * cp]), (0.0, 1.0, 0.0), self.in_fov
        else:
            cy_, sy = math.cos(math.radians(self.yaw)), math.sin(math.radians(self.yaw))
            cp, sp = math.cos(math.radians(self.pitch)), math.sin(math.radians(self.pitch))
            d = np.array([sy * cp, sp, cy_ * cp])
            eye, f, fovy = self.target + self.dist * d, -d, 38.0
            up = (0.0, 1.0, 0.0) if abs(self.pitch) < 89 else (0.0, 0.0, -1.0)
        r = _unit(np.cross(f, up))
        return eye, f, r, np.cross(r, f), fovy

    def _camera(self, aspect: float):
        eye, f, _, u, fovy = self._view_basis()
        if self.mode == "inside":
            near, far = 0.01, 10.0
        else:
            near, far = max(0.001, min(0.05, 0.02 * self.dist)), self.dist + 6.0
        return perspective(fovy, aspect, near, far) @ look_at(eye, eye + f, u), eye

    def _ray(self, pos: QPointF):
        """Origin and direction of the view ray through widget position ``pos``."""
        eye, f, r, u, fovy = self._view_basis()
        w, h = max(self.width(), 1), max(self.height(), 1)
        t = math.tan(math.radians(fovy) / 2)
        x = (2.0 * pos.x() / w - 1.0) * t * w / h
        y = (1.0 - 2.0 * pos.y() / h) * t
        return eye, _unit(f + r * x + u * y)

    def _pick(self, o: np.ndarray, d: np.ndarray) -> np.ndarray | None:
        """First visible surface along the ray: outer coat, section face, retina (analytic)."""
        r_in = 1.0 if self.detail == "simple" else em.R_RET

        def hits(radius, c=(0.0, 0.0, 0.0)):
            oc = o - np.asarray(c)
            b = float(oc @ d)
            disc = b * b - (float(oc @ oc) - radius * radius)
            if disc < 0:
                return None
            q = math.sqrt(disc)
            return -b - q, -b + q

        if self.mode == "inside":
            h = hits(r_in)
            return None if h is None else o + d * h[1]
        h = hits(1.0)
        if h is None or h[1] <= 0:
            return None
        if self._half_on():                             # 세로 단면: outer coat, section face, far retina
            k, off = self.half_plane()
            r_in = em.R_RET

            def kept(p):
                return float(p @ k) >= -off - 1e-6

            if h[0] > 0 and kept(o + d * h[0]):
                return o + d * h[0]
            dn = float(d @ k)
            if abs(dn) > 1e-9:
                t = (-off - float(o @ k)) / dn
                c = o + d * t
                if t > 0 and r_in * r_in <= float(c @ c) <= 1.0:
                    return c
            hi = hits(r_in)
            if hi is not None and hi[1] > 0 and kept(o + d * hi[1]):
                return o + d * hi[1]
            return None
        if self.cut >= 0.999:                           # closed: sclera or cornea
            p = o + d * max(h[0], 0.0)
            if p[2] > em.LIMBUS_Z:
                hc = hits(em.CORNEA_R, (0.0, 0.0, em.CORNEA_CENTER_Z))
                if hc is not None and hc[0] > 0:
                    return o + d * hc[0]
            return p
        clip = self.cut if self.detail == "simple" else em.cut_plane_z(self.cut)
        if h[0] > 0:                                    # camera outside the globe
            p = o + d * h[0]
            if p[2] <= clip + 1e-6:
                return p                                # outer coat
        if o[2] > clip and d[2] < 0:                    # down through the cut plane: section face?
            c = o + d * ((clip - o[2]) / d[2])
            if r_in * r_in <= float(c @ c) <= 1.0:
                return c
        hi = hits(r_in)                                 # … or the retina beyond the opening
        if hi is not None and hi[1] > 0 and (o + d * hi[1])[2] <= clip:
            return o + d * hi[1]
        return None

    def zoom_at(self, steps: float, pos: QPointF | None = None) -> None:
        """Zoom ``steps`` wheel notches toward what lies under ``pos`` (default: the centre)."""
        if pos is None:
            pos = QPointF(self.width() / 2, self.height() / 2)
        if self.mode == "inside":
            self._zoom_inside(steps, pos)
        else:
            self._zoom_outside(steps, pos)
        self._view_changed()

    def _zoom_outside(self, steps: float, pos: QPointF) -> None:
        # scale the camera–pivot set about the point under the cursor: it stays put on screen
        o, d = self._ray(pos)
        hit = self._pick(o, d)
        anchor = hit if hit is not None else o + d * self.dist
        s = 0.88 ** steps
        reach = float(np.linalg.norm(anchor - o))
        if s < 1.0:                                     # stop short of the surface
            s = max(s, min(1.0, 0.06 / max(reach, 1e-6)), 0.02 / self.dist)
        s = min(s, 12.0 / self.dist)
        if abs(s - 1.0) < 1e-9:
            return
        if s > 1.0 and self.dist * s >= self.DIST0:
            target = self.target * 0.5  # past the start view: the pivot returns to the eye centre
        else:
            target = anchor + (self.target - anchor) * s
            if s > 1.0:                 # zooming out: the pivot drifts back toward the centre
                target = target * (1.0 - 0.5 * min(1.0, max(0.0, (self.dist * s - 1.6) / 1.7)))
        self.target, self.dist = target, self.dist * s

    def _zoom_inside(self, steps: float, pos: QPointF) -> None:
        fov = min(140.0, max(4.0, self.in_fov * (0.88 ** steps)))
        if fov == self.in_fov:
            return
        _, d0 = self._ray(pos)
        self.in_fov = fov
        for _ in range(3):              # turn the view so the same retina stays under the cursor
            _, d1 = self._ray(pos)
            axis = np.cross(d1, d0)
            sa = float(np.linalg.norm(axis))
            if sa < 1e-9:
                break
            k, a = axis / sa, math.atan2(sa, float(d1 @ d0))
            _, f, _, _, _ = self._view_basis()
            f = f * math.cos(a) + np.cross(k, f) * math.sin(a) + k * float(k @ f) * (1 - math.cos(a))
            self.in_pitch = max(-85.0, min(85.0, math.degrees(math.asin(max(-1.0, min(1.0, f[1]))))))
            self.in_yaw = max(-150.0, min(150.0, math.degrees(math.atan2(f[0], -f[2]))))

    def pan(self, dx: float, dy: float) -> None:
        """Move the view by (dx, dy) widget pixels (outside: shift the orbit pivot)."""
        if self.mode == "inside":
            self._look(dx, dy)
            return
        _, _, r, u, fovy = self._view_basis()
        k = 2.0 * self.dist * math.tan(math.radians(fovy) / 2) / max(self.height(), 1)
        t = self.target - r * dx * k + u * dy * k
        n = float(np.linalg.norm(t))
        self.target = t if n <= 1.5 else t * (1.5 / n)
        self.update()

    def _look(self, dx: float, dy: float) -> None:
        if self.mode == "inside":
            k = self.in_fov / max(self.height(), 1)
            self.in_yaw = max(-150.0, min(150.0, self.in_yaw - dx * k))
            self.in_pitch = max(-85.0, min(85.0, self.in_pitch + dy * k))
        else:
            self.yaw = (self.yaw - dx * 0.4) % 360.0
            self.pitch = max(-89.0, min(89.0, self.pitch + dy * 0.4))
        self.update()

    def _overlay_wanted(self) -> bool:
        return self._half_on() and ((self.fov_alpha > 0.005 and self.fov_sweep > 0.0)
                                    or (self.scan is not None and self.scan_beam > 0.005))

    def paintGL(self) -> None:
        if not self._ok:
            return
        if not self._overlay_wanted():
            self._paint_gl()
            return
        # the field-of-view rays, the angle and the slit beam go over the picture (also into
        # grabFramebuffer, so 화면 저장 keeps them)
        painter = QPainter(self)
        painter.beginNativePainting()
        try:
            mvp = self._paint_gl()
            self._release_gl_state()
        finally:
            painter.endNativePainting()
        try:
            self._paint_overlay(painter, mvp)
        finally:
            painter.end()

    def _release_gl_state(self) -> None:
        """Unbind our buffers, attribute arrays and program before QPainter draws (its paint
        engine reads vertices from client memory, which a bound VBO would redirect)."""
        gl = self.gl
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, 0)
        for loc in range(3):
            gl.glDisableVertexAttribArray(loc)
        gl.glUseProgram(0)
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glActiveTexture(gl.GL_TEXTURE0)

    def _mapping_uniforms(self) -> dict:
        """Uniforms of MAPPING_LIB: how the photo lies on the retina, the slit and the field edge."""
        tmax = self.theta_max
        scan = (-1.0, 0.0)
        if self.scan is not None and self.scan_dim > 0.0:
            scan = (self._center[1] + (2.0 * min(1.0, max(0.0, self.scan)) - 1.0) * self._radius[1],
                    float(min(1.0, self.scan_dim)))
        return dict(tmax=tmax, gmax=proj.g(tmax, self.projection, self.viewpoint, tmax=tmax, c=self.radial_c),
                    proj=proj.PROJECTION_INDEX.get(self.projection, 0), d=self.viewpoint, c=self.radial_c,
                    center=self._center, radius=self._radius, roll=math.radians(self.roll_deg),
                    grid=1.0 if self.show_grid else 0.0, has_tex=int(self._tex is not None),
                    scan=scan, fovring=float(self.fov_ring))

    @staticmethod
    def _section_quad(k: np.ndarray, off: float, size: float = 1.16) -> em.MeshData:
        """Square in the section plane ``p·k = -off`` covering the eye (the cornea included)."""
        k = _unit(k)
        e1 = _unit(np.array([0.0, 0.0, 1.0]) - k[2] * k)
        e2 = np.cross(k, e1)
        c = -k * off
        pos = np.array([c + (a * e1 + b * e2) * size for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))], np.float32)
        return em.MeshData(pos, np.tile(-k, (4, 1)).astype(np.float32), np.array([0, 1, 2, 0, 2, 3], np.uint32))

    def _clip_half(self, gl, k: np.ndarray, off: float) -> None:
        """Fixed-function clip plane 1 = the section plane (given with an identity modelview)."""
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glLoadIdentity()
        gl.glClipPlane(gl.GL_CLIP_PLANE1, (float(k[0]), float(k[1]), float(k[2]), float(off) + 2e-4))

    def _paint_gl(self) -> np.ndarray:
        gl = self.gl
        for loc in range(3, 8):          # a QPainter may leave other attribute arrays enabled
            gl.glDisableVertexAttribArray(loc)
        while self._stale:
            self._stale.pop().delete(gl)
        if self._tex_dirty:
            self._upload_texture()
        dpr = self.devicePixelRatioF()
        w, h = max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr))
        gl.glViewport(0, 0, w, h)
        if self.black:
            gl.glClearColor(0.0, 0.0, 0.0, 1.0)
        else:
            gl.glClearColor(0.105, 0.115, 0.13, 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glDisable(gl.GL_BLEND)
        inside = self.mode == "inside"
        half = self._half_on()
        closed = not inside and not half and self.cut >= 0.999
        mvp, campos = self._camera(w / h)
        if self.detail == "simple":
            self._paint_simple(gl, mvp, campos, inside, closed, half)
            return mvp
        try:
            self._ensure_model_textures()
        except Exception as exc:  # e.g. out of memory: keep showing the eye, the simple way
            self.detail = "simple"
            self.glError.emit(f"자세히 보기를 준비할 수 없어 간단히 보기로 바꿨습니다: {exc}")
            self._paint_simple(gl, mvp, campos, inside, closed, half)
            return mvp

        for name, unit in _UNITS.items():
            gl.glActiveTexture(gl.GL_TEXTURE0 + unit)
            gl.glBindTexture(gl.GL_TEXTURE_2D, (self._tex or 0) if name == "tex" else self._model_tex[name])
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glEnable(gl.GL_DEPTH_TEST)

        if inside:
            lights = {"key": _unit((0.15, 0.25, 1.0)), "kx": (1.0, 0.0, 0.0), "ky": (0.0, 1.0, 0.0),
                      "fill": (0.0, 0.0, 1.0), "fx": (1.0, 0.0, 0.0), "fy": (0.0, 1.0, 0.0)}
        else:
            lights = studio_lights(campos)
        k, off = self.half_plane() if half else (np.zeros(3), 1.0)
        clip = 2.0 if closed or inside or half else float(self.cut)
        common = dict(mvp=mvp, campos=campos, cut=clip, mirror=int(self.laterality == "OS"),
                      hk=k, hoff=float(off), **lights)
        mapping = self._mapping_uniforms()

        def use(name, **extra):
            p = self._prog[name]
            gl.glUseProgram(p)
            self._set(p, **common, **extra)
            return p

        # The cut also clips geometry before rasterising (the shaders still discard
        # per pixel, so a driver without clip planes draws the same picture, slower).
        # The planes are given with an identity modelview, i.e. in object space.
        clip_plane = self._clip_ok and not (closed or inside or half)
        half_clip = self._clip_ok and half
        if clip_plane:
            gl.glMatrixMode(gl.GL_MODELVIEW)
            gl.glLoadIdentity()
            gl.glClipPlane(gl.GL_CLIP_PLANE0, (0.0, 0.0, -1.0, clip + 2e-4))
        if half_clip:
            self._clip_half(gl, k, off)
            gl.glEnable(gl.GL_CLIP_PLANE1)

        # Opaque surfaces front to back: what hides the costly retina goes first,
        # so the depth test rejects the hidden part of the inner wall.
        if not inside:
            # -- outer coat (망막 투시: the retina seen through it) ------------------
            use("sclera", clip=float(em.LIMBUS_Z if closed or half else min(self.cut, em.LIMBUS_Z)),
                disc=self.disc_dir if self.disc_dir is not None else (0.37, 0.02, -0.93),
                xray=float(self.xray), **mapping)
            self._meshes["sclera"].draw(gl)
            if clip_plane:
                gl.glEnable(gl.GL_CLIP_PLANE0)
            # -- section faces of the cut -----------------------------------------
            if half:                       # one analytic face; it lies on the plane, so it is not clipped
                if half_clip:
                    gl.glDisable(gl.GL_CLIP_PLANE1)
                use("section", part=0)
                self._dynamic("half_face", (tuple(np.round(k, 6)), round(float(off), 5)),
                              lambda: self._section_quad(k, off)).draw(gl)
                if half_clip:
                    gl.glEnable(gl.GL_CLIP_PLANE1)
            elif not closed:
                p = use("tissue", rim_post=int(em.cut_plane_z(self.cut) < em.Z_ORA))
                for part, kind in (("wall", 0), ("iris", 1)):
                    mesh = self._dynamic("rim_" + part, round(self.cut, 4), lambda part=part: self._rim(part))
                    if mesh is not None:
                        self._set(p, kind=kind)
                        mesh.draw(gl)
            # -- optic nerve and muscles ------------------------------------------
            if self.show_nerve and self.disc_dir is not None:
                use("tissue", kind=4)
                self._dynamic("nerve", (tuple(self.disc_dir), self.laterality),
                              lambda: em.nerve_mesh(self.disc_dir, self.laterality)).draw(gl)
            if self.show_muscles:
                use("tissue", kind=5)
                self._dynamic("muscles", self.laterality, lambda: em.muscle_mesh(self.laterality)).draw(gl)
            # -- cornea (ray traced: iris, pupil, limbus, catchlight) --------------
            if closed:
                use("cornea")
                self._meshes["cornea"].draw(gl)

        # -- iris, chamber angle, retina and inner wall ------------------------------
        if not closed:
            if inside or half or self.cut > em.IRIS_BACK_Z:      # otherwise cut away entirely
                use("tissue", kind=2)
                self._meshes["iris"].draw(gl)
                self._set(self._prog["tissue"], kind=3)
                self._meshes["angle"].draw(gl)
            if half:
                open_n, open_ = -k, float(off)
            else:
                open_n, open_ = (0.0, 0.0, 1.0), float(em.cut_plane_z(self.cut))
            use("wall", inside=int(inside), light=lights["key"] if not inside else (0.0, 0.0, 1.0),
                open_n=open_n, open=open_, **mapping)
            self._meshes["wall"].draw(gl)

        # -- background, only where nothing was drawn (before the transparent media) --
        if clip_plane:
            gl.glDisable(gl.GL_CLIP_PLANE0)
        if half_clip:
            gl.glDisable(gl.GL_CLIP_PLANE1)
        gl.glDepthMask(gl.GL_FALSE)
        gl.glUseProgram(self._prog["bg"])
        self._set(self._prog["bg"], aspect=float(w / h), black=int(self.black))
        self._meshes["bg"].draw(gl)
        gl.glDepthMask(gl.GL_TRUE)

        # -- transparent media ----------------------------------------------------
        if inside or half or (not closed and self.cut > em.LENS_BACK_Z):
            gl.glEnable(gl.GL_BLEND)
            # Keep destination alpha at 1: QOpenGLWidget composites its FBO as
            # premultiplied, so alpha < 1 here shows as colour artifacts.
            gl.glBlendFuncSeparate(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA, gl.GL_ZERO, gl.GL_ONE)
            gl.glDepthMask(gl.GL_FALSE)
            if clip_plane:
                gl.glEnable(gl.GL_CLIP_PLANE0)
            if half_clip:
                gl.glEnable(gl.GL_CLIP_PLANE1)
            p = use("clear", kind=2)
            self._meshes["zonules"].draw(gl)
            self._set(p, kind=0)
            gl.glEnable(gl.GL_CULL_FACE)
            for face in (gl.GL_FRONT, gl.GL_BACK):        # far side of the lens first
                gl.glCullFace(face)
                self._meshes["lens"].draw(gl)
            gl.glDisable(gl.GL_CULL_FACE)
            if half:
                # the lens in section, translucent; then the cornea, cut open: a clear shell
                if half_clip:
                    gl.glDisable(gl.GL_CLIP_PLANE1)
                use("section", part=1)
                self._meshes["half_face"].draw(gl)
                if half_clip:
                    gl.glEnable(gl.GL_CLIP_PLANE1)
                p = use("clear", kind=3)
                self._meshes["cornea"].draw(gl)
            elif not inside:
                lens_cap = self._dynamic("rim_lens", round(self.cut, 4), lambda: self._rim("lens"))
                if lens_cap is not None:
                    self._set(p, kind=1)
                    lens_cap.draw(gl)
            gl.glDepthMask(gl.GL_TRUE)
            gl.glDisable(gl.GL_BLEND)
            if clip_plane:
                gl.glDisable(gl.GL_CLIP_PLANE0)
            if half_clip:
                gl.glDisable(gl.GL_CLIP_PLANE1)
        return mvp

    def _paint_simple(self, gl, mvp, campos, inside: bool, closed: bool, half: bool = False) -> None:
        """The original light-weight model (``detail == "simple"``); 세로 단면 adds the inner wall,
        the chamber angle, the lens and the section face of the anatomical model."""
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._tex or 0)
        light = campos / (np.linalg.norm(campos) or 1.0) + np.array([-0.35, 0.55, 0.0])
        light = _unit((0.0, 0.0, 1.0) if inside else light)
        k, off = self.half_plane() if half else (np.zeros(3), 1.0)
        half_clip = self._clip_ok and half
        p = self._prog["simple_eye"]
        gl.glUseProgram(p)
        self._set(p, mvp=mvp, cut=2.0 if closed or half else float(self.cut),
                  limbus=em.LIMBUS_Z if closed or half else 2.0, inside=int(inside), light=light,
                  side=1 if half else 0, xray=0.0 if inside else float(self.xray), hk=k, hoff=float(off),
                  **self._mapping_uniforms())
        self._meshes["sclera"].draw(gl)
        if inside:
            return
        if half_clip:
            self._clip_half(gl, k, off)
            gl.glEnable(gl.GL_CLIP_PLANE1)
        if half:                                           # the retina on the anatomical inner wall
            self._set(p, side=2)
            self._meshes["wall"].draw(gl)
        s = self._prog["simple_solid"]
        gl.glUseProgram(s)
        self._set(s, mvp=mvp, light=light, campos=campos, hk=k, hoff=float(off))
        if self.show_nerve and self.disc_dir is not None:
            self._set(s, kind=0, color=(0.92, 0.86, 0.74, 1.0))
            self._dynamic("simple_nerve", tuple(self.disc_dir), lambda: em.simple_nerve_mesh(self.disc_dir)).draw(gl)
        if closed or half:
            self._set(s, kind=1, color=(1.0, 1.0, 1.0, 1.0))
            self._meshes["simple_iris"].draw(gl)
        if half:
            self._set(s, kind=0, color=(0.30, 0.20, 0.15, 1.0))
            self._meshes["angle"].draw(gl)
            if half_clip:
                gl.glDisable(gl.GL_CLIP_PLANE1)
            sec = self._prog["section"]
            gl.glUseProgram(sec)
            self._set(sec, mvp=mvp, campos=campos, part=0, cut=2.0, **studio_lights(campos))
            self._dynamic("half_face", (tuple(np.round(k, 6)), round(float(off), 5)),
                          lambda: self._section_quad(k, off)).draw(gl)
            if half_clip:
                gl.glEnable(gl.GL_CLIP_PLANE1)
            gl.glUseProgram(s)
        if closed or half:
            gl.glEnable(gl.GL_BLEND)
            # Keep destination alpha at 1: QOpenGLWidget composites its FBO as
            # premultiplied, so alpha < 1 here shows as colour artifacts.
            gl.glBlendFuncSeparate(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA, gl.GL_ZERO, gl.GL_ONE)
            gl.glDepthMask(gl.GL_FALSE)
            if half:
                self._set(s, kind=2, color=(1.0, 1.0, 1.0, 0.16))
                self._meshes["lens"].draw(gl)
                sec = self._prog["section"]
                gl.glUseProgram(sec)
                self._set(sec, part=1)
                if half_clip:
                    gl.glDisable(gl.GL_CLIP_PLANE1)
                self._meshes["half_face"].draw(gl)
                if half_clip:
                    gl.glEnable(gl.GL_CLIP_PLANE1)
                gl.glUseProgram(s)
            self._set(s, kind=2, color=(1.0, 1.0, 1.0, 0.12))
            self._meshes["cornea"].draw(gl)
            gl.glDepthMask(gl.GL_TRUE)
            gl.glDisable(gl.GL_BLEND)
        if half_clip:
            gl.glDisable(gl.GL_CLIP_PLANE1)

    def _paint_overlay(self, painter: QPainter, mvp: np.ndarray) -> None:
        """세로 단면: the field-of-view rays from the eye centre with the angle (e.g. "176°") and the
        slit beam through the pupil, drawn over the section face while it faces the camera."""
        k, off = self.half_plane()
        eye = self._view_basis()[0]
        vis = _smooth(0.0, 0.3, (-float(eye @ k) - off) / max(float(np.linalg.norm(eye)), 1e-6))
        if vis <= 0.0:
            return
        w, h = self.width(), self.height()

        def to_screen(p):
            v = mvp @ np.array([p[0], p[1], p[2], 1.0], np.float32)
            if v[3] <= 1e-6:
                return None
            return QPointF((v[0] / v[3] + 1.0) * 0.5 * w, (1.0 - v[1] / v[3]) * 0.5 * h)

        m, zax = self.meridian(), np.array([0.0, 0.0, 1.0])
        base = -k * off

        def on_plane(t: float, r: float):    # angle t from the posterior pole (+: image up), radius r
            return base + r * (math.sin(t) * m - math.cos(t) * zax)

        centre, edge = to_screen(base), to_screen(on_plane(math.pi / 2, 1.0))
        if centre is None or edge is None:
            return
        eye_px = math.hypot(edge.x() - centre.x(), edge.y() - centre.y())     # eye radius on screen
        lw = max(1.4, eye_px / 95.0)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        def glow(points, color: QColor, alpha: float, width: float) -> None:
            pts = [q for q in points if q is not None]
            if len(pts) < 2 or alpha <= 0.0:
                return
            path = QPainterPath(pts[0])
            for q in pts[1:]:
                path.lineTo(q)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for wmul, a in ((4.5, 0.12), (2.4, 0.28), (1.0, 1.0)):
                c = QColor(color)
                c.setAlphaF(min(1.0, alpha * a))
                pen = QPen(c, width * wmul)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                painter.drawPath(path)

        def spot(p: QPointF, color: QColor, alpha: float, radius: float) -> None:
            painter.setPen(Qt.PenStyle.NoPen)
            for rmul, a in ((2.6, 0.18), (1.6, 0.4), (1.0, 1.0)):
                c = QColor(color)
                c.setAlphaF(min(1.0, alpha * a))
                painter.setBrush(c)
                painter.drawEllipse(p, radius * rmul, radius * rmul)

        if self.scan is not None and self.scan_beam > 0.005:      # slit beam: in through the pupil
            a = self.scan_beam * vis
            th, side = self.scan_theta(self.scan)
            hit = to_screen(on_plane(side * th, em.R_RET))
            glow([to_screen(base + zax * 1.9), to_screen(base + zax * (em.IRIS_Z + 0.01)), hit],
                 self.BEAM_COLOR, a, lw * 1.15)
            if hit is not None:
                spot(hit, QColor(255, 226, 190), a, lw * 1.6)

        if self.fov_alpha > 0.005 and self.fov_sweep > 0.0:      # field of view at the eye centre
            a = self.fov_alpha * vis
            th = self.theta_max * min(1.0, self.fov_sweep)
            for side in (1.0, -1.0):
                glow([centre, to_screen(on_plane(side * th, em.R_RET))], self.FOV_COLOR, a, lw)
            glow([to_screen(on_plane(t, 0.2)) for t in np.linspace(-th, th, 72)], self.FOV_COLOR, a * 0.9, lw * 0.8)
            spot(centre, self.FOV_COLOR, a, lw * 1.2)
            la = a * _smooth(0.55, 1.0, self.fov_sweep)
            anchor = to_screen(base + zax * 0.33)
            if la > 0.01 and anchor is not None:
                font = QFont(self.font())
                font.setBold(True)
                font.setPixelSize(max(14, int(eye_px * 0.24)))
                small = QFont(self.font())
                small.setPixelSize(max(10, int(eye_px * 0.075)))
                big = QPainterPath()
                big.addText(0.0, 0.0, font, f"{math.degrees(2.0 * self.theta_max):.0f}°")
                sub = QPainterPath()
                sub.addText(0.0, 0.0, small, "안구 중심각")
                bb, sb = big.boundingRect(), sub.boundingRect()
                gap = small.pixelSize() * 0.45
                top = anchor.y() - (bb.height() + gap + sb.height()) / 2
                big.translate(anchor.x() - bb.center().x(), top - bb.top())
                sub.translate(anchor.x() - sb.center().x(), top + bb.height() + gap - sb.top())
                outline = QColor(0, 16, 28)
                outline.setAlphaF(min(1.0, la * 0.85))
                fill = QColor(self.FOV_COLOR)
                fill.setAlphaF(min(1.0, la))
                for path, ow in ((big, max(2.0, font.pixelSize() / 9.0)), (sub, max(1.5, small.pixelSize() / 5.0))):
                    painter.strokePath(path, QPen(outline, ow, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                                  Qt.PenJoinStyle.RoundJoin))
                    painter.fillPath(path, fill)

    # -- interaction -----------------------------------------------------------
    # left drag: rotate (inside: look around) · right drag up/down: zoom where the
    # drag started · middle drag or Shift+left drag: move · wheel: zoom at the
    # cursor · double click / 0: start view · + / -: zoom at the centre
    def mousePressEvent(self, e):
        self.interacted.emit()
        self._drag = self._press = e.position()
        if e.button() == Qt.MouseButton.RightButton:
            self._drag_kind = "zoom"
        elif e.button() == Qt.MouseButton.MiddleButton or e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._drag_kind = "pan"
        else:
            self._drag_kind = "rotate"

    def mouseReleaseEvent(self, e):
        self._drag = None

    def mouseMoveEvent(self, e):
        if self._drag is None:
            return
        d = e.position() - self._drag
        self._drag = e.position()
        if self._drag_kind == "zoom":
            self.zoom_at(-d.y() / 40.0, self._press)
        elif self._drag_kind == "pan":
            self.pan(d.x(), d.y())
        else:
            self._look(d.x(), d.y())

    def wheelEvent(self, e):
        self.interacted.emit()
        self.zoom_at(e.angleDelta().y() / 120.0, e.position())

    def pinch(self, value: float, pos: QPointF) -> None:
        """Trackpad pinch (macOS): magnify by ``1 + value`` toward ``pos``
        (one wheel notch magnifies by 1 / 0.88)."""
        if value > -1.0:
            self.interacted.emit()
            self.zoom_at(math.log1p(value) / -math.log(0.88), pos)

    def event(self, e):
        if (e.type() == QEvent.Type.NativeGesture
                and e.gestureType() == Qt.NativeGestureType.ZoomNativeGesture):
            self.pinch(e.value(), e.position())
            return True
        return super().event(e)

    def mouseDoubleClickEvent(self, e):
        self.interacted.emit()
        self.reset_view()

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Plus,
                 Qt.Key.Key_Equal, Qt.Key.Key_Minus, Qt.Key.Key_Underscore, Qt.Key.Key_0, Qt.Key.Key_Home):
            self.interacted.emit()
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
        elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_at(2.0)
        elif k in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            self.zoom_at(-2.0)
        elif k in (Qt.Key.Key_0, Qt.Key.Key_Home):
            self.reset_view()
        else:
            super().keyPressEvent(e)
