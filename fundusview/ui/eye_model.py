"""Anatomical model eye for the 3D view: dimensions, meshes and procedural textures.

Units: 1.0 = 12 mm, the outer radius of the sclera. The globe centre is the
origin, +z points to the cornea and -z to the posterior pole; for a right eye
(OD) +x is nasal and +y superior, a left eye mirrors x. The retina is the
inner surface of the eye wall (radius ``R_RET``); the fundus photo is mapped
onto it by direction from the centre, exactly as in ``projection.py``.

Everything here is numpy / Pillow only, so it runs (and is tested) without
OpenGL. Textures are generated once per process from fixed seeds:

* iris        — Cartesian RGBA over the iris disc, alpha = stromal relief
* sclera      — two stereographic maps (anterior / posterior hemisphere) of
                the outer coat with its conjunctival, episcleral, anterior
                ciliary and vortex vessels
* periphery   — stereographic map of the fundus beyond the photographed field
                (choroidal tessellation, peripheral retinal vessels, ora)

Stereographic maps are conformal (vessels keep their width in every
direction) and have no seam; the shaders look them up with one division.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

MM = 1.0 / 12.0

# eye wall (≈ 0.7 mm sclera, 0.25 mm choroid, 0.25 mm retina)
SCLERA_T = 0.058
CHOROID_T = 0.021
RETINA_T = 0.021
R_RET = 1.0 - SCLERA_T - CHOROID_T - RETINA_T

# anterior segment
LIMBUS_Z = 0.877                              # corneal opening: 11.5 mm cornea
LIMBUS_R = math.sqrt(1.0 - LIMBUS_Z ** 2)
LIMBUS_ALPHA = math.asin(LIMBUS_R)            # limbus, angle from the anterior pole
LIMBUS_INNER_R = 0.42                         # inner edge of the corneoscleral junction
CORNEA_CENTER_Z, CORNEA_R = 0.439, 0.65       # 7.8 mm anterior curvature
N_AQUEOUS = 1.336
IRIS_Z = 0.83                                 # front of the iris: ≈ 3.1 mm anterior chamber
IRIS_BACK_Z = 0.80
IRIS_ROOT_R = 0.52
PUPIL_R = 0.15                                # 3.6 mm pupil
LENS_R = 0.40                                 # 9.6 mm diameter, 4 mm thick
LENS_EQ_Z = 0.66
LENS_FRONT_H, LENS_BACK_H = 0.125, 0.20
LENS_FRONT_Z = LENS_EQ_Z + LENS_FRONT_H
LENS_BACK_Z = LENS_EQ_Z - LENS_BACK_H
LENS_FRONT_CURV = 10.0 * MM                   # anterior lens radius (Purkinje III image)

# ora serrata and ciliary body
ORA_THETA = math.radians(122.0)               # from the posterior pole
Z_ORA = -R_RET * math.cos(ORA_THETA)
CILIARY_PROCESSES = 72
PLICATA_Z = (0.62, 0.79)
PROCESS_HEIGHT = 0.08

NERVE_R = 0.19                                # optic nerve with its sheaths (≈ 4.5 mm)

# stereographic texture maps: half-size in map units (tan of half the covered angle)
SCLERA_MAP_XMAX = math.tan(math.radians(50.0))      # each hemisphere map reaches 100° from its pole
PERI_MAP_XMAX = math.tan(math.radians(62.5))        # fundus map reaches 125° (past the ora)

# Rectus muscles (OD): meridian (0° nasal, 90° superior), limbus→insertion,
# insertion width, tendon length and arc of contact, all in mm.
RECTI = (
    ("MR", 0.0, 5.5, 10.3, 3.7, 7.0),
    ("SR", 90.0, 7.7, 10.6, 5.8, 7.0),
    ("LR", 180.0, 6.9, 9.2, 8.8, 12.0),
    ("IR", 270.0, 6.5, 9.8, 5.5, 7.0),
)


# ---------------------------------------------------------------------------
# meshes
# ---------------------------------------------------------------------------
@dataclass
class MeshData:
    pos: np.ndarray                  # (n, 3) float32
    nrm: np.ndarray                  # (n, 3) float32
    idx: np.ndarray                  # (m,) uint32 — triangles, or line pairs when ``lines``
    uv: np.ndarray | None = None     # (n, 2) float32
    lines: bool = False

    def mirrored_x(self) -> "MeshData":
        s = np.array([-1.0, 1.0, 1.0], np.float32)
        return MeshData(self.pos * s, self.nrm * s, self.idx, self.uv, self.lines)


def _mesh(pos, nrm, idx, uv=None, lines=False) -> MeshData:
    return MeshData(np.ascontiguousarray(pos, np.float32), np.ascontiguousarray(nrm, np.float32),
                    np.ascontiguousarray(idx, np.uint32),
                    None if uv is None else np.ascontiguousarray(uv, np.float32), lines)


def merge(*meshes: MeshData) -> MeshData:
    meshes = [m for m in meshes if m is not None]
    offs = np.cumsum([0] + [len(m.pos) for m in meshes[:-1]])
    uv = None
    if any(m.uv is not None for m in meshes):
        uv = np.concatenate([m.uv if m.uv is not None else np.zeros((len(m.pos), 2), np.float32)
                             for m in meshes])
    return _mesh(np.concatenate([m.pos for m in meshes]), np.concatenate([m.nrm for m in meshes]),
                 np.concatenate([m.idx + o for m, o in zip(meshes, offs)]), uv, meshes[0].lines)


def _grid_indices(rows: int, cols: int) -> np.ndarray:
    """Triangles of a (rows+1) × (cols+1) vertex grid."""
    w = cols + 1
    i = np.arange(rows)[:, None] * w
    j = np.arange(cols)[None, :]
    a, b, c, d = i + j, i + w + j, i + w + j + 1, i + j + 1
    return np.stack([a, b, c, a, c, d], axis=-1).reshape(-1)


def sphere_mesh(n_lat: int = 128, n_lon: int = 256, a_max: float = math.pi,
                center=(0.0, 0.0, 0.0), radius: float = 1.0) -> MeshData:
    """Sphere (or cap up to polar angle ``a_max`` from +z), triangles CCW seen from outside."""
    a = np.linspace(0.0, a_max, n_lat + 1)
    b = np.linspace(0.0, 2 * math.pi, n_lon + 1)
    A, B = np.meshgrid(a, b, indexing="ij")
    nrm = np.stack([np.sin(A) * np.cos(B), np.sin(A) * np.sin(B), np.cos(A)], axis=-1).reshape(-1, 3)
    return _mesh(nrm * radius + np.asarray(center), nrm, _grid_indices(n_lat, n_lon))


def revolve(r, z, n_seg: int, normals=None, relief=None, uv_s=None) -> MeshData:
    """Surface of revolution of the profile ``(r[i], z[i])`` about the z axis.

    ``normals`` are the profile normals ``(nr, nz)``; with ``relief(z, phi)``
    (an inward radial displacement) the normals are taken from the displaced
    grid instead, oriented like the profile normals.
    """
    r, z = np.asarray(r, np.float64), np.asarray(z, np.float64)
    phi = np.linspace(0.0, 2 * math.pi, n_seg + 1)
    R = np.repeat(r[:, None], n_seg + 1, axis=1)
    Z = np.repeat(z[:, None], n_seg + 1, axis=1)
    if relief is not None:
        R = R - relief(Z, phi[None, :])
    c, s = np.cos(phi)[None, :], np.sin(phi)[None, :]
    P = np.stack([R * c, R * s, Z], axis=-1)
    nr, nz = normals
    N0 = np.stack([nr[:, None] * c, nr[:, None] * s, np.repeat(nz[:, None], n_seg + 1, axis=1)], axis=-1)
    if relief is not None:
        dPi = np.gradient(P, axis=0)
        dPj = np.gradient(P, axis=1)
        dPj[:, 0] = dPj[:, -1] = P[:, 1] - P[:, -2]          # periodic seam
        N = np.cross(dPi, dPj)
        ln = np.linalg.norm(N, axis=-1, keepdims=True)
        N = np.where(ln > 1e-12, N / np.maximum(ln, 1e-12), N0)
        N *= np.sign(np.sum(N * N0, axis=-1, keepdims=True) + 1e-12)
    else:
        N = N0
    uv = None
    if uv_s is not None:
        U, V = np.meshgrid(np.asarray(uv_s, np.float64), phi / (2 * math.pi), indexing="ij")
        uv = np.stack([U, V], axis=-1).reshape(-1, 2)
    return _mesh(P.reshape(-1, 3), N.reshape(-1, 3), _grid_indices(len(r) - 1, n_seg), uv)


def _profile_normals(r, z, flip: bool = False):
    """Unit normals ``(-dz, dr)`` of a profile polyline (left of the direction of travel)."""
    dr, dz = np.gradient(np.asarray(r, np.float64)), np.gradient(np.asarray(z, np.float64))
    n = np.hypot(dr, dz)
    n[n == 0] = 1.0
    nr, nz = -dz / n, dr / n
    return (-nr, -nz) if flip else (nr, nz)


# -- inner wall: retina, ora serrata, pars plana, pars plicata --------------
_ANT_Z = np.array([Z_ORA, 0.55, 0.62, 0.66, 0.70, 0.74, 0.78, IRIS_BACK_Z])
_ANT_R = np.array([R_RET * math.sin(ORA_THETA), math.sqrt(R_RET ** 2 - 0.55 ** 2), 0.64, 0.595, 0.562,
                   0.540, 0.526, IRIS_ROOT_R])


def _pchip(x, xs, ys, d0=None):
    """Monotone cubic (Fritsch–Carlson) interpolation; ``d0`` fixes the first slope."""
    x = np.asarray(x, np.float64)
    h = np.diff(xs)
    delta = np.diff(ys) / h
    d = np.zeros_like(ys)
    for k in range(1, len(xs) - 1):
        if delta[k - 1] * delta[k] > 0:
            w1, w2 = 2 * h[k] + h[k - 1], h[k] + 2 * h[k - 1]
            d[k] = (w1 + w2) / (w1 / delta[k - 1] + w2 / delta[k])
    d[0] = delta[0] if d0 is None else d0
    d[-1] = delta[-1]
    k = np.clip(np.searchsorted(xs, x) - 1, 0, len(xs) - 2)
    t = (x - xs[k]) / h[k]
    h00, h10 = 2 * t ** 3 - 3 * t ** 2 + 1, t ** 3 - 2 * t ** 2 + t
    h01, h11 = -2 * t ** 3 + 3 * t ** 2, t ** 3 - t ** 2
    return h00 * ys[k] + h10 * h[k] * d[k] + h01 * ys[k + 1] + h11 * h[k] * d[k + 1]


def wall_base_radius(z):
    """Radius of the inner wall (without ciliary processes) at height ``z``."""
    z = np.asarray(z, np.float64)
    post = np.sqrt(np.maximum(R_RET ** 2 - z ** 2, 0.0))
    ant = _pchip(np.clip(z, Z_ORA, IRIS_BACK_Z), _ANT_Z, _ANT_R, d0=-Z_ORA / _ANT_R[0])
    return np.where(z <= Z_ORA, post, ant)


def ciliary_relief(z, phi):
    """Inward height of the ciliary processes (72 meridional ridges of the pars plicata)."""
    z0, z1 = PLICATA_Z
    u = np.clip((np.asarray(z, np.float64) - z0) / (z1 - z0), 0.0, 1.0)
    env = np.sin(math.pi * u) ** 1.5
    ridge = (0.5 + 0.5 * np.cos(CILIARY_PROCESSES * np.asarray(phi, np.float64))) ** 2
    return PROCESS_HEIGHT * env * ridge


def wall_radius(z, phi):
    return wall_base_radius(z) - ciliary_relief(z, phi)


def inner_wall_mesh(n_post: int = 140, n_ant: int = 72, n_seg: int = 432) -> MeshData:
    """Retina … ciliary body up to the iris root; normals face the inside of the eye."""
    th = np.linspace(0.0, ORA_THETA, n_post + 1)
    za = np.linspace(Z_ORA, IRIS_BACK_Z, n_ant + 1)[1:]
    z = np.concatenate([-R_RET * np.cos(th), za])
    r = np.concatenate([R_RET * np.sin(th), wall_base_radius(za)])
    nr, nz = _profile_normals(r, z)
    nr[: n_post + 1], nz[: n_post + 1] = -np.sin(th), np.cos(th)      # exact on the sphere
    return revolve(r, z, n_seg, (nr, nz), relief=ciliary_relief)


def iris_mesh(n_seg: int = 192) -> MeshData:
    """Iris as a thin solid: back (pigment), pupillary margin, front (stroma)."""
    parts = []
    for r, z in ((np.linspace(IRIS_ROOT_R, PUPIL_R, 24), np.full(24, IRIS_BACK_Z)),
                 (np.full(6, PUPIL_R), np.linspace(IRIS_BACK_Z, IRIS_Z, 6)),
                 (np.linspace(PUPIL_R, IRIS_ROOT_R, 48), np.full(48, IRIS_Z))):
        parts.append(revolve(r, z, n_seg, _profile_normals(r, z)))
    return merge(*parts)


def angle_mesh(n_seg: int = 192) -> MeshData:
    """Chamber angle: from the iris root up the corneoscleral wall to the limbus."""
    t = np.linspace(0.0, 1.0, 12)
    r = IRIS_ROOT_R + (LIMBUS_INNER_R - IRIS_ROOT_R) * t
    z = IRIS_Z + (LIMBUS_Z - IRIS_Z) * (t ** 0.8)
    return revolve(r, z, n_seg, _profile_normals(r, z))


def lens_profile(n: int = 64):
    t = np.linspace(0.0, math.pi, n + 1)
    hz = np.where(t <= math.pi / 2, LENS_FRONT_H, LENS_BACK_H)
    r = LENS_R * np.sin(t)
    z = LENS_EQ_Z + hz * np.cos(t)
    nr, nz = np.sin(t) / LENS_R, np.cos(t) / hz
    ln = np.hypot(nr, nz)
    return r, z, nr / ln, nz / ln


def lens_radius(z: float) -> float:
    h = LENS_FRONT_H if z >= LENS_EQ_Z else LENS_BACK_H
    u = (z - LENS_EQ_Z) / h
    return LENS_R * math.sqrt(max(0.0, 1.0 - u * u))


def lens_mesh(n_seg: int = 160) -> MeshData:
    r, z, nr, nz = lens_profile()
    return revolve(r, z, n_seg, (nr, nz))


def cornea_mesh() -> MeshData:
    # reaches a little past the limbus, under the sclera, so the seam never cracks open
    a_max = math.acos((LIMBUS_Z - 0.012 - CORNEA_CENTER_Z) / CORNEA_R)
    return sphere_mesh(48, 192, a_max, (0, 0, CORNEA_CENTER_Z), CORNEA_R)


def zonule_lines(n: int = 216, seed: int = 3) -> MeshData:
    """Zonular fibres from the ciliary processes to the lens equator (line pairs)."""
    rng = np.random.default_rng(seed)
    pos = []
    for k in range(n):
        phi = 2 * math.pi * (k // 3) / (n // 3) + rng.normal(0, 0.01)
        zc = rng.uniform(0.665, 0.735)
        rc = float(wall_radius(zc, phi)) - 0.004
        zl = LENS_EQ_Z + rng.uniform(-0.055, 0.045)
        rl = lens_radius(zl) + 0.002
        pos += [(rc * math.cos(phi), rc * math.sin(phi), zc), (rl * math.cos(phi), rl * math.sin(phi), zl)]
    pos = np.asarray(pos)
    return _mesh(pos, np.zeros_like(pos), np.arange(len(pos)), lines=True)


def _annulus(r_in, r_out, z: float, n_seg: int) -> MeshData:
    """Flat ring at height z (``r_in`` may vary with angle); uv = (0 inner … 1 outer, phi/2π)."""
    phi = np.linspace(0.0, 2 * math.pi, n_seg + 1)
    r_in = np.broadcast_to(np.asarray(r_in, np.float64), phi.shape)
    r_out = np.broadcast_to(np.asarray(r_out, np.float64), phi.shape)
    pos = np.concatenate([np.stack([rr * np.cos(phi), rr * np.sin(phi), np.full_like(phi, z)], 1)
                          for rr in (r_in, r_out)])
    uv = np.concatenate([np.stack([np.full_like(phi, v), phi / (2 * math.pi)], 1) for v in (0.0, 1.0)])
    nrm = np.tile([0.0, 0.0, 1.0], (len(pos), 1))
    return _mesh(pos, nrm, _grid_indices(1, n_seg), uv)


def cut_plane_z(cut: float) -> float:
    """Height of the section face: the front cut never reaches past the limbus."""
    return min(cut, LIMBUS_Z)


def rim_meshes(cut: float, n_seg: int = 432) -> dict[str, MeshData]:
    """Section faces where the front cut plane meets the eye wall, iris and lens."""
    zc = cut_plane_z(cut)
    out = {}
    if zc <= -1.0:
        return out
    r_out = math.sqrt(max(0.0, 1.0 - zc * zc))
    phi = np.linspace(0.0, 2 * math.pi, n_seg + 1)
    if zc <= -R_RET:
        r_in = np.zeros_like(phi)
    elif zc <= IRIS_BACK_Z:
        r_in = wall_radius(zc, phi)
    elif zc <= IRIS_Z:
        r_in = np.full_like(phi, IRIS_ROOT_R)
        out["iris"] = _annulus(PUPIL_R - 0.002, IRIS_ROOT_R, zc, 192)
    else:
        t = (zc - IRIS_Z) / (LIMBUS_Z - IRIS_Z)
        r_in = np.full_like(phi, IRIS_ROOT_R + (LIMBUS_INNER_R - IRIS_ROOT_R) * t ** (1 / 0.8))
    # overlap the clipped surfaces by a hair so no crack opens along the polygonal edges
    out["wall"] = _annulus(np.maximum(r_in - 0.003, 0.0), r_out + 0.003, zc, n_seg)
    if LENS_BACK_Z < zc < LENS_FRONT_Z:
        out["lens"] = _annulus(0.0, lens_radius(zc) + 0.002, zc, 128)
    return out


# -- tubes: optic nerve and extraocular muscles -------------------------------
def _bezier(P, n: int):
    t = np.linspace(0.0, 1.0, n)[:, None]
    P0, P1, P2, P3 = (np.asarray(p, np.float64) for p in P)
    return (1 - t) ** 3 * P0 + 3 * (1 - t) ** 2 * t * P1 + 3 * (1 - t) * t ** 2 * P2 + t ** 3 * P3


def _transport_frames(c: np.ndarray, u0: np.ndarray):
    """Tangents and rotation-minimising normals along the polyline ``c``."""
    T = np.gradient(c, axis=0)
    T /= np.linalg.norm(T, axis=1, keepdims=True)
    U = np.zeros_like(c)
    u = u0 - np.dot(u0, T[0]) * T[0]
    for i in range(len(c)):
        u = u - np.dot(u, T[i]) * T[i]
        u /= np.linalg.norm(u)
        U[i] = u
    return T, U, np.cross(T, U)


def _unit(v):
    v = np.asarray(v, np.float64)
    return v / np.linalg.norm(v)


def _perp(v):
    h = np.array([0.0, 1.0, 0.0]) if abs(v[1]) < 0.9 else np.array([1.0, 0.0, 0.0])
    return _unit(np.cross(v, h))


def _cap(center, T, U, V, rx, ry, n: int, uv_offset: float, sign: float = 1.0) -> MeshData:
    """Flat elliptical end cap; uv = (offset + x, y) in the cap's unit coordinates."""
    a = np.linspace(0.0, 2 * math.pi, n + 1)
    x, y = np.concatenate([[0.0], np.cos(a)]), np.concatenate([[0.0], np.sin(a)])
    pos = center + np.outer(x * rx, U) + np.outer(y * ry, V)
    j = np.arange(n)
    idx = np.stack([np.zeros(n, int), 1 + j, 2 + j], 1).reshape(-1)
    nrm = np.tile(T * sign, (len(pos), 1))
    return _mesh(pos, nrm, idx, np.stack([uv_offset + x, y], 1))


