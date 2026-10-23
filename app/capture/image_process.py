"""이미지 보정 (Pro 모드 Image Process).

원본은 건드리지 않고 표시/저장용 보정본을 만든다. 입력·출력 모두 BGR uint8.

- brightness: -100 ~ +100 (가산)
- contrast:   0.2 ~ 3.0  (중간값 127.5 기준 배율)
- gamma:      0.2 ~ 3.0  (1.0 = 변화 없음, >1 밝게)
- negative:   반전(NEGA)
- channel:    "rgb" | "green"(Red-free, 혈관·출혈 관찰) | "gray"
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Adjust:
    brightness: float = 0.0
    contrast: float = 1.0
    gamma: float = 1.0
    negative: bool = False
    channel: str = "rgb"

    def is_identity(self) -> bool:
        return (self.brightness == 0 and self.contrast == 1.0 and self.gamma == 1.0
                and not self.negative and self.channel == "rgb")


def apply_adjust(frame: np.ndarray, adj: Adjust) -> np.ndarray:
    if frame is None:
        return frame
    if adj.is_identity():
        return frame.copy()
    img = frame.astype(np.float32)

    if adj.channel == "green":
        g = img[..., 1]
        img = np.stack([g, g, g], axis=-1)
    elif adj.channel == "gray":
        # BGR → 휘도
        y = img[..., 0] * 0.114 + img[..., 1] * 0.587 + img[..., 2] * 0.299
        img = np.stack([y, y, y], axis=-1)

    img = (img - 127.5) * float(adj.contrast) + 127.5 + float(adj.brightness)
    np.clip(img, 0, 255, out=img)
    if adj.gamma != 1.0:
        img = 255.0 * np.power(img / 255.0, 1.0 / float(adj.gamma))
    if adj.negative:
        img = 255.0 - img
    return np.clip(img, 0, 255).astype(np.uint8)
