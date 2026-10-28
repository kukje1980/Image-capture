"""촬영 모드 — 자주 쓰는 카메라 · 촬영 설정을 이름 붙여 저장하고 촬영 중에 바로 바꾼다.

카메라 값은 app/capture/camera_props.py (노출 · 게인 · 밝기 · 대비 · 채도 · 선명도 · 화이트밸런스, 자동 노출 · 자동 WB) 를 쓴다.
모드에 없는 항목은 카메라를 건드리지 않고, 자동 노출 · 자동 WB 가 없으면 자동으로 둔다.

한 모드에 들어가는 것: 해상도 · 카메라 조정값(camera_props) · Smart 자동 촬영 방식 · 피킹 · 분할 칸 수.
config.capture_presets 에 dict 목록으로, 지금 모드 이름은 config.active_preset 에 저장한다.
"""
from __future__ import annotations

from app.capture import camera_props

DEFAULT_NAME = "기본 (자동)"
FIELDS = ("capture_width", "capture_height", "camera_props", "smart_mode", "smart_peaking", "split_count")


def from_config(config, name: str) -> dict:
    """지금 설정으로 모드 하나를 만든다."""
    return {
        "name": name.strip() or DEFAULT_NAME,
        "capture_width": int(config.capture_width),
        "capture_height": int(config.capture_height),
        "camera_props": camera_props.sanitize(getattr(config, "camera_props", {})),
        "smart_mode": getattr(config, "smart_mode", "off") or "off",
        "smart_peaking": bool(getattr(config, "smart_peaking", False)),
        "split_count": int(getattr(config, "split_count", 4) or 4),
    }


def normalize(p: dict, config) -> dict:
    base = from_config(config, str(p.get("name") or DEFAULT_NAME))
    for k in FIELDS:
        if k in p and p[k] is not None:
            base[k] = p[k]
    base["camera_props"] = camera_props.sanitize(base.get("camera_props"))
    base["capture_width"], base["capture_height"] = int(base["capture_width"]), int(base["capture_height"])
    base["split_count"] = int(base["split_count"]) if int(base["split_count"]) in (2, 4, 6, 8, 16) else 4
    if base["smart_mode"] not in ("off", "freeze", "snapshot"):
        base["smart_mode"] = "off"
    base["smart_peaking"] = bool(base["smart_peaking"])
    return base


def all_presets(config) -> list[dict]:
    """저장한 모드 목록 (없으면 '기본 (자동)' 하나). 이름이 겹치면 앞의 것만."""
    out, seen = [], set()
    for p in getattr(config, "capture_presets", []) or []:
        if isinstance(p, dict) and p.get("name") and p["name"] not in seen:
            seen.add(p["name"])
            out.append(normalize(p, config))
    if not out:
        out.append(default_preset(config))
    return out


def default_preset(config) -> dict:
    """'기본 (자동)': 카메라 자동 · Smart 끔 · 피킹 끔 · 4분할 (해상도는 지금 설정)."""
    d = from_config(config, DEFAULT_NAME)
    d.update(camera_props={}, smart_mode="off", smart_peaking=False, split_count=4)
    return d


def find(config, name: str) -> dict | None:
    return next((p for p in all_presets(config) if p["name"] == name), None)


def save(config, preset: dict) -> None:
    """같은 이름이 있으면 바꾸고, 없으면 끝에 더한다."""
    preset = normalize(preset, config)
    lst = all_presets(config)
    for i, p in enumerate(lst):
        if p["name"] == preset["name"]:
            lst[i] = preset
            break
    else:
        lst.append(preset)
    config.capture_presets = lst


def device_requests(props: dict) -> dict:
    """모드를 카메라에 걸 때 보낼 값: 모드의 값 + (지정하지 않은) 자동 노출 · 자동 WB 는 자동(1)."""
    req = dict(camera_props.sanitize(props))
    for auto_key, manual_key in (("auto_exposure", "exposure"), ("auto_wb", "wb_temperature")):
        if auto_key not in req:
            req[auto_key] = 0.0 if manual_key in req else 1.0     # 수동 값을 지정했으면 자동을 끈다
    return req


def apply_to_config(config, preset: dict) -> bool:
    """모드를 설정에 반영. 해상도가 바뀌어 카메라를 다시 열어야 하면 True."""
    preset = normalize(preset, config)
    restart = (int(config.capture_width), int(config.capture_height)) != (preset["capture_width"], preset["capture_height"])
    config.capture_width, config.capture_height = preset["capture_width"], preset["capture_height"]
    config.camera_props = dict(preset["camera_props"])
    config.smart_mode = preset["smart_mode"]
    config.smart_peaking = preset["smart_peaking"]
    config.split_count = preset["split_count"]
    config.active_preset = preset["name"]
    return restart