def nerve_mesh(p, laterality: str | None, n_seg: int = 64, n_len: int = 48) -> MeshData:
    """Optic nerve stump in its dural sheath leaving the globe at unit direction ``p``.

    A gently curved tube (≈ 11 mm) with a fillet where the sheath merges into
    the sclera and a flat cut end; uv = (s along the nerve, angle/2π) on the
    tube and (4 + x, y) on the cut face.
    """
    p = _unit(p)
    nasal = np.array([-1.0 if laterality == "OS" else 1.0, 0.0, 0.0])
    P1 = 1.30 * p
    P2 = P1 + 0.30 * _unit(p + np.array([0.0, -0.22, 0.0]) + 0.10 * nasal)
    P3 = P2 + 0.30 * _unit(p + np.array([0.0, 0.05, 0.0]) + 0.25 * nasal)
    c = _bezier((0.965 * p, P1, P2, P3), n_len)
    seg = np.linalg.norm(np.diff(c, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    rr = NERVE_R * (1.0 + 0.32 * np.exp(-(s / 0.05) ** 2)) * (1.0 - 0.05 * s / s[-1])
    T, U, V = _transport_frames(c, _perp(p))
    a = np.linspace(0.0, 2 * math.pi, n_seg + 1)
    d = np.cos(a)[None, :, None] * U[:, None, :] + np.sin(a)[None, :, None] * V[:, None, :]
    pos = c[:, None, :] + rr[:, None, None] * d
    S, A = np.meshgrid(s / s[-1], a / (2 * math.pi), indexing="ij")
    tube = _mesh(pos.reshape(-1, 3), d.reshape(-1, 3), _grid_indices(n_len - 1, n_seg),
                 np.stack([S, A], -1).reshape(-1, 2))
    return merge(tube, _cap(c[-1], T[-1], U[-1], V[-1], rr[-1], rr[-1], n_seg, 4.0))


def simple_nerve_mesh(p, radius: float = 0.14, length: float = 0.7, n: int = 48) -> MeshData:
    """Optic nerve of the simple view: a slightly tapered tube leaving the globe at unit ``p``."""
    p = _unit(p)
    u = _perp(p)
    v = np.cross(p, u)
    t = np.linspace(0, 2 * math.pi, n + 1)
    d = np.outer(np.cos(t), u) + np.outer(np.sin(t), v)
    # the base ring sits just outside the globe (|0.995 p + 0.147 d| > 1): never shows through
    rings = [p * s + d * rr for s, rr in ((0.995, radius * 1.05), (1.0 + length, radius * 0.9))]
    tube = _mesh(np.concatenate(rings), np.concatenate([d, d]), _grid_indices(1, n))
    return merge(tube, _cap(p * (1.0 + length), p, u, v, radius * 0.9, radius * 0.9, n, 4.0))


def _ribbon(c, N, s, width, thick, conform, n_u: int, uv_x) -> MeshData:
    """Flattened tube along ``c`` lying on the globe: bottom on the surface, wrapped to it
    where ``conform`` = 1 (on the globe) and flat where 0 (free in the orbit)."""
    T = np.gradient(c, axis=0)
    T /= np.linalg.norm(T, axis=1, keepdims=True)
    B = np.cross(T, N)
    B /= np.linalg.norm(B, axis=1, keepdims=True)
    N = np.cross(B, T)
    u = np.linspace(0.0, 2 * math.pi, n_u + 1)
    x = np.cos(u)[None, :] * width[:, None] / 2
    h = (np.sin(u)[None, :] + 1.0) * thick[:, None] / 2 + 0.004
    flat = c[:, None, :] + x[..., None] * B[:, None, :] + h[..., None] * N[:, None, :]
    rad = np.linalg.norm(c, axis=1)[:, None, None]
    curved = (rad + h[..., None]) * (np.cos(x)[..., None] * N[:, None, :] + np.sin(x)[..., None] * B[:, None, :])
    k = conform[:, None, None]
    P = k * curved + (1 - k) * flat
    dPs = np.gradient(P, axis=0)
    dPu = np.gradient(P, axis=1)
    dPu[:, 0] = dPu[:, -1] = P[:, 1] - P[:, -2]
    nrm = np.cross(dPu, dPs)
    nrm /= np.maximum(np.linalg.norm(nrm, axis=-1, keepdims=True), 1e-12)
    mid = c[:, None, :] + thick[:, None, None] / 2 * N[:, None, :]
    nrm *= np.sign(np.sum(nrm * (P - mid), axis=-1, keepdims=True) + 1e-12)
    UVx, UVy = np.meshgrid(uv_x, u / (2 * math.pi), indexing="ij")
    tube = _mesh(P.reshape(-1, 3), nrm.reshape(-1, 3), _grid_indices(len(c) - 1, n_u),
                 np.stack([UVx, UVy], -1).reshape(-1, 2))
    caps = []
    for i, sign in ((0, -1.0), (-1, 1.0)):
        ring = P[i, :-1]
        center = ring.mean(axis=0)
        # a ring wrapped around the globe has its mean inside it: lift the centre to the ring
        center *= max(1.0, np.linalg.norm(ring, axis=1).mean() / np.linalg.norm(center))
        e1 = _unit(ring[0] - center)
        e2 = np.cross(T[i], e1)
        loc = ring - center
        xy = np.stack([loc @ e1, loc @ e2], 1)
        rx, ry = np.abs(xy[:, 0]).max(), np.abs(xy[:, 1]).max()
        pos = np.concatenate([[center], ring, ring[:1]])
        uv = np.concatenate([[[0.0, 0.0]], xy / [rx, ry], xy[:1] / [rx, ry]])
        uv[:, 0] += 4.0
        j = np.arange(n_u)
        idx = np.stack([np.zeros(n_u, int), 1 + j, 2 + j], 1).reshape(-1)
        caps.append(_mesh(pos, np.tile(T[i] * sign, (len(pos), 1)), idx, uv))
    return merge(tube, *caps)


def _globe_path(start, direction, contact: float, free: float, target, n: int = 56):
    """Great-circle arc of length ``contact`` on the unit sphere from ``start`` along
    ``direction``, then leaving tangentially and bending toward ``target``."""
    s0 = _unit(start)
    t0 = _unit(direction - np.dot(direction, s0) * s0)
    n1 = max(8, int(n * contact / (contact + free)))
    g = np.linspace(0.0, contact, n1)
    arc = np.outer(np.cos(g), s0) + np.outer(np.sin(g), t0)
    tan_end = -math.sin(contact) * s0 + math.cos(contact) * t0
    q0 = arc[-1]
    q1 = q0 + tan_end * free * 0.5
    q2 = q1 + _unit(np.asarray(target, np.float64) - q1) * free * 0.5
    t = np.linspace(0.0, 1.0, n - n1 + 1)[1:, None]
    tail = (1 - t) ** 2 * q0 + 2 * (1 - t) * t * q1 + t ** 2 * q2
    tail /= np.minimum(np.linalg.norm(tail, axis=1, keepdims=True), 1.0)     # never through the globe
    c = np.concatenate([arc, tail])
    N = np.concatenate([arc, np.repeat(arc[-1:], len(tail), 0)])
    for i in range(n1, len(c)):                    # transport the surface normal off the globe
        Ti = _unit(c[i] - c[i - 1])
        Ni = N[i - 1] - np.dot(N[i - 1], Ti) * Ti
        N[i] = _unit(Ni)
    s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(c, axis=0), axis=1))])
    conform = np.clip(1.0 - (s - contact) / 0.25, 0.0, 1.0)
    return c, N, s, conform


