"""Build web3d/eye3d.html: the program's 3D eye in a single web page, to try out 3D ideas before they
go into the program.

The page uses what the program uses, taken from the program itself when this script runs:

* the shaders of ``fundusview/ui/eye3d.py`` (GLSL 1.20), rewritten for WebGL 2 (GLSL ES 3.00);
* the eye model of ``fundusview/ui/eye_model.py``: its dimensions, the profiles the meshes are
  turned from (the page builds the meshes from them), the zonules and the muscles;
* the anatomical textures (iris, sclera, retinal periphery);
* demo photos from ``fundusview/demo.py`` with the image circle, optic disc and fovea found by
  ``fundusview/imaging.py``, as the program finds them when it imports a photo.

    python web3d/build.py                 # writes web3d/eye3d.html
    python web3d/build.py page-body.html  # … and the page without its document skeleton

The page logic is ``web3d/app.js`` and its look ``web3d/app.css``; ``web3d/page.html`` holds the
markup. All of it, and the data, end up inline in the one HTML file.
"""
from __future__ import annotations

import base64
import io
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from fundusview import demo, imaging, placement  # noqa: E402
from fundusview import projection as proj  # noqa: E402
from fundusview.ui import eye3d as e3  # noqa: E402
from fundusview.ui import eye_model as em  # noqa: E402


# -- shaders -----------------------------------------------------------------------------
PROGRAMS = {          # as EyeView.initializeGL composes them (the detailed look)
    "bg": (("BG_VERT",), ("BG_FRAG",)),
    "sclera": (("VERT",), ("COMMON", "SCLERA_LIB", "MAPPING_LIB", "RETINA_LIB", "SCLERA_FRAG")),
    "cornea": (("VERT",), ("COMMON", "SCLERA_LIB", "IRIS_LIB", "CORNEA_FRAG")),
    "wall": (("VERT",), ("COMMON", "MAPPING_LIB", "RETINA_LIB", "WALL_FRAG")),
    "tissue": (("VERT",), ("COMMON", "IRIS_LIB", "WALL_LAYERS_LIB", "TISSUE_FRAG")),
    "clear": (("VERT",), ("COMMON", "CLEAR_FRAG")),
    "section": (("VERT",), ("COMMON", "WALL_LAYERS_LIB", "SECTION_FRAG")),
    "fade": (("BG_VERT",), ("FADE_FRAG",)),
}


# What the page tries before the program has it: a few lines more in the program's shaders, as
# (part, old, new), each old matching once. They go into eye3d.py once they are confirmed in the page.
WEB_PATCHES: list[tuple[str, str, str]] = []   # (all in eye3d.py now)


def block(name: str) -> str:
    """A part of the program's shaders with the page's lines in it."""
    src = getattr(e3, name)
    for part, old, new in WEB_PATCHES:
        if part == name:
            assert src.count(old) == 1, (name, old)
            src = src.replace(old, new)
    return src


def to_es300(src: str, stage: str) -> str:
    """GLSL 1.20 → GLSL ES 3.00 (WebGL 2): the same code, the newer spelling."""
    src = src.replace("#version 120\n", "")
    src = "\n".join(line for line in src.splitlines() if "gl_ClipVertex" not in line)   # no clip planes:
    src = re.sub(r"\btexture2D\s*\(", "texture(", src)                                 # the shaders discard
    if stage == "vs":
        src = re.sub(r"\battribute\b", "in", src)
        src = re.sub(r"\bvarying\b", "out", src)
    else:
        src = re.sub(r"\bvarying\b", "in", src)
        src = src.replace("gl_FragColor", "fragColor_")
        src = "out vec4 fragColor_;\n" + src
    return "#version 300 es\nprecision highp float;\nprecision highp int;\nprecision highp sampler2D;\n" + src


def shaders() -> dict:
    out = {}
    for name, (vs, fs) in PROGRAMS.items():
        out[name] = {"vs": to_es300(e3._glsl(*(block(p) for p in vs)), "vs"),
                     "fs": to_es300(e3._glsl(*(block(p) for p in fs)), "fs")}
    return out


# -- the eye model -----------------------------------------------------------------------
def b64(a: np.ndarray, dtype) -> str:
    return base64.b64encode(np.ascontiguousarray(a, dtype).tobytes()).decode("ascii")


def profile(r, z, normals=None) -> dict:
    nr, nz = normals if normals is not None else em._profile_normals(r, z)
    return {k: [round(float(x), 7) for x in v] for k, v in (("r", r), ("z", z), ("nr", nr), ("nz", nz))}


