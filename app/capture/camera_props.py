"""카메라 속성 (노출·게인·밝기·화이트밸런스 등) — 장치 드라이버(UVC)에 직접 설정.

값의 범위는 장치마다 다르므로 Windows DirectShow 의 일반적인 범위를 기본으로 쓴다.
장치가 지원하지 않는 속성은 설정이 무시된다(set_property 가 False). 설정값은 config.json 의
camera_props 에 저장되어 다음에 카메라를 열 때 다시 적용된다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Prop:
    key: str
    label: str
    lo: float
    hi: float
    default: float
    step: float = 1.0
    toggle: bool = False          # 켜기/끄기 (자동 노출 등)


PROPS: list[Prop] = [
    Prop("auto_exposure", "자동 노출", 0, 1, 1, toggle=True),
    Prop("exposure", "노출 (셔터)", -13, -1, -6),
    Prop("gain", "게인 (감도)", 0, 100, 0),
    Prop("brightness", "밝기", -64, 64, 0),
    Prop("contrast", "대비", 0, 100, 50),
    Prop("saturation", "채도", 0, 100, 50),
    Prop("sharpness", "선명도", 0, 100, 50),
    Prop("auto_wb", "자동 화이트밸런스", 0, 1, 1, toggle=True),
    Prop("wb_temperature", "색온도 (K)", 2800, 6500, 4600, step=100),
]
BY_KEY = {p.key: p for p in PROPS}


def cv2_id(key: str):
    """OpenCV CAP_PROP_* 번호 (없으면 None)."""
    try:
        import cv2
    except ImportError:  # pragma: no cover
        return None
    return {
        "auto_exposure": cv2.CAP_PROP_AUTO_EXPOSURE,
        "exposure": cv2.CAP_PROP_EXPOSURE,
        "gain": cv2.CAP_PROP_GAIN,
        "brightness": cv2.CAP_PROP_BRIGHTNESS,
        "contrast": cv2.CAP_PROP_CONTRAST,
        "saturation": cv2.CAP_PROP_SATURATION,
        "sharpness": cv2.CAP_PROP_SHARPNESS,
        "auto_wb": cv2.CAP_PROP_AUTO_WB,
        "wb_temperature": cv2.CAP_PROP_WB_TEMPERATURE,
    }.get(key)


def device_value(key: str, value: float) -> float:
    """UI 값 → 드라이버 값. 자동 노출은 관례상 0.75(자동) / 0.25(수동)."""
    if key == "auto_exposure":
        return 0.75 if value else 0.25
    return float(value)


def clamp(key: str, value) -> float:
    p = BY_KEY[key]
    v = float(value)
    if p.toggle:
        return 1.0 if v else 0.0
    return min(p.hi, max(p.lo, v))


def sanitize(props: dict | None) -> dict:
    """저장된 값 중 아는 속성만 범위 안으로."""
    out = {}
    for k, v in (props or {}).items():
        if k in BY_KEY and isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = clamp(k, v)
        elif k in BY_KEY and isinstance(v, bool):
            out[k] = 1.0 if v else 0.0
    return out