def muscle_mesh(laterality: str | None) -> MeshData:
    """Stumps of the four recti and two obliques (enucleated-globe style)."""
    parts = []
    apex = np.array([0.8, 0.0, -2.6])
    for _, mer, ins_mm, w_mm, tendon_mm, contact_mm in RECTI:
        f = math.radians(mer)
        a = LIMBUS_ALPHA + ins_mm * MM
        start = np.array([math.sin(a) * math.cos(f), math.sin(a) * math.sin(f), math.cos(a)])
        direction = np.array([math.cos(a) * math.cos(f), math.cos(a) * math.sin(f), -math.sin(a)])
        c, N, s, conform = _globe_path(start, direction, contact_mm * MM, 0.32, apex)
        tl = tendon_mm * MM
        width = w_mm * MM * (1.0 - 0.32 * np.clip(s / s[-1], 0, 1) ** 0.7)
        thick = 0.03 + 0.10 * np.clip((s - 0.6 * tl) / (0.5 + 0.4 * tl), 0.0, 1.0) ** 0.8
        parts.append(_ribbon(c, N, s, width, thick, conform, 40, (s - tl) / s[-1]))
    # superior oblique: thin tendon fanning out under the SR, toward the trochlea
    for start_aphi, target, contact, free, w0, w1, t0, t1, tendon in (
            ((100.0, 118.0), (0.9, 1.1, 1.0), 0.45, 0.30, 0.80, 0.26, 0.025, 0.06, 9.0),
            ((118.0, 212.0), (0.6, -1.1, 1.0), 0.60, 0.25, 0.75, 0.50, 0.05, 0.13, 0.1)):
        a, f = (math.radians(v) for v in start_aphi)
        start = np.array([math.sin(a) * math.cos(f), math.sin(a) * math.sin(f), math.cos(a)])
        target = np.asarray(target, np.float64)
        c, N, s, conform = _globe_path(start, target - start, contact, free, target)
        u = np.clip(s / s[-1], 0, 1)
        width = w0 + (w1 - w0) * u ** 0.6
        thick = t0 + (t1 - t0) * u
        parts.append(_ribbon(c, N, s, width, thick, conform, 32, (s - tendon) / s[-1]))
    m = merge(*parts)
    return m.mirrored_x() if laterality == "OS" else m