def model() -> dict:
    """What the page needs to build the meshes as eye_model.py builds them."""
    consts = {k: float(getattr(em, k)) for k in (
        "MM", "SCLERA_T", "CHOROID_T", "RETINA_T", "R_RET", "LIMBUS_Z", "LIMBUS_R", "LIMBUS_ALPHA",
        "LIMBUS_INNER_R", "CORNEA_CENTER_Z", "CORNEA_R", "N_AQUEOUS", "IRIS_Z", "IRIS_BACK_Z", "IRIS_ROOT_R",
        "PUPIL_R", "LENS_R", "LENS_EQ_Z", "LENS_FRONT_H", "LENS_BACK_H", "LENS_FRONT_Z", "LENS_BACK_Z",
        "ORA_THETA", "Z_ORA", "CILIARY_PROCESSES", "PROCESS_HEIGHT", "NERVE_R")}
    consts["PLICATA_Z0"], consts["PLICATA_Z1"] = (float(v) for v in em.PLICATA_Z)
    consts["DEFAULT_VIEWPOINT"] = proj.DEFAULT_VIEWPOINT
    consts["DEFAULT_RADIAL_C"] = proj.DEFAULT_RADIAL_C
    consts["DISC_FOVEA_DEG"] = placement.DISC_FOVEA_DEG
    consts["DISC_TILT_DEG"] = placement.DISC_TILT_DEG

    # inner wall (inner_wall_mesh): the retina band and the ciliary band
    n_post, n_ant = 64, 56
    th = np.linspace(0.0, em.ORA_THETA, n_post + 1)
    za = np.linspace(em.Z_ORA, em.IRIS_BACK_Z, n_ant + 1)[1:]
    z = np.concatenate([-em.R_RET * np.cos(th), za])
    r = np.concatenate([em.R_RET * np.sin(th), em.wall_base_radius(za)])
    nr, nz = em._profile_normals(r, z)
    nr[: n_post + 1], nz[: n_post + 1] = -np.sin(th), np.cos(th)
    k = n_post + 1
    wall = {"post": profile(r[:k], z[:k], (nr[:k], nz[:k])), "ant": profile(r[k - 1:], z[k - 1:], (nr[k - 1:], nz[k - 1:])),
            "seg_post": 180, "seg_ant": 432}
    iris = []
    for rr, zz in ((np.linspace(em.IRIS_ROOT_R, em.PUPIL_R, 24), np.full(24, em.IRIS_BACK_Z)),
                   (np.full(6, em.PUPIL_R), np.linspace(em.IRIS_BACK_Z, em.IRIS_Z, 6)),
                   (np.linspace(em.PUPIL_R, em.IRIS_ROOT_R, 48), np.full(48, em.IRIS_Z))):
        iris.append(profile(rr, zz))
    t = np.linspace(0.0, 1.0, 12)
    angle = profile(em.IRIS_ROOT_R + (em.LIMBUS_INNER_R - em.IRIS_ROOT_R) * t,
                    em.IRIS_Z + (em.LIMBUS_Z - em.IRIS_Z) * (t ** 0.8))
    lr, lz, lnr, lnz = em.lens_profile()
    lens = profile(lr, lz, (lnr, lnz))
    zb = np.linspace(em.Z_ORA, em.IRIS_BACK_Z, 129)                 # wall_base_radius for the cut rims
    zon = em.zonule_lines()
    mus = em.muscle_mesh("OD")
    return {
        "consts": consts,
        "wall": wall, "iris": iris, "angle": angle, "lens": lens,
        "wall_base": {"z": [round(float(v), 7) for v in zb], "r": [round(float(v), 7) for v in em.wall_base_radius(zb)]},
        "zonules": b64(zon.pos, np.float32),
        "muscles": {"pos": b64(mus.pos, np.float32), "nrm": b64(mus.nrm, np.float32),
                    "uv": b64(mus.uv, np.float32), "idx": b64(mus.idx, np.uint16 if len(mus.pos) < 65536 else np.uint32),
                    "idx32": len(mus.pos) >= 65536},
        "units": dict(e3._UNITS),
        "dist0": e3.EyeView.DIST0, "fov0": e3.EyeView.FOV0,
        "relief": 0.6, "spin": 10.0,
    }


# -- textures ----------------------------------------------------------------------------
def data_url(img: Image.Image, fmt: str, **kw) -> str:
    buf = io.BytesIO()
    img.save(buf, fmt, **kw)
    mime = "image/png" if fmt == "PNG" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def textures() -> dict:
    tex = e3.model_textures()
    return {"iris": data_url(Image.fromarray(tex["iris"]), "PNG", optimize=True),
            "scl_a": data_url(Image.fromarray(tex["sclera_a"]), "JPEG", quality=84),
            "scl_p": data_url(Image.fromarray(tex["sclera_p"]), "JPEG", quality=86),
            "peri": data_url(Image.fromarray(tex["periphery"]), "JPEG", quality=86)}


