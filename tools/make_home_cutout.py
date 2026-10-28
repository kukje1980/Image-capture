"""Keeler 판 홈 화면 사진(제품 사진)에서 장비만 떼어 투명 PNG 로 만든다.

    python tools/make_home_cutout.py              # assets/brand/keeler/home-*.jpg → home-*.png 모두
    python tools/make_home_cutout.py slitlamp     # 하나만

사진마다 배경이 달라 떼는 방법 · 값을 아래 PRESETS 에 둔다 (원본은 사용자 제공, assets/brand/keeler/SOURCE.md).
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.photo_cutout import (  # noqa: E402
    cutout_gradient_background,
    cutout_white_background,
    fade_cut_edges,
    trim_transparent,
)

FOLDER = ROOT / "assets" / "brand" / "keeler"
PRESETS = {
    # 슬릿램프 단독 (옅은 그라데이션 배경 + 바닥 반사) — 바닥에 닿는 선(원근) 아래 반사를 지움
    "slitlamp": lambda img: cutout_gradient_background(
        img, floor_pts=[(0, 583), (268, 583), (285, 588), (700, 588)]),
    # 슬릿램프 + 영상 시스템 (흰 배경) — 가운데 은색 기둥은 바닥 그림자 처리에서 뺌
    "system": lambda img: cutout_white_background(img, protect=(0.478, 0.586, 0.783)),
    # 접안렌즈 확대 (흰 배경 · 왼쪽 · 아래가 잘린 사진) — 렌즈의 얇은 흰 링은 남기고, 잘린 쪽은 서서히 사라지게
    "eyepiece": lambda img: fade_cut_edges(cutout_white_background(
        img, thr=228, soft_lo=180, hole_min=300, floor_frac=1.0, hole_min_radius=6)),
}


def make(name: str) -> Path:
    src = FOLDER / f"home-{name}.jpg"
    img = cv2.imdecode(np.fromfile(str(src), np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"사진을 열 수 없습니다: {src}")
    out = trim_transparent(PRESETS[name](img))
    dst = src.with_suffix(".png")
    ok, buf = cv2.imencode(".png", out, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    if not ok:
        raise SystemExit(f"PNG 로 저장하지 못했습니다: {dst}")
    buf.tofile(str(dst))
    print(f"{dst.relative_to(ROOT)}: {out.shape[1]}×{out.shape[0]}, 장비 {np.mean(out[..., 3] > 0):.0%}")
    return dst


def main(argv: list[str]) -> int:
    for name in argv or list(PRESETS):
        make(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