# ---------------------------------------------------------------------------
# procedural textures
# ---------------------------------------------------------------------------
TEXTURE_VERSION = 5


def load_textures(cache_dir: Path | None = None) -> dict[str, np.ndarray]:
    """All textures of the model eye, from ``cache_dir`` when it holds this version.

    Generating them takes a few seconds; the PNG cache makes later starts instant.
    A broken or unwritable cache is ignored.
    """
    gens = {"iris": iris_texture, "sclera_a": sclera_anterior_texture,
            "sclera_p": sclera_posterior_texture, "periphery": retina_periphery_texture}
    out = {}
    folder = Path(cache_dir) / f"eye-textures-v{TEXTURE_VERSION}" if cache_dir else None
    for name, gen in gens.items():
        path = folder / f"{name}.png" if folder else None
        if path is not None and path.exists():
            try:
                out[name] = np.asarray(Image.open(path))
                continue
            except (OSError, ValueError):
                pass
        out[name] = gen()
        if path is not None:
            try:
                folder.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp")
                Image.fromarray(out[name]).save(tmp, format="PNG", compress_level=1)
                tmp.replace(path)
            except OSError:
                pass
    return out

def _noise(rng, shape, cells, periodic_x: bool = False) -> np.ndarray:
    """Smooth value noise in ≈[0, 1]: a random grid of ``cells`` (rows, cols) upsampled bicubically."""
    h, w = shape
    g = rng.random(cells).astype(np.float32)
    if periodic_x:
        g = np.concatenate([g, g, g], axis=1)
        a = np.asarray(Image.fromarray(g).resize((3 * w, h), Image.BICUBIC))[:, w:2 * w]
    else:
        a = np.asarray(Image.fromarray(g).resize((w, h), Image.BICUBIC))
    return np.array(a, np.float32)