# -- demo photos -------------------------------------------------------------------------
DEVICES = {   # as profiles.py describes these cameras
    "reticam": {"label": "RetiCam 3100 Plus (176°)", "fov": 176.0, "fov_type": "internal", "projection": "radial"},
    "apollo": {"label": "APOLLO (135° · 165°)", "fov": 135.0, "fov_type": "internal", "projection": "equidistant"},
    "camera45": {"label": "일반 안저카메라 (45°)", "fov": 45.0, "fov_type": "external", "projection": "perspective"},
}

PHOTOS = (   # key, label, eye, device, fov, synth arguments
    ("reticam_od", "RetiCam 176° · 우안", "OD", "reticam", 176.0,
     dict(fov_type="internal", projection="radial", size=(1180, 886), seed=21, tint=(0.82, 0.45, 0.24))),
    ("cam45_center", "45° 황반 중심 · 우안", "OD", "camera45", 45.0,
     dict(fov_type="external", projection="perspective", size=(900, 900), seed=31)),
    ("cam45_nasal", "45° 코쪽 · 우안", "OD", "camera45", 45.0,
     dict(fov_type="external", projection="perspective", size=(900, 900), seed=31, gaze=(27.0, 1.0, 2.0))),
    ("cam45_up", "45° 위쪽 · 우안", "OD", "camera45", 45.0,
     dict(fov_type="external", projection="perspective", size=(900, 900), seed=31, gaze=(1.0, 24.0, 1.0))),
    ("cam30_disc", "30° 유두 중심 · 좌안", "OS", "camera45", 30.0,
     dict(fov_type="external", projection="perspective", size=(800, 800), seed=12, gaze=(-21.0, 1.5))),
    ("apollo_os", "APOLLO 135° · 좌안", "OS", "apollo", 135.0,
     dict(fov_type="internal", projection="equidistant", size=(1000, 1000), seed=4, tint=(0.78, 0.47, 0.30))),
)


def photos() -> list[dict]:
    out = []
    for key, label, eye, device, fov, kw in PHOTOS:
        kw = dict(kw)
        size = kw.pop("size")
        circle = None
        if device == "reticam":           # the device's frame: a 4:3 picture, the circle a little inside it
            circle = (size[0] / 2.0, size[1] / 2.0, size[1] / 2.0 * 0.97)
        rgb = demo.synth_fundus(eye=eye, fov_deg=fov, size=size, circle=circle, **kw)
        if device == "camera45" and fov >= 45:   # a 4:3 frame, the circle cut at the top and bottom
            h = size[0] * 3 // 4
            top = (size[0] - h) // 2
            rgb = np.ascontiguousarray(rgb[top:top + h])
        dev = DEVICES[device]
        c = imaging.detect_circle(rgb)
        tmax = math.degrees(proj.theta_max(fov, dev["fov_type"]))
        disc = imaging.detect_disc(rgb, c, disc_frac=min(0.25, 3.8 / max(tmax, 5.0)),
                                   search=0.5 if device in ("reticam", "apollo") else 0.7)
        fovea = None
        if disc is not None:
            cam = placement.Camera(*c, fov, dev["fov_type"], dev["projection"])
            fovea = imaging.detect_fovea(rgb, cam, disc[:2], eye)
        out.append({"key": key, "label": label, "eye": eye, "device": device, "fov": fov,
                    "fov_type": dev["fov_type"], "projection": dev["projection"],
                    "circle": [round(float(v), 2) for v in c],
                    "disc": None if disc is None else [round(float(v), 2) for v in disc[:2]],
                    "fovea": None if fovea is None else [round(float(v), 2) for v in fovea[:2]],
                    "src": data_url(Image.fromarray(rgb), "JPEG", quality=88)})
    return out


# -- the page ----------------------------------------------------------------------------
def build(out: Path = HERE / "eye3d.html", fragment: Path | None = None) -> Path:
    """Write the page as a whole document (``out``: open it in a browser) and, when asked, as the
    content of a page without its document skeleton (``fragment``: for a host that adds it)."""
    data = {"shaders": shaders(), "model": model(), "textures": textures(), "photos": photos(),
            "devices": DEVICES, "projections": list(proj.PROJECTIONS),
            "projection_labels": dict(proj.PROJECTION_LABELS)}
    page = (HERE / "page.html").read_text(encoding="utf-8")
    css = (HERE / "app.css").read_text(encoding="utf-8")
    js = (HERE / "app.js").read_text(encoding="utf-8")
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = (page.replace("/*@CSS@*/", css)
                .replace("/*@JS@*/", js.replace("</script", "<\\/script"))
                .replace("@DATA@", blob))
    head, body = page.split("<!--/head-->", 1)
    head = head.replace("<!--head-->", "").strip()
    out.write_text('<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
                   '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                   f"{head}\n</head>\n<body>\n{body.strip()}\n</body>\n</html>\n", encoding="utf-8")
    if fragment is not None:
        fragment.write_text(f"{head}\n{body.strip()}\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    frag = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    path = build(fragment=frag)
    print(f"{path} ({path.stat().st_size / 1e6:.1f} MB)")
