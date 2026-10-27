"""브랜드 홈 사진(흰 배경 제품 사진)에서 장비만 떼어 투명 PNG 로 만든다.

    python tools/make_home_cutout.py assets/brand/keeler/home.jpg assets/brand/keeler/home.png

Keeler 사진은 가운데 은색 기둥이 바닥 그림자 처리에 지워지지 않게 --protect 0.478,0.586,0.783 (x0,x1,y1 비율) 을 준다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.photo_cutout import cutout_white_background, trim_transparent  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--protect", default="0.478,0.586,0.783")
    args = ap.parse_args()
    img = cv2.imdecode(np.fromfile(args.src, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        print(f"사진을 열 수 없습니다: {args.src}")
        return 1
    protect = tuple(float(v) for v in args.protect.split(",")) if args.protect else None
    out = trim_transparent(cutout_white_background(img, protect=protect))
    ok, buf = cv2.imencode(".png", out, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    if not ok:
        return 1
    buf.tofile(args.dst)
    print(f"{args.dst}: {out.shape[1]}×{out.shape[0]}, 장비 {np.mean(out[..., 3] > 0):.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