def _fbm(rng, shape, base_cells, octaves: int = 4, periodic_x: bool = False) -> np.ndarray:
    out = np.zeros(shape, np.float32)
    amp, tot = 1.0, 0.0
    cy, cx = base_cells
    for _ in range(octaves):
        out += amp * _noise(rng, shape, (max(2, cy), max(2, cx)), periodic_x)
        tot += amp
        amp *= 0.5
        cy, cx = cy * 2, cx * 2
    return out / tot


def _smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _lerp(a, b, t):
    """``a + (b - a)·t`` in place on a float32 (..., 3) array; ``t`` broadcasts per pixel."""
    t = np.asarray(t, np.float32)
    if t.ndim:
        t = t[..., None]
    a += (np.asarray(b, np.float32) - a) * t
    return a


def _composite(base: Image.Image, layers) -> np.ndarray:
    """Paint flat colours over ``base`` through 8-bit masks: ``layers`` = [(rgb, mask, strength)]."""
    for rgb, mask, k in layers:
        m = mask.point(lambda v, k=k: int(v * k + 0.5))
        base = Image.composite(Image.new("RGB", base.size, tuple(int(c * 255 + 0.5) for c in rgb)), base, m)
    return np.asarray(base)


def _wrap_pi(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def _grow(rng, t, p, h, w, cfg: dict, out: list, depth: int = 0, length: float | None = None) -> None:
    """Random-walk vessel on a sphere in (polar angle t from the map pole, azimuth p).

    ``h`` is the heading relative to increasing t (π = toward the pole). The
    walk steers toward ``cfg['target']``, tapers, branches and stops outside
    ``cfg['t_range']``. Polylines of (t, p, width) are appended to ``out``.
    """
    length = cfg["length"] if length is None else length
    t_lo, t_hi = cfg["t_range"]
    pts = [(t, p, w)]
    s = 0.0
    toward = cfg.get("toward")
    while s < length and w > cfg["min_w"]:
        h += rng.normal(0.0, cfg["wander"])
        if toward is not None:                 # great-circle bearing to a point (t, p)
            st, ct, sp, cp = math.sin(t), math.cos(t), math.sin(p), math.cos(p)
            q = (math.sin(toward[0]) * math.cos(toward[1]), math.sin(toward[0]) * math.sin(toward[1]),
                 math.cos(toward[0]))
            dt = q[0] * ct * cp + q[1] * ct * sp - q[2] * st
            dp = -q[0] * sp + q[1] * cp
            if math.hypot(dt, dp) < 0.03:
                break
            h += cfg["steer"] * _wrap_pi(math.atan2(dp, dt) - h)
        elif cfg.get("target") is not None:
            h += cfg["steer"] * _wrap_pi(cfg["target"] - h)
        t += cfg["step"] * math.cos(h)
        p += cfg["step"] * math.sin(h) / max(math.sin(t), 0.05)
        if not t_lo < t < t_hi:
            break
        s += cfg["step"]
        w = min(w * cfg["taper"], cfg.get("max_w", 1.0))
        pts.append((t, p, w))
        if depth < cfg.get("depth", 3) and rng.random() < cfg["branch"]:
            side = 1.0 if rng.random() < 0.5 else -1.0
            _grow(rng, t, p, h + side * rng.uniform(0.45, 1.0), w * 0.72, cfg, out, depth + 1,
                  (length - s) * rng.uniform(0.3, 0.8))
            w *= 0.9
    if len(pts) > 1:
        out.append(np.asarray(pts))


class _MapCanvas:
    """Supersampled 8-bit mask over a stereographic map (pole at the centre)."""

    def __init__(self, n: int, xmax: float, ss: int = 2):
        self.n, self.xmax, self.ss = n, xmax, ss
        self.img = Image.new("L", (n * ss, n * ss), 0)
        self.draw = ImageDraw.Draw(self.img)
        self.scale = n * ss / (2 * xmax)

    def project(self, t, p):
        rx = np.tan(np.asarray(t) / 2)
        x = (rx * np.cos(p) + self.xmax) * self.scale
        y = (rx * np.sin(p) + self.xmax) * self.scale
        return x, y, self.scale / (1.0 + np.cos(t))      # px per unit length on the sphere

    def vessel(self, poly: np.ndarray, value: int) -> None:
        x, y, k = self.project(poly[:, 0], poly[:, 1])
        wpx = poly[:, 2] * k
        for i in range(1, len(poly)):
            w = max(1.0, float(wpx[i]))
            self.draw.line([(x[i - 1], y[i - 1]), (x[i], y[i])], fill=value, width=int(round(w)))
            if w >= 2.0:
                r = w / 2
                self.draw.ellipse([x[i] - r, y[i] - r, x[i] + r, y[i] + r], fill=value)

    def spot(self, t, p, radius: float, value: int, elong: float = 1.0) -> None:
        x, y, k = self.project(t, p)
        rr, rt = radius * k, radius * k * elong
        # elongate along the meridian (radial direction in the map)
        c, s = math.cos(p), math.sin(p)
        pts = [(float(x + rt * math.cos(a) * c - rr * math.sin(a) * s),
                float(y + rt * math.cos(a) * s + rr * math.sin(a) * c)) for a in np.linspace(0, 2 * math.pi, 24)]
        self.draw.polygon(pts, fill=value)

    def result(self, blur: float = 0.0) -> Image.Image:
        img = self.img.resize((self.n, self.n), Image.BOX)
        return img.filter(ImageFilter.GaussianBlur(blur)) if blur > 0 else img


def _map_coords(n: int, xmax: float):
    c = (np.arange(n, dtype=np.float32) + 0.5) / n * 2 * xmax - xmax
    X, Y = np.meshgrid(c, c)                       # row = y, col = x
    rx = np.hypot(X, Y)
    return 2 * np.arctan(rx), np.arctan2(Y, X)


def _to_u8(rgb) -> np.ndarray:
    return (np.clip(rgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


@lru_cache(maxsize=None)
def sclera_anterior_texture(n: int = 2048, seed: int = 5) -> np.ndarray:
    """Anterior hemisphere of the outer coat (map pole = corneal apex), RGB uint8."""
    rng = np.random.default_rng(seed)
    limb = LIMBUS_ALPHA
    m = n // 2                                     # the ground has no fine detail: build it at half size
    al, phi = _map_coords(m, SCLERA_MAP_XMAX)
    base = np.empty((m, m, 3), np.float32)
    base[:] = (0.875, 0.855, 0.815)
    base *= (0.975 + 0.05 * _fbm(rng, (m, m), (6, 6), 5))[..., None]
    _lerp(base, (0.94, 0.90, 0.83), 0.35 * _fbm(rng, (m, m), (3, 3), 3))       # ivory mottling
    _lerp(base, (0.91, 0.80, 0.78), 0.14 * _smoothstep(0.75, 1.35, al))          # fornix flush
    _lerp(base, (0.76, 0.77, 0.80), 0.6 * _smoothstep(limb + 0.045, limb, al))   # translucent limbus
    # palisades of Vogt: fine radial ridges in the limbal zone
    zone = _smoothstep(limb, limb + 0.012, al) * _smoothstep(limb + 0.05, limb + 0.025, al)
    base *= (1.0 + 0.025 * np.sin(phi * 120 + 3 * np.sin(phi * 23)) * zone)[..., None]
    base[al < limb] = (0.70, 0.72, 0.76)
    ground = Image.fromarray(_to_u8(base)).resize((n, n), Image.BICUBIC)

    conj_a, conj_v, epi, deep, fine = (_MapCanvas(n, SCLERA_MAP_XMAX) for _ in range(5))
    # conjunctival vessels: few, tortuous, from the fornix toward the limbus, mostly in the lid fissure
    k = 0
    while k < 58:
        p0 = rng.uniform(0, 2 * math.pi)
        if rng.random() > 0.2 + 0.8 * math.cos(p0) ** 2:
            continue
        k += 1
        polys: list = []
        cfg = dict(step=0.008, wander=0.2, steer=0.05, target=math.pi, length=rng.uniform(0.4, 0.9),
                   t_range=(limb + rng.uniform(0.05, 0.12), 1.75), branch=0.05, taper=0.994, min_w=0.0022)
        _grow(rng, rng.uniform(0.9, 1.4), p0, math.pi + rng.normal(0, 0.35), rng.uniform(0.004, 0.0105),
              cfg, polys)
        canvas = conj_a if rng.random() < 0.55 else conj_v
        v = int(rng.uniform(90, 230))
        for poly in polys:
            canvas.vessel(poly, v)
    # limbal arcades: short circumferential loops just outside the limbus
    for _ in range(120):
        polys = []
        cfg = dict(step=0.006, wander=0.5, steer=0.0, target=None, length=rng.uniform(0.03, 0.07),
                   t_range=(limb + 0.022, limb + 0.12), branch=0.08, taper=0.995, min_w=0.002)
        _grow(rng, limb + rng.uniform(0.035, 0.09), rng.uniform(0, 2 * math.pi),
              rng.choice((-1.0, 1.0)) * math.pi / 2 + rng.normal(0, 0.3), rng.uniform(0.0022, 0.0035), cfg, polys)
        for poly in polys:
            conj_a.vessel(poly, int(rng.uniform(70, 140)))
    # capillary meshwork
    for _ in range(260):
        polys = []
        cfg = dict(step=0.008, wander=0.6, steer=0.0, target=None, length=rng.uniform(0.05, 0.14),
                   t_range=(limb + 0.03, 1.7), branch=0.05, taper=0.997, min_w=0.0015)
        _grow(rng, rng.uniform(limb + 0.08, 1.6), rng.uniform(0, 2 * math.pi), rng.uniform(0, 2 * math.pi),
              rng.uniform(0.0018, 0.0028), cfg, polys)
        for poly in polys:
            fine.vessel(poly, int(rng.uniform(50, 110)))
    # anterior ciliary arteries from the rectus insertions, diving 3–4 mm from the limbus
    for name, mer, ins_mm, *_ in RECTI:
        for off in ((-0.13, 0.13) if name != "LR" else (0.0,)):
            polys = []
            cfg = dict(step=0.01, wander=0.12, steer=0.1, target=math.pi, length=1.0,
                       t_range=(limb + rng.uniform(0.25, 0.32), 1.6), branch=0.05, taper=0.996, min_w=0.004)
            _grow(rng, LIMBUS_ALPHA + ins_mm * MM - 0.01, math.radians(mer) + off + rng.normal(0, 0.03),
                  math.pi, rng.uniform(0.010, 0.014), cfg, polys)
            for poly in polys:
                epi.vessel(poly, 200)
    # deep episcleral plexus, seen blurred through the conjunctiva
    for _ in range(60):
        polys = []
        cfg = dict(step=0.012, wander=0.15, steer=0.05, target=math.pi, length=rng.uniform(0.2, 0.5),
                   t_range=(limb + 0.2, 1.6), branch=0.08, taper=0.99, min_w=0.006)
        _grow(rng, rng.uniform(0.7, 1.3), rng.uniform(0, 2 * math.pi), math.pi + rng.normal(0, 0.4),
              rng.uniform(0.010, 0.018), cfg, polys)
        for poly in polys:
            deep.vessel(poly, int(rng.uniform(100, 180)))
    return _composite(ground, (
        ((0.62, 0.30, 0.34), deep.result(3.0), 0.30),
        ((0.86, 0.52, 0.52), fine.result(0.7), 0.30),
        ((0.55, 0.20, 0.24), epi.result(1.1), 0.60),
        ((0.60, 0.15, 0.17), conj_v.result(0.7), 0.75),
        ((0.78, 0.22, 0.20), conj_a.result(0.7), 0.75)))


@lru_cache(maxsize=None)
def sclera_posterior_texture(n: int = 1024, seed: int = 9) -> np.ndarray:
    """Posterior hemisphere of the sclera (map pole = posterior pole), RGB uint8."""
    rng = np.random.default_rng(seed)
    th, phi = _map_coords(n, SCLERA_MAP_XMAX)
    col = np.empty((n, n, 3), np.float32)
    col[:] = (0.84, 0.81, 0.75)
    col *= (0.965 + 0.07 * _fbm(rng, (n, n), (8, 8), 5))[..., None]
    _lerp(col, (0.80, 0.80, 0.82), 0.28 * _smoothstep(1.05, 1.5, th))        # thin sclera at the equator
    vort, vort_deep, lpc, spots = (_MapCanvas(n, SCLERA_MAP_XMAX) for _ in range(4))
    exits = [(math.radians(73 + rng.normal(0, 3)), math.pi / 4 + k * math.pi / 2 + rng.normal(0, 0.08), 1.0)
             for k in range(4)]
    exits += [(math.radians(rng.uniform(68, 80)), rng.uniform(0, 2 * math.pi), 0.6) for _ in range(2)]
    for t0, p0, size in exits:
        vort.spot(t0, p0, 0.03 * size, 255, elong=1.4)
        polys = []
        cfg = dict(step=0.01, wander=0.05, steer=0.1, target=math.pi, length=0.2 * size,
                   t_range=(0.2, 1.8), branch=0.0, taper=0.985, min_w=0.01)
        _grow(rng, t0, p0, math.pi + rng.normal(0, 0.2), 0.055 * size, cfg, polys)
        for poly in polys:
            vort.vessel(poly, 220)
        polys = []                                     # oblique intrascleral course, seen through the sclera
        cfg.update(length=0.14 * size, target=0.0)
        _grow(rng, t0, p0, rng.normal(0, 0.2), 0.06 * size, cfg, polys)
        for poly in polys:
            vort_deep.vessel(poly, 200)
    for p0 in (0.0, math.pi):
        for dp, v in ((-0.035, 140), (0.035, 110)):
            polys = []
            cfg = dict(step=0.012, wander=0.03, steer=0.05, target=0.0, length=1.0,
                       t_range=(0.3, 1.45), branch=0.0, taper=0.999, min_w=0.003)
            _grow(rng, 0.42, p0 + dp, 0.0, 0.012, cfg, polys)
            for poly in polys:
                lpc.vessel(poly, v)
    for _ in range(7):
        spots.spot(rng.uniform(1.1, 1.5), rng.uniform(0, 2 * math.pi), rng.uniform(0.006, 0.012), 200)
    return _composite(Image.fromarray(_to_u8(col)), (
        ((0.52, 0.40, 0.42), lpc.result(1.5), 0.35),
        ((0.45, 0.42, 0.45), spots.result(1.0), 0.45),
        ((0.55, 0.53, 0.60), vort_deep.result(5.0), 0.40),
        ((0.40, 0.36, 0.44), vort.result(3.0), 0.62)))


@lru_cache(maxsize=None)
def retina_periphery_texture(n: int = 1024, seed: int = 4) -> np.ndarray:
    """Fundus beyond the photographed field up to past the ora (map pole = posterior pole)."""
    rng = np.random.default_rng(seed)
    th, phi = _map_coords(n, PERI_MAP_XMAX)
    col = np.empty((n, n, 3), np.float32)
    col[:] = (0.72, 0.35, 0.21)
    _lerp(col, (0.52, 0.23, 0.13), _smoothstep(0.9, 2.1, th))
    col *= (0.95 + 0.10 * _fbm(rng, (n, n), (40, 40), 3))[..., None]           # RPE granularity
    chor, ret_a, ret_v = (_MapCanvas(n, PERI_MAP_XMAX) for _ in range(3))
    amp = [(1.62 + rng.normal(0, 0.04), math.pi / 4 + k * math.pi / 2 + rng.normal(0, 0.05)) for k in range(4)]
    for _ in range(650):                   # choroidal veins, widening as they converge on the vortex ampullae
        t0, p0 = math.acos(rng.uniform(math.cos(2.2), math.cos(0.45))), rng.uniform(0, 2 * math.pi)
        ta, pa = amp[int(((p0 % (2 * math.pi)) // (math.pi / 2)))]
        q = (math.sin(ta) * math.cos(pa), math.sin(ta) * math.sin(pa), math.cos(ta))
        h0 = math.atan2(-q[0] * math.sin(p0) + q[1] * math.cos(p0),
                        (q[0] * math.cos(p0) + q[1] * math.sin(p0)) * math.cos(t0) - q[2] * math.sin(t0))
        polys = []
        cfg = dict(step=0.012, wander=0.05, steer=0.18, toward=(ta, pa), length=rng.uniform(0.25, 0.7),
                   t_range=(0.3, 2.25), branch=0.0, taper=1.01, max_w=0.034, min_w=0.0)
        _grow(rng, t0, p0, h0 + rng.normal(0, 0.3), rng.uniform(0.009, 0.016), cfg, polys)
        for poly in polys:
            chor.vessel(poly, int(rng.uniform(150, 255)))
    for _ in range(26):                    # peripheral retinal vessels running out to the ora
        polys = []
        cfg = dict(step=0.012, wander=0.08, steer=0.03, target=0.0, length=1.4,
                   t_range=(0.5, 2.1), branch=0.05, taper=0.994, min_w=0.0025)
        _grow(rng, rng.uniform(0.85, 1.05), rng.uniform(0, 2 * math.pi), rng.normal(0, 0.2),
              rng.uniform(0.006, 0.011), cfg, polys)
        canvas = ret_a if rng.random() < 0.5 else ret_v
        for poly in polys:
            canvas.vessel(poly, int(rng.uniform(150, 220)))
    tess = np.asarray(chor.result(1.6), np.float32) / 127.5 - 1.0
    col *= (1.0 + 0.16 * _smoothstep(0.6, 1.4, th) * tess)[..., None]
    _lerp(col, (0.32, 0.18, 0.12), _smoothstep(1.95, 2.13, th))
    return _composite(Image.fromarray(_to_u8(col)), (
        ((0.47, 0.10, 0.07), ret_v.result(0.6), 0.65),
        ((0.62, 0.18, 0.11), ret_a.result(0.6), 0.55)))


def _shift_cols(field: np.ndarray, shift: np.ndarray) -> np.ndarray:
    """Sample ``field`` at (row, col + shift) with wrap-around linear interpolation."""
    h, w = field.shape
    x = np.arange(w, dtype=np.float32)[None, :] + shift
    x0 = np.floor(x)
    f = x - x0
    x0 = x0.astype(np.int64) % w
    a = np.take_along_axis(field, x0, axis=1)
    b = np.take_along_axis(field, (x0 + 1) % w, axis=1)
    return a + (b - a) * f


@lru_cache(maxsize=None)
def iris_texture(n: int = 1024, seed: int = 11) -> np.ndarray:
    """Brown iris over [-IRIS_ROOT_R, IRIS_ROOT_R]², RGBA uint8; alpha = stromal height.

    Built in polar coordinates (rows = radius from the pupil margin to the
    root, cols = angle) and resampled: radial trabeculae, the pupillary zone
    and its ruff, the zig-zag collarette, crypts of Fuchs, concentric
    contraction furrows and a few freckles.
    """
    rng = np.random.default_rng(seed)
    NA, NR = 2048, 384
    rp = PUPIL_R / IRIS_ROOT_R
    rn = (rp + (1 - rp) * (np.arange(NR) + 0.5) / NR).astype(np.float32)[:, None]
    RN = np.broadcast_to(rn, (NR, NA))
    px_rad = NA / (2 * math.pi)                         # cols per radian
    px_r = NR / (1 - rp)                                # rows per unit of normalised radius

    warp = (_noise(rng, (NR, NA), (5, 14), True) - 0.5) * 26 + (_noise(rng, (NR, NA), (14, 48), True) - 0.5) * 7
    f1 = _shift_cols(_noise(rng, (NR, NA), (8, 300), True), warp)
    f2 = _shift_cols(_noise(rng, (NR, NA), (22, 760), True), warp * 1.1)
    fib = _smoothstep(0.28, 0.80, 0.55 * f1 + 0.45 * f2)
    fine = _smoothstep(0.25, 0.85, _shift_cols(_noise(rng, (NR, NA), (30, 1300), True), warp * 0.5))
    big = _noise(rng, (NR, NA), (4, 9), True)

    rc = (0.53 + 0.05 * (_noise(rng, (1, NA), (2, 7), True)[0] - 0.5)
          + 0.022 * (_noise(rng, (1, NA), (2, 29), True)[0] - 0.5))[None, :]
    coll = np.exp(-((RN - rc) / 0.022) ** 2)
    pz = _smoothstep(rc + 0.012, rc - 0.012, RN)

    def polar_canvas():
        img = Image.new("L", (NA, NR), 0)
        return img, ImageDraw.Draw(img)

    def ellipse(draw, a0, r0, half_w, half_h, v):
        for off in (-NA, 0, NA):
            x, y = a0 * px_rad + off, (r0 - rp) * px_r
            draw.ellipse([x - half_w, y - half_h, x + half_w, y + half_h], fill=v)

    crypt_img, cd = polar_canvas()
    for count, r_lo, r_hi, w_lo, w_hi, h_lo, h_hi, v_lo, v_hi in (
            (30, 0.025, 0.10, 0.018, 0.042, 0.03, 0.075, 110, 210),    # collarette crypts
            (34, None, None, 0.010, 0.024, 0.015, 0.04, 70, 150),      # peripheral crypts
            (8, -0.10, -0.04, 0.008, 0.014, 0.012, 0.022, 60, 120)):   # pupillary zone
        for _ in range(count):
            a0 = rng.uniform(0, 2 * math.pi)
            rc0 = float(rc[0, int(a0 * px_rad) % NA])
            r0 = rng.uniform(0.80, 0.93) if r_lo is None else rc0 + rng.uniform(r_lo, r_hi)
            ellipse(cd, a0, r0, rng.uniform(w_lo, w_hi) / r0 * px_rad, rng.uniform(h_lo, h_hi) * px_r,
                    int(rng.uniform(v_lo, v_hi)))
    crypt = np.asarray(crypt_img.filter(ImageFilter.GaussianBlur(2.6)), np.float32) / 255.0

    furrow_img, fd = polar_canvas()
    for r0 in (0.70, 0.765, 0.825, 0.875, 0.925):
        for _ in range(int(rng.integers(3, 6))):
            a0, span = rng.uniform(0, 2 * math.pi), rng.uniform(0.4, 1.6)
            a = np.linspace(a0, a0 + span, int(span * 120))
            y = (r0 + rng.normal(0, 0.006) + 0.005 * np.sin(a * rng.uniform(8, 20)) - rp) * px_r
            for off in (-NA, 0, NA):
                fd.line(list(zip(a * px_rad + off, y)), fill=int(rng.uniform(140, 210)), width=2)
    furrow = np.asarray(furrow_img.filter(ImageFilter.GaussianBlur(1.4)), np.float32) / 255.0

    freck_img, frd = polar_canvas()
    for _ in range(3):
        r0 = rng.uniform(0.62, 0.9)
        rad = rng.uniform(0.015, 0.03)
        ellipse(frd, rng.uniform(0, 2 * math.pi), r0, rad / r0 * px_rad, rad * px_r, 255)
    freck = np.asarray(freck_img.filter(ImageFilter.GaussianBlur(2.5)), np.float32) / 255.0

    ruff_edge = rp + 0.014 + (0.007 * _noise(rng, (1, NA), (2, 70), True)[0]
                              + 0.004 * _noise(rng, (1, NA), (2, 190), True)[0])[None, :]
    ruff = _smoothstep(ruff_edge + 0.006, ruff_edge - 0.004, RN)

    col = np.empty((NR, NA, 3), np.float32)
    col[:] = (0.15, 0.085, 0.042)                                   # ciliary zone stroma
    _lerp(col, (0.31, 0.185, 0.095), fib * 0.85)                    # trabeculae
    pup = np.empty_like(col)
    pup[:] = (0.27, 0.16, 0.075)                                    # pupillary zone
    _lerp(pup, (0.40, 0.255, 0.12), fine * 0.7)
    _lerp(col, pup, pz)
    _lerp(col, (0.42, 0.28, 0.135), coll * 0.6)                     # collarette
    _lerp(col, (0.085, 0.048, 0.024), crypt * 0.75)                 # crypts of Fuchs
    _lerp(col, (0.09, 0.055, 0.028), furrow * 0.5)                  # contraction furrows
    _lerp(col, (0.12, 0.065, 0.028), freck * 0.7)                   # freckles
    _lerp(col, (0.075, 0.045, 0.025), _smoothstep(0.86, 1.0, RN) * 0.85)
    _lerp(col, (0.07, 0.045, 0.03), ruff)                           # pupillary ruff
    col *= (0.86 + 0.28 * big)[..., None]
    height = np.clip(0.55 + 0.28 * (fib - 0.5) + 0.35 * coll + 0.1 * pz - 0.45 * crypt - 0.25 * furrow
                     - 0.1 * ruff, 0.0, 1.0)
    polar = np.dstack([_to_u8(col), _to_u8(height)[..., None]])

    # polar → Cartesian (bilinear, wrapping in angle)
    c = (np.arange(n, dtype=np.float32) + 0.5) / n * 2 - 1
    X, Y = np.meshgrid(c, c)
    r = np.hypot(X, Y)
    fr = np.clip((r - rp) * px_r - 0.5, 0, NR - 1.001)
    fa = np.mod(np.arctan2(Y, X), 2 * math.pi) * px_rad - 0.5
    r0, a0 = np.floor(fr).astype(np.int32), np.floor(fa).astype(np.int32)
    wr, wa = (fr - r0)[..., None], (fa - a0)[..., None]
    i00 = r0 * NA + a0 % NA
    i01 = r0 * NA + (a0 + 1) % NA
    flat = polar.reshape(-1, 4).astype(np.float32)
    top = np.take(flat, i00, axis=0)
    top += (np.take(flat, i01, axis=0) - top) * wa
    bot = np.take(flat, i00 + NA, axis=0)
    bot += (np.take(flat, i01 + NA, axis=0) - bot) * wa
    out = top
    out += (bot - top) * wr
    out[r < rp] = (4, 3, 3, 128)
    out[r > 1.0] = (18, 11, 7, 76)
    return (out + 0.5).astype(np.uint8)
