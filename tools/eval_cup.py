"""How well the cup is found on one photo — measured on photos whose disc and cup experts outlined.

    python tools/eval_cup.py PATH [--sets REFUGE,Drishti_GS,ORIGA] [--split train|test|all] [--every N]
                             [--disc truth|auto] [--level 0.30]

The photos are not in this repository: "A Fundus Image Dataset for Domain Generalization in Joint
Segmentation of Optic Disc and Optic Cup" (Chen et al. 2023; CC BY 4.0; https://zenodo.org/records/8009107,
616 MB) — 800 × 800 cut-outs round the disc from REFUGE, Drishti-GS, ORIGA and RIGA with a mask each
(0: cup, 128: rim, 255: outside). ``PATH`` is the folder the archive was unpacked into.

What is measured is the cup that 녹내장 분석 → 디스크 C/D draws by itself (``disc3d.height_one_photo`` →
``disc3d.cup_from_surface``), for each way of estimating the shape (밝기 · 혈관 꺾임 · 하이브리드), on the
picture the program would cut: ``FIELD`` disc diameters round the disc's middle.

* ``--disc truth`` (default): inside the expert's disc outline — the cup alone is judged;
* ``--disc auto``: inside the disc margin the program finds itself (``glaucoma.find_disc_margin``).

Per method: the mean and median error of the vertical C/D against the expert's, how often it is within
0.1 and 0.2, the mean signed error (+: the cup is drawn too large), the cup's overlap with the expert's
(Dice), and how often no cup was drawn at all. docs/cup_bends.md has the numbers of the version this
file came with.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fundusview import disc3d  # noqa: E402
from fundusview import glaucoma as G  # noqa: E402

FIELD = 3.5                 # disc diameters across the picture (ui.glaucoma_dialog.DT_EST_FIELD)
SETS = ("REFUGE", "Drishti_GS", "ORIGA")


def cases(root: Path, sets, split: str):
    for name in sets:
        for part in (("train", "test") if split == "all" else (split,)):
            listing = root / f"{name}_{part}.csv"
            if not listing.is_file():
                continue
            with open(listing, newline="") as fh:
                for row in csv.DictReader(fh):
                    yield name, root / row["image"], root / row["mask"]


def read_case(image: Path, mask: Path):
    """``(texture, disc mask, cup mask)`` on the program's own picture (``disc3d.TEX_PX`` across, ``FIELD``
    disc diameters wide), or None for a case that cannot be used (no disc, or it runs off the cut-out)."""
    bgr = cv2.imread(str(image), cv2.IMREAD_COLOR)
    m = cv2.imread(str(mask), cv2.IMREAD_GRAYSCALE)
    if bgr is None or m is None or bgr.shape[:2] != m.shape[:2]:
        return None
    disc, cup = (m < 200).astype(np.uint8), (m < 64).astype(np.uint8)
    if disc.sum() < 400 or cup.sum() < 20:
        return None
    ys, xs = np.nonzero(disc)
    cx, cy = float(xs.mean()), float(ys.mean())
    dd = 0.5 * ((xs.max() - xs.min() + 1) + (ys.max() - ys.min() + 1))        # the disc's diameter (px)
    side = FIELD * dd
    n = disc3d.TEX_PX
    k = n / side
    M = np.float32([[k, 0, n / 2.0 - cx * k], [0, k, n / 2.0 - cy * k]])
    tex = cv2.warpAffine(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), M, (n, n), flags=cv2.INTER_AREA if k < 1 else cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_REPLICATE)
    d = cv2.warpAffine(disc * 255, M, (n, n), flags=cv2.INTER_LINEAR) > 127
    c = cv2.warpAffine(cup * 255, M, (n, n), flags=cv2.INTER_LINEAR) > 127
    return tex, d, c


def outline_of(mask: np.ndarray) -> dict | None:
    found, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not found:
        return None
    p = max(found, key=len).reshape(-1, 2).astype(np.float64)
    return {"poly": p} if len(p) >= 8 else None


def tall(mask: np.ndarray) -> float:
    ys = np.nonzero(mask.any(axis=1))[0]
    return float(ys.max() - ys.min() + 1) if len(ys) else 0.0


def measure(tex, disc_mask, cup_mask, method: str, disc_from: str, level: float):
    """``(vertical C/D found, the expert's, Dice of the cups)`` — the first None where no cup was drawn."""
    truth = tall(cup_mask) / max(tall(disc_mask), 1.0)
    n = disc3d.TEX_PX
    info: dict = {}
    H = disc3d.height_one_photo(tex, 1.0 / FIELD, method, info=info)
    disc = outline_of(disc_mask)
    if disc_from == "auto":
        found = G.find_disc_margin(tex, 1.0 / FIELD)
        disc = {"pts": found["pts"]} if found is not None else None
    if disc is None or not info.get("cup", True):
        return None, truth, 0.0
    kh = H.shape[0] / n
    on_h = {"poly": (G.curve(disc) + 0.5) * kh - 0.5}
    got = disc3d.cup_from_surface(H, on_h, level)
    if got is None:
        return None, truth, 0.0
    edge = (got[1].astype(np.float64) + 0.5) / kh - 0.5
    mine = np.zeros((n, n), np.uint8)
    cv2.fillPoly(mine, [np.round(edge).astype(np.int32)], 1)
    disc_h = float(np.ptp(G.curve(disc)[:, 1])) if disc_from == "auto" else tall(disc_mask)
    v = float(np.ptp(edge[:, 1])) / max(disc_h, 1.0)
    inter = float((mine.astype(bool) & cup_mask).sum())
    dice = 2.0 * inter / max(float(mine.sum() + cup_mask.sum()), 1.0)
    return v, truth, dice


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path")
    ap.add_argument("--sets", default=",".join(SETS))
    ap.add_argument("--split", default="test", choices=("train", "test", "all"))
    ap.add_argument("--every", type=int, default=1)
    ap.add_argument("--disc", default="truth", choices=("truth", "auto"))
    ap.add_argument("--level", type=float, default=disc3d.CUP_LEVEL)
    ap.add_argument("--methods", default=",".join(disc3d.METHODS))
    args = ap.parse_args(argv)
    root = Path(args.path)
    todo = list(cases(root, args.sets.split(","), args.split))[::max(1, args.every)]
    if not todo:
        print(f"no cases under {root} (expected <set>_<split>.csv listings)", file=sys.stderr)
        return 2
    methods = args.methods.split(",")
    rows = {m: [] for m in methods}                 # (set, found, truth, dice)
    t0, used = time.time(), 0
    for name, image, mask in todo:
        case = read_case(image, mask)
        if case is None:
            continue
        used += 1
        for m in methods:
            v, truth, dice = measure(*case, m, args.disc, args.level)
            rows[m].append((name, v, truth, dice))
    print(f"{used} photos ({args.split}; disc: {args.disc}; level {args.level:.2f}) in {time.time() - t0:.0f} s")
    print(f"{'set':<11}{'method':<9}{'n':>5}{'none':>7}{'MAE':>7}{'median':>8}{'≤0.1':>7}{'≤0.2':>7}{'bias':>7}{'Dice':>7}")
    for group in list(dict.fromkeys(r[0] for r in rows[methods[0]])) + ["all"]:
        for m in methods:
            sel = [r for r in rows[m] if group in ("all", r[0])]
            got = [(v, t, d) for _, v, t, d in sel if v is not None]
            if not sel:
                continue
            err = np.array([v - t for v, t, _ in got]) if got else np.zeros(0)
            none = 1.0 - len(got) / len(sel)
            if len(err):
                a = np.abs(err)
                print(f"{group:<11}{m:<9}{len(sel):>5}{none:>7.1%}{a.mean():>7.3f}{np.median(a):>8.3f}{(a <= 0.1).mean():>7.1%}"
                      f"{(a <= 0.2).mean():>7.1%}{err.mean():>+7.3f}{np.mean([d for _, _, d in got]):>7.3f}")
            else:
                print(f"{group:<11}{m:<9}{len(sel):>5}{none:>7.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
