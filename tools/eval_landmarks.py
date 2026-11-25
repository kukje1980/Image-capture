"""How well the optic disc and the fovea are found — measured on photos marked by experts.

    python tools/eval_landmarks.py "PATH/C. Localization" [--split test|train|all] [--fov 34.8]
                                   [--poor all|blur,dark,…] [--every N]

The photos are not in this repository: IDRiD, "C. Localization" (516 photos of 4288 × 2848 with the
centres of the optic disc and the fovea — Porwal et al., Med Image Anal 2020; CC BY 4.0;
https://zenodo.org/records/17219542, 213 MB). Success, as usual in the literature: within one disc
radius of the expert's mark; here a disc radius is taken as 0.115 × the radius of the photo's field
(smaller than the discs are: strict). ``--fov``: the photos' field as fundusview's camera model sees
it (the field of view with which disc and fovea lie 21.5° apart at the eye's centre: 34.8° "external"
for this camera — the 50° of its data sheet puts the macula a disc diameter off).

``--poor`` repeats the measurement on poorly taken versions of the same photos: out of focus, under-
and over-exposed, hazy (cataract), unevenly lit, with a band of glare at the rim (where the band covers
the disc or the macula the photo is left out), noisy, flat, and with lashes reaching in.

docs/landmarks.md has the numbers of the version this file came with.
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fundusview import imaging, placement  # noqa: E402


def _field(rgb):
    return rgb.max(axis=2) > 12


def blur(rgb, rng):            # out of focus / cataract
    return cv2.GaussianBlur(rgb, (0, 0), 6.0)


def dark(rgb, rng):            # under-exposed (small pupil)
    return (255.0 * (rgb / 255.0) ** 1.6 * 0.6).astype(np.uint8)


def bright(rgb, rng):          # over-exposed
    out = np.clip(255.0 * (rgb / 255.0) ** 0.5 * 1.25, 0, 255)
    return np.where(_field(rgb)[..., None], out, rgb).astype(np.uint8)


def haze(rgb, rng):            # media opacity: contrast lost, a grey-white veil
    veil = np.array([170.0, 150.0, 120.0])
    out = cv2.GaussianBlur(rgb, (0, 0), 3.0).astype(np.float64) * 0.4 + veil * 0.6
    return np.where(_field(rgb)[..., None], out, rgb).astype(np.uint8)


def uneven(rgb, rng):          # one side dark, the other flared
    h, w = rgb.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    a = rng.uniform(0, 2 * np.pi)
    t = ((xx - w / 2) * np.cos(a) + (yy - h / 2) * np.sin(a)) / (0.5 * h)
    return np.clip(rgb * np.clip(1.0 + 0.75 * t, 0.2, 2.2)[..., None], 0, 255).astype(np.uint8)


def glare(rgb, rng):           # the lid's reflex: a sharp bright band along one side of the field
    h, w = rgb.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    a = rng.uniform(0, 2 * np.pi)
    d = (xx - w / 2) * np.cos(a) + (yy - h / 2) * np.sin(a)
    along = ((xx - w / 2) * -np.sin(a) + (yy - h / 2) * np.cos(a)) / h
    edge = 0.5 * h * rng.uniform(0.45, 0.7) + 0.03 * h * np.sin(along * 14)
    t = (np.clip((d - edge) / (0.02 * h), 0, 1) * _field(rgb))[..., None]
    return np.clip(rgb * (1 - t) + np.array([255.0, 230.0, 110.0]) * t, 0, 255).astype(np.uint8)


def noise(rgb, rng):           # high gain
    return np.where(_field(rgb)[..., None], np.clip(rgb + rng.normal(0, 22, rgb.shape), 0, 255), rgb).astype(np.uint8)


def lowcon(rgb, rng):          # flat
    f = _field(rgb)[..., None]
    m = rgb[f[..., 0]].mean(axis=0)
    return np.where(f, np.clip(m + (rgb - m) * 0.35, 0, 255), rgb).astype(np.uint8)


def lash(rgb, rng):            # lashes / the lid's shadow: dark streaks reaching in from one side
    out = rgb.copy()
    h, w = rgb.shape[:2]
    side = rng.integers(0, 2)
    for _ in range(14):
        x0 = rng.uniform(0.15, 0.85) * w
        x1 = x0 + rng.uniform(-0.08, 0.08) * w
        y1 = h * (rng.uniform(0.6, 0.8) if side else rng.uniform(0.2, 0.4))
        cv2.line(out, (int(x0), h - 1 if side else 0), (int(x1), int(y1)), (10, 6, 4), int(rng.integers(3, 9)), cv2.LINE_AA)
    return cv2.GaussianBlur(out, (0, 0), 1.2)


POOR = {"blur": blur, "dark": dark, "bright": bright, "haze": haze, "uneven": uneven, "glare": glare,
        "noise": noise, "lowcon": lowcon, "lash": lash}
SIDE = 1072                    # the photos reduced to this (as an import analyses them)


def load(root: Path, split: str):
    marks: dict = {}
    for kind, folder in (("disc", "1. Optic Disc Center Location"), ("fovea", "2. Fovea Center Location")):
        for f in (root / "2. Groundtruths" / folder).glob("*.csv"):
            part = "test" if "Testing" in f.name else "train"
            for row in csv.reader(open(f, encoding="utf-8-sig")):
                if len(row) >= 3 and row[0].startswith("IDRiD_") and row[1].strip():
                    marks.setdefault((part, row[0]), {})[kind] = (float(row[1]), float(row[2]))
    for (part, name), m in sorted(marks.items()):
        if split not in ("all", part) or len(m) < 2:
            continue
        folder = "a. Training Set" if part == "train" else "b. Testing Set"
        im = Image.open(root / "1. Original Images" / folder / f"{name}.jpg")
        full = im.size[0]
        im.draft("RGB", (SIDE, SIDE))
        im = im.convert("RGB")
        if max(im.size) > SIDE:
            k = SIDE / max(im.size)
            im = im.resize((round(im.size[0] * k), round(im.size[1] * k)), Image.BILINEAR)
        s = im.size[0] / full
        yield name, np.asarray(im), tuple(v * s for v in m["disc"]), tuple(v * s for v in m["fovea"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("root", type=Path)
    ap.add_argument("--split", default="test", choices=("test", "train", "all"))
    ap.add_argument("--fov", type=float, default=34.8)
    ap.add_argument("--poor", default="")
    ap.add_argument("--every", type=int, default=1)
    a = ap.parse_args()
    photos = list(load(a.root, a.split))[::a.every]
    kinds = ["clean"] + (list(POOR) if a.poor == "all" else [k for k in a.poor.split(",") if k])
    print(f"{len(photos)} photos ({a.split}), field {a.fov}°")
    print(f"{'':8s} {'disc ≤1R':>9s} {'median':>7s} {'none':>5s} | {'fovea ≤1R':>9s} {'median':>7s} {'none':>5s} | {'eye':>6s} {'ms':>4s} {'n':>4s}")
    for kind in kinds:
        de, fe, eyes, t0 = [], [], [], time.time()
        for i, (name, rgb, disc_true, fovea_true) in enumerate(photos):
            if kind != "clean":
                before, rgb = rgb, POOR[kind](rgb, np.random.default_rng(i))
                if kind == "glare":           # the band over the disc or the macula: nothing to find there
                    if any(np.abs(rgb[int(y) - 6:int(y) + 7, int(x) - 6:int(x) + 7].astype(int)
                                  - before[int(y) - 6:int(y) + 7, int(x) - 6:int(x) + 7]).mean() > 25
                           for x, y in (disc_true, fovea_true)):
                        continue
            circle = imaging.detect_circle(rgb)
            cam = placement.Camera(*circle, a.fov, "external", "perspective")
            disc, fovea = imaging.detect_landmarks(rgb, cam, None)
            R = 0.115 * circle[2]
            de.append(math.hypot(disc[0] - disc_true[0], disc[1] - disc_true[1]) / R if disc is not None else 99.0)
            fe.append(math.hypot(fovea[0] - fovea_true[0], fovea[1] - fovea_true[1]) / R if fovea is not None else 99.0)
            if fovea is not None:
                eyes.append(fovea[3] == ("OD" if disc_true[0] > fovea_true[0] else "OS"))
        if not de:
            continue
        de, fe = np.array(de), np.array(fe)
        print(f"{kind:8s} {100 * (de <= 1).mean():8.1f}% {np.median(de):6.2f}R {(de > 90).sum():5d} | "
              f"{100 * (fe <= 1).mean():8.1f}% {np.median(fe):6.2f}R {(fe > 90).sum():5d} | "
              f"{100 * np.mean(eyes) if eyes else 0:5.1f}% {(time.time() - t0) / len(de) * 1000:4.0f} {len(de):4d}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
