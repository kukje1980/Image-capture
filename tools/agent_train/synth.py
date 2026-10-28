"""합성 슬릿램프 장면 생성기 — 학습 파이프라인 점검용 (실제 데이터를 대신하지 않는다).

    python tools/agent_train/synth.py <출력폴더> [--per-class 60]

라벨별 폴더에 jpg 를 만든다: diffuse / slit / retro / fluorescein / ir_meibo / external / unusable.
조명 색·슬릿 띠·후방조명 원·피부색 등 '장면을 구분하는 성질'만 흉내 낸 그림이다.
train_scene.py 로 학습이 끝까지 돌아가는지, 앱이 모델을 읽어 추론하는지 확인하는 데 쓴다.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

W, H = 640, 360


def _iris(rng, bgr=(60, 90, 120), pupil=35, radius=110, noise=18):
    img = np.zeros((H, W, 3), np.uint8)
    img[:] = (10, 10, 10)
    cx, cy = W // 2 + int(rng.integers(-30, 30)), H // 2 + int(rng.integers(-20, 20))
    cv2.circle(img, (cx, cy), radius + 50, (150, 160, 170), -1)          # 공막
    cv2.circle(img, (cx, cy), radius, bgr, -1)                           # 홍채
    tex = rng.integers(-noise, noise, (H, W, 1)).astype(np.int16)
    img = np.clip(img.astype(np.int16) + tex, 0, 255).astype(np.uint8)
    cv2.circle(img, (cx, cy), pupil, (8, 8, 8), -1)                      # 동공
    return img, (cx, cy), radius


def diffuse(rng):
    img, _, _ = _iris(rng, bgr=tuple(int(v) for v in rng.integers(40, 140, 3)))
    glare = np.zeros_like(img)
    cv2.circle(glare, (W // 2 + 60, H // 2 - 40), 10, (255, 255, 255), -1)
    return cv2.addWeighted(img, 1.0, glare, 0.9, 0)


def slit(rng):
    img, (cx, cy), r = _iris(rng)
    img = (img * 0.35).astype(np.uint8)
    w = int(rng.integers(6, 22))
    ang = float(rng.uniform(-25, 25))
    band = np.zeros_like(img)
    cv2.rectangle(band, (cx - w // 2, cy - r - 40), (cx + w // 2, cy + r + 40), (235, 245, 255), -1)
    m = cv2.getRotationMatrix2D((cx, cy), ang, 1.0)
    band = cv2.warpAffine(band, m, (W, H))
    return np.clip(img.astype(np.int16) + band.astype(np.int16), 0, 255).astype(np.uint8)


def retro(rng):
    img = np.full((H, W, 3), 12, np.uint8)
    cx, cy = W // 2 + int(rng.integers(-20, 20)), H // 2
    cv2.circle(img, (cx, cy), 95, (200, 110, 60), -1)                     # 밝은 붉은 반사
    cv2.circle(img, (cx, cy), 95, (40, 40, 40), 6)
    for _ in range(int(rng.integers(0, 6))):                              # 혼탁(검은 점)
        cv2.circle(img, (cx + int(rng.integers(-60, 60)), cy + int(rng.integers(-60, 60))),
                   int(rng.integers(3, 9)), (30, 20, 15), -1)
    return img


def fluorescein(rng):
    img, (cx, cy), r = _iris(rng, bgr=(120, 40, 10))
    img = cv2.addWeighted(img, 0.6, np.full_like(img, (140, 40, 0)), 0.4, 0)   # 코발트블루
    for _ in range(int(rng.integers(2, 12))):
        cv2.circle(img, (cx + int(rng.integers(-r, r)), cy + int(rng.integers(-r, r))),
                   int(rng.integers(3, 12)), (60, 230, 200), -1)                 # 녹황색 염색
    return img


def ir_meibo(rng):
    g = np.full((H, W), 90, np.uint8)
    for i in range(16):
        x = 40 + i * 36 + int(rng.integers(-4, 4))
        cv2.line(g, (x, 60), (x + int(rng.integers(-10, 10)), 300), 190, int(rng.integers(5, 10)))
    g = cv2.GaussianBlur(g, (0, 0), 2)
    g = np.clip(g.astype(np.int16) + rng.integers(-10, 10, (H, W)), 0, 255).astype(np.uint8)
    return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)


def external(rng):
    img = np.zeros((H, W, 3), np.uint8)
    img[:] = (int(rng.integers(120, 160)), int(rng.integers(150, 190)),
              int(rng.integers(190, 230)))                                        # 피부
    cv2.ellipse(img, (W // 2, H // 2), (150, 60), 0, 0, 360, (230, 230, 235), -1)   # 공막
    cv2.circle(img, (W // 2, H // 2), 48, (70, 90, 110), -1)
    cv2.circle(img, (W // 2, H // 2), 18, (10, 10, 10), -1)
    return img


def unusable(rng):
    if rng.random() < 0.5:
        return np.full((H, W, 3), int(rng.integers(0, 12)), np.uint8)
    return np.full((H, W, 3), int(rng.integers(240, 256)), np.uint8)


GENERATORS = {"diffuse": diffuse, "slit": slit, "retro": retro, "fluorescein": fluorescein,
              "ir_meibo": ir_meibo, "external": external, "unusable": unusable}


def make_dataset(out, per_class: int = 60, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    out = Path(out)
    counts = {}
    for label, fn in GENERATORS.items():
        d = out / label
        d.mkdir(parents=True, exist_ok=True)
        for i in range(per_class):
            img = fn(rng)
            if rng.random() < 0.3:
                img = cv2.GaussianBlur(img, (0, 0), float(rng.uniform(0.5, 2.0)))
            cv2.imwrite(str(d / f"{label}_{i:04d}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        counts[label] = per_class
    return counts


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--per-class", type=int, default=60)
    a = ap.parse_args()
    print(make_dataset(a.out, a.per_class))
