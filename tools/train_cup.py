"""Fit the cup model of ``fundusview/cuplearn.py`` and write ``fundusview/cup_weights.py``.

    python tools/train_cup.py PATH [--lam 0.03] [--cv]

``PATH``: the unpacked photos of https://zenodo.org/records/8009107 (see tools/eval_cup.py). The model is
fitted on the **train** lists of REFUGE, Drishti-GS and ORIGA only; the test lists are for
tools/eval_cup.py. ``--cv``: five-fold cross-validation on the training photos instead of writing weights.
"""
from __future__ import annotations

import argparse
import base64
import io
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import eval_cup as E  # noqa: E402
from fundusview import cuplearn as L  # noqa: E402


def load(root: Path, split: str):
    """Profiles, the expert's cup reach (part of the disc's radius, per direction) for every usable photo."""
    Ps, Ys = [], []
    for _name, image, mask in E.cases(root, E.SETS, split):
        case = E.read_case(image, mask)
        if case is None:
            continue
        tex, d, c = case
        disc, cup = E.outline_of(d), E.outline_of(c)
        if disc is None or cup is None:
            continue
        (cx, cy), rad = L.disc_polar(disc["poly"])
        ang = np.arctan2(cup["poly"][:, 1] - cy, cup["poly"][:, 0] - cx)
        r = np.hypot(cup["poly"][:, 0] - cx, cup["poly"][:, 1] - cy)
        order = np.argsort(ang)
        want = np.arange(L.A) * 2 * np.pi / L.A
        want = np.where(want > np.pi, want - 2 * np.pi, want)
        reach = np.interp(want, np.concatenate([ang[order] - 2 * np.pi, ang[order], ang[order] + 2 * np.pi]),
                          np.tile(r[order], 3))
        Ps.append(L.profiles(tex, disc["poly"]))
        Ys.append(np.clip(reach / np.maximum(rad, 1.0), 0.0, 1.0))
    return np.stack(Ps), np.stack(Ys).astype(np.float32)


def fit(Ps, Ys, which: str, lam: float) -> dict:
    F = np.concatenate([L.design(P, which) for P in Ps]).astype(np.float64)
    y = Ys.reshape(-1).astype(np.float64)
    mu, sd = F.mean(0), F.std(0) + 1e-6
    Z = (F - mu) / sd
    w = np.linalg.solve(Z.T @ Z + lam * len(Z) * np.eye(Z.shape[1]), Z.T @ (y - y.mean()))
    return {f"{which}_mu": mu.astype(np.float32), f"{which}_sd": sd.astype(np.float32),
            f"{which}_w": w.astype(np.float32), f"{which}_b": np.float32(y.mean())}


def vertical(ratio: np.ndarray) -> float:
    """The vertical C/D of a cup that reaches ``ratio`` of a round disc's radius in each direction."""
    s = np.sin(np.arange(L.A) * 2 * np.pi / L.A)
    return float((ratio * s).max() - (ratio * s).min()) / 2.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path")
    ap.add_argument("--lam", type=float, default=0.03)
    ap.add_argument("--cv", action="store_true")
    args = ap.parse_args(argv)
    Ps, Ys = load(Path(args.path), "train")
    print(f"{len(Ps)} training photos")
    if args.cv:
        fold = np.random.default_rng(1).permutation(len(Ps)) % 5
        for which in L.CHANNELS:
            err, rad = [], []
            for k in range(5):
                m = fit(Ps[fold != k], Ys[fold != k], which, args.lam)
                for P, y in zip(Ps[fold == k], Ys[fold == k]):
                    got = L.ratio(P, which, m)
                    err.append(abs(vertical(got) - vertical(y)))
                    rad.append(float(np.abs(got - y).mean()))
            e = np.array(err)
            print(f"{which:8s} reach MAE {np.mean(rad):.3f}  vertical C/D MAE {e.mean():.3f}  median {np.median(e):.3f}  "
                  f"≤0.1 {(e <= 0.1).mean():.1%}  ≤0.2 {(e <= 0.2).mean():.1%}")
        return 0
    model: dict = {}
    for which in L.CHANNELS:
        model.update(fit(Ps, Ys, which, args.lam))
    buf = io.BytesIO()
    np.savez_compressed(buf, **model)
    text = base64.b64encode(buf.getvalue()).decode("ascii")
    lines = "\n".join(f'    "{text[i:i + 100]}"' for i in range(0, len(text), 100))
    out = Path(__file__).resolve().parents[1] / "fundusview" / "cup_weights.py"
    out.write_text('"""The weights of ``cuplearn.py`` (a compressed .npz, base64) — written by tools/train_cup.py:\n'
                   f'ridge regression (λ = {args.lam:g}) on {len(Ps)} photos with expert disc and cup outlines (the train '
                   'lists of REFUGE,\nDrishti-GS and ORIGA in https://zenodo.org/records/8009107, CC BY 4.0). Not edited by hand.'
                   f'"""\nDATA = (\n{lines}\n)\n', encoding="utf-8")
    print(f"wrote {out} ({len(text) / 1024:.0f} kB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
