"""Persistent user settings (JSON).

Stored per user in ``%APPDATA%\\FundusViewer\\settings.json`` on Windows,
``~/Library/Application Support/FundusViewer`` on macOS (or
``~/.config/fundusviewer`` elsewhere). ``FUNDUSVIEW_HOME`` overrides the
directory, which keeps tests and portable installs self-contained.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import APP_NAME

# What happens to a source file after it has been imported.
ACTION_COPY = "copy"            # copy into the library, leave the original (default, safe)
ACTION_MOVE = "move"            # move into the library (the drop folder is emptied)
ACTION_REFERENCE = "reference"  # leave in place, the DB points at the original path
ACTIONS = (ACTION_COPY, ACTION_MOVE, ACTION_REFERENCE)


def config_dir() -> Path:
    env = os.getenv("FUNDUSVIEW_HOME")
    if env:
        return Path(env)
    appdata = os.getenv("APPDATA")
    if appdata:  # Windows
        return Path(appdata) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path.home() / ".config" / APP_NAME.lower()


def default_library_dir() -> Path:
    env = os.getenv("FUNDUSVIEW_HOME")
    if env:
        return Path(env) / "Library"
    return Path.home() / "Documents" / f"{APP_NAME}Library"


def default_inbox_dir() -> Path:
    """Folder anyone can drop photos into (USB copies, e-mail attachments ...)."""
    env = os.getenv("FUNDUSVIEW_HOME")
    if env:
        return Path(env) / "Inbox"
    return Path.home() / "Documents" / "안저사진 가져오기"


@dataclass
class WatchFolder:
    path: str
    profile: str = "auto"         # camera profile key (see profiles.py) or "auto"
    recursive: bool = True
    action: str = ACTION_COPY
    polling: bool = False         # use polling (network drives / NAS where change events are unreliable)
    enabled: bool = True


@dataclass
class Settings:
    library_dir: str = ""
    watch_folders: list[WatchFolder] = field(default_factory=list)
    watch_on_startup: bool = True
    # Seconds a new file's size must stay unchanged before it is imported
    # (the capture software may still be writing it).
    stable_seconds: float = 1.5
    # Safety-net rescan interval for missed change events (seconds, 0 = off).
    rescan_seconds: int = 60
    # "auto" | "desktop" | "software" — software = bundled Mesa llvmpipe
    # (opengl32sw.dll), for PCs whose GPU driver lacks OpenGL 2.1.
    opengl: str = "auto"
    # 3D eye: "detailed" (자세히, anatomical — as the web page) or "simple" (간단히, light-weight, for slow PCs;
    # 간단히 | 자세히 in the bar above the 3D eye)
    view3d_detail: str = "detailed"
    panel3d: bool = False           # 3D: the settings beside the eye are open ([설정] in the bar; closed at first)
    # 3D 마우스 휠 (3D 설정 → 마우스 휠 · 설정 → 일반): "zoom" — 커서 쪽으로 확대 (the depth on the 깊이
    # 막대 beside the eye) · "depth" — 자르는 깊이 (내부에서는 확대) · "walk" — 들어가기 (각막 → 망막, 뒤로
    # 나오기). walk_click3d: a click on the cornea picks the anterior segment, and the wheel walks in meanwhile
    # (zoom · depth)
    wheel3d: str = "zoom"
    # 3D 깊이 막대 · 배율 막대 over the eye: lying ("h") or standing ("v") and where they were dragged to
    # (depth_bar.FloatBar.state(): "" as at first, "h", "v:0.250:0.900" — fractions of the free room)
    depth_bar3d: str = ""
    zoom_bar3d: str = ""
    walk_click3d: bool = True
    # Motion and 3D effects (보기 → 부드러운 움직임; 3D 안구: 입체 조명, 자동 회전)
    smooth_motion: bool = True
    relief3d: bool = False          # 3D 입체 조명 (off: the photo keeps its own brightness, as taken)
    auto_rotate3d: bool = True
    glass3d: int = 80               # 공막 투명도 0 … 100 (0 = the opaque white sclera)
    align3d: bool = True            # 3D: the photo's fovea / disc at their place on the eye (placement.py)
    surface3d: bool = False         # 3D 망막 입체: 표면 높낮이 (the retina raised by its relief, relief.py;
                                    # off: the photo lies smooth on the retina, as taken)
    surface_height3d: int = 45      # … 높이 0 … 100
    simple3d: bool = False          # 3D 단순하게 보기 (coats, iris, lens and nerve plain)
    slit_dir3d: str = "down"        # 슬릿 스캔: "down", "up", "right", "left" or "all" (상하좌우)
    autofind3d: bool = True         # 3D 사진: the macula and disc found automatically are used (off: only marked ones)
    # the look this settings file was last used with: a newer one may adopt new defaults once
    ui_version: int = 0
    # Extra user-defined filename regexes tried before the profile patterns.
    custom_filename_patterns: list[str] = field(default_factory=list)
    last_patient: str = ""
    # Photo list under the views: 1 = one line; otherwise by eye — OD row on top, OS row under it
    # (newest first in each; an older 3 means by eye too)
    thumb_rows: int = 2
    # where the command toolbar is (dragged by the handle at its top): "left", "right", "top" — or "under"
    # (its right-click menu: in a row under the large photos, over the photo list)
    cmdbar_area: str = "left"
    # the look of the toolbar icons (보기 → 아이콘 모양; ui/icons.py STYLES): "group" 기능별 색 라인 (처음 설정) ·
    # "mono" · "color" · "dark" · "tint" · "flat" · "tile" (the colour tiles of before 0.13.5)
    icon_style: str = "group"
    # … and what is written on its photos (보기 → 사진 목록 표시): the exam date, the kind of photo
    # (컬러 · 몽타주 …). The eye is said once per row, at its left.
    thumb_date: bool = True
    thumb_kind: bool = False
    # Simple · Multi: 황반 · 디스크 — each photo's macula and optic disc enlarged under it, as on Detail
    simple_closeups: bool = False
    # 환자를 열면 (설정 → 일반): "odos" = Simple (처음 설정) — 최신 OD | OS 두 장을 나란히, 아래 사진
    # 목록은 날짜 책갈피로 · "grid" = 16장 보기 (VK-2 방식) — 사진 16장을 한 화면에, 골라서 [Multi]로
    # 고른 사진만 보기. Anything else (an older "overview") is 16장 보기.
    open_view: str = "odos"
    # 환자를 열면 사진 목록은 (설정 → 일반): "latest" = 가장 최근 검사일의 사진 (처음 설정) · "all" = 전체
    # (모든 검사일의 사진) — the 날짜 책갈피 the photo list opens on
    open_book: str = "latest"
    # The photos of the list grow toward the mouse like the icons of the Dock of a Mac (보기 → 사진
    # 목록에 마우스를 올리면 미리 보기)
    hover_preview: bool = True
    # The large photos (Simple · Multi · Detail): the loupe under the mouse while it is over the whole
    # photo, not zoomed yet — no button needed (보기 → 큰 사진에 마우스를 올리면 돋보기). Off at first
    # (0.13.2): as before 0.10.16, the loupe is there while the left button is held
    hover_loupe: bool = False
    # … how large: that many times its size in the list (보기 → 미리 보기 배율; peek.SCALES: 1.5 … 3)
    preview_scale: float = 2.0
    # G 필터 (설정 → 일반): what the button gives — "green" the green channel alone, "rnfl" 녹색 + RNFL 강화
    # (the ▾ of the button offers both anyway) — and how strong that RNFL 강화 is: 0.5 … 0.9
    green_filter: str = "green"
    rnfl_strength: float = 0.9
    # 녹내장 분석 → 3D 입체 (설정 → 일반): how one photo's shape is estimated when the window opens —
    # "hybrid" 하이브리드 (처음 설정) · "vessels" 혈관 꺾임 · "pallor" 밝기 (disc3d.METHODS); the tab can switch.
    # 디스크 C/D starts on the same one (its lines of equal depth and the cup put on one of them)
    disc3d_method: str = "hybrid"
    # … and the stereo depth of two photos (설정 → 일반): "parallax_vessels" 시차 + 혈관 꺾임 (처음 설정) ·
    # "parallax" 시차 (disc3d.STEREO_METHODS); the tab can switch
    disc3d_stereo_method: str = "parallax_vessels"
    # 카메라 각도 보정 (calibrate.py): the lens curve measured from the photos, {camera profile: radial_c}
    lens_curves: dict[str, float] = field(default_factory=dict)
    montage_fast: bool = False      # 몽타주 빠르게: the saved picture at most 2400 px instead of 4000
    # Automatic import (autosetup.py): an always-watched inbox folder and
    # detection of the capture software's folders at every start.
    inbox_dir: str = ""
    auto_detect: bool = True
    ignored_auto_folders: list[str] = field(default_factory=list)  # removed by the user: never re-added
    # Sharing with other computers (share.py, 설정 → 공유): "off" — this computer only; "server" — this
    # computer holds the database and the photos and answers the others; "client" — the library of
    # the server at ``server_url`` is shown in place of this computer's own
    share_mode: str = "off"
    share_port: int = 8765
    share_key: str = ""             # 접속 암호 (the server's; on a client: the password of its server)
    server_url: str = ""            # client: http://<server>:<port>
    # DICOM (dicomnet.py, 설정 → DICOM): this program's own AE title, the PACS photos are sent to
    # (C-STORE) and the worklist server the day's orders are asked from (MWL C-FIND)
    dicom_ae: str = "FUNDUSVIEWER"
    pacs_host: str = ""
    pacs_port: int = 104
    pacs_ae: str = ""
    mwl_host: str = ""
    mwl_port: int = 104
    mwl_ae: str = ""
    mwl_modality: str = "OP"        # the orders asked for, and the Modality of the photos sent ("" = every order)
    mwl_own_station: bool = False   # only the orders scheduled for this program's AE title
    dicom_charset: str = "ISO 2022 IR 149"   # Hangul names: "ISO 2022 IR 149" (KS X 1001) or "ISO_IR 192" (UTF-8)
    dicom_sop: str = "op"           # JPEG / PNG photos go as "op" Ophthalmic Photography or "sc" Secondary Capture
    dicom_jpeg: bool = True         # a JPEG photo is sent as it is (JPEG Baseline) when the PACS takes that
    dicom_institution: str = ""     # Institution Name written into the photos sent

    @property
    def library(self) -> Path:
        return Path(self.library_dir) if self.library_dir else default_library_dir()

    @property
    def inbox(self) -> Path:
        return Path(self.inbox_dir) if self.inbox_dir else default_inbox_dir()

    # -- persistence -------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or (config_dir() / "settings.json")
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        folders = [WatchFolder(**{k: v for k, v in f.items() if k in WatchFolder.__dataclass_fields__})
                   for f in raw.pop("watch_folders", [])]
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        return cls(watch_folders=folders, **known)

    def save(self, path: Path | None = None) -> None:
        path = path or (config_dir() / "settings.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
