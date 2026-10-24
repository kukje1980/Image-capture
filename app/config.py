"""애플리케이션 설정. %APPDATA%/SlitLampImaging/config.json 에 JSON으로 저장."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, fields
from pathlib import Path

from app import paths

CONFIG_FILE = "config.json"
log = logging.getLogger(__name__)


@dataclass
class AppConfig:
    camera_index: int = 0
    camera_name: str = ""                    # 선택한 카메라 이름 (장치 순서가 바뀌어도 이름으로 다시 찾음)
    camera_backend: str = "dshow"            # dshow(Windows; macOS에선 자동으로 AVFoundation) | avfoundation | any
    capture_width: int = 1920
    capture_height: int = 1080
    source_mode: str = "device"              # device | file | synthetic
    test_file_path: str = ""                 # source_mode=file 일 때 재생할 파일
    media_root: str = ""                     # 기본 저장 루트 (비면 appdata/media)
    export_root: str = ""                    # 동시 저장 폴더 (비면 appdata/export)
    db_path: str = ""                        # SQLite 경로 (비면 appdata/slitlamp.db)
    photo_format: str = "png"                # png | jpg
    video_fallback_fourcc: str = "mp4v"      # ffmpeg 실패 시 cv2 폴백 코덱
    subfolder_template: str = "{chart_no}_{patient_id}/{date}"
    thumbnail_max_side: int = 120
    newest_on_top: bool = True
    theme: str = "dark"                      # dark(기본, 영상 작업 공간) | light
    clinic_name: str = ""                    # 인쇄 보고서 머리말 기관명
    px_per_mm: float = 0.0                   # 측정 눈금 보정 (0 = 미보정, px 단위)
    brand: str = ""                          # 화면 브랜드 (비면 기본, "keeler" = Keeler 전용)
    shortcuts: dict = field(default_factory=dict)   # 사용자 지정 단축키 {동작 id: "키"} (app/shortcuts.py)

    @classmethod
    def config_path(cls) -> Path:
        return paths.get_appdata_dir() / CONFIG_FILE

    @classmethod
    def load(cls) -> "AppConfig":
        cfg = cls()
        p = cls.config_path()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                defaults = cls()
                for f in fields(cls):
                    if f.name not in data:
                        continue
                    v, d = data[f.name], getattr(defaults, f.name)
                    # 형식이 다른 값(예: "camera_index": "1", "shortcuts": [..])은 버리고 기본값 유지
                    if isinstance(d, bool) != isinstance(v, bool):
                        continue
                    if isinstance(d, float) and isinstance(v, int):
                        v = float(v)
                    if isinstance(v, type(d)):
                        setattr(cfg, f.name, v)
                    else:
                        log.warning("config %s 값 형식이 잘못되어 무시: %r", f.name, v)
            except Exception:
                # 손상된 설정은 지우지 않고 옆에 보관한 뒤 기본값으로 시작 (저장 위치 등을 나중에 되살릴 수 있게)
                log.exception("config.json 을 읽지 못했습니다 — config.json.broken 으로 보관")
                try:
                    os.replace(p, p.with_name(p.name + ".broken"))
                except OSError:
                    pass
        cfg._apply_defaults()
        return cfg

    def _apply_defaults(self) -> None:
        base = paths.get_appdata_dir()
        if not self.media_root:
            self.media_root = str(base / "media")
        if not self.export_root:
            self.export_root = str(base / "export")
        if not self.db_path:
            self.db_path = str(base / "slitlamp.db")
        paths.ensure_dir(self.media_root)
        paths.ensure_dir(Path(self.db_path).parent)

    def save(self) -> None:
        p = self.config_path()
        paths.ensure_dir(p.parent)
        data = {f.name: getattr(self, f.name) for f in fields(self)}
        # 임시 파일에 다 쓴 뒤 바꿔치기 — 저장 중 꺼져도 설정 파일이 반쯤 지워지지 않는다
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
