"""애플리케이션 설정. %APPDATA%/SlitLampImaging/config.json 에 JSON으로 저장."""
from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path

from app import paths

CONFIG_FILE = "config.json"


@dataclass
class AppConfig:
    camera_index: int = 0
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
                known = {f.name for f in fields(cls)}
                for k, v in data.items():
                    if k in known:
                        setattr(cfg, k, v)
            except Exception:
                pass  # 손상된 설정은 무시하고 기본값 사용
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
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
