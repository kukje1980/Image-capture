"""폴더 가져오기 (웹 서버판) — 안저 카메라가 사진을 넣는 서버 PC 폴더를 지켜보다가 파일 이름의
아이디·이름·날짜·좌우로 환자 DB 에 등록하고 원본은 지운다. 규칙은 데스크탑(app/services/folder_import.py)과 같다.

  · 카메라가 아직 쓰는 파일은 건너뜀 (두 번 연속 같은 크기·시각, 1.5초 지난 파일만)
  · 아이디(차트번호·환자ID)로 환자를 찾고 없으면 새로 등록
  · 이름이 다르거나(같은 글자 종류끼리) 파일 이름을 못 읽으면 지우지 않고 '_확인필요' 폴더로
  · 원본 그대로 복사 → 크기 확인 → 원본 삭제 (끄거나 실패하면 '_가져옴' 폴더로)
  · 브라우저에서 못 여는 TIFF·BMP 는 PNG(무손실)로 바꿔 저장
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import shutil
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path

from app import config
from app.fundus_filename import captured_at, parse_filename

log = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
WEB_EXTS = {".jpg", ".jpeg", ".png", ".webp"}           # 브라우저가 바로 보여 주는 형식
REVIEW_DIR = "_확인필요"
DONE_DIR = "_가져옴"
STABLE_SEC = 1.5


@dataclass
class ImportSettings:
    enabled: bool = False
    dir: str = ""
    template: str = ""                 # 비우면 자동 인식 · 예: {id}_{name}_{date}_{eye}
    delete: bool = True                # 등록한 원본 지우기 (끄면 '_가져옴' 으로)
    recursive: bool = True
    switch_patient: bool = True        # 화면이 가져온 환자로 바뀜 (브라우저가 처리)
    interval_sec: int = 3


def load_settings() -> ImportSettings:
    s = ImportSettings()
    try:
        data = json.loads(Path(config.IMPORT_SETTINGS_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return s
    for f in fields(ImportSettings):
        v = data.get(f.name)
        if v is not None and isinstance(v, type(getattr(s, f.name))):
            setattr(s, f.name, v)
    return s


def save_settings(s: ImportSettings) -> None:
    p = Path(config.IMPORT_SETTINGS_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(s), ensure_ascii=False, indent=2), encoding="utf-8")


def photo_datetime(path: Path) -> datetime:
    try:
        from PIL import Image
        with Image.open(path) as im:
            exif = im.getexif()
            raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)
        if raw:
            return datetime.strptime(str(raw).strip()[:19], "%Y:%m:%d %H:%M:%S")
    except Exception:  # noqa: BLE001
        pass
    return datetime.fromtimestamp(path.stat().st_mtime)


def _same_script_conflict(a, b) -> bool:
    if not a or not b:
        return False
    na, nb = re.sub(r"[\s_^]+", "", a).upper(), re.sub(r"[\s_^]+", "", b).upper()
    hangul = re.compile(r"[가-힣]")
    if bool(hangul.search(na)) != bool(hangul.search(nb)):
        return False
    return na != nb


class WebImporter:
    def __init__(self, db):
        self.db = db
        self.settings = load_settings()
        self._seen: dict[str, tuple[int, float]] = {}
        self._skip: set[str] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.recent: deque = deque(maxlen=30)
        self.seq = 0                       # 새로 가져올 때마다 +1 (화면이 새로 고칠지 판단)
        self.total_ok = 0
        self.total_review = 0
        self.last_error = ""
        self.last_scan = ""

    # ---- 상태 ----
    def status(self) -> dict:
        s = self.settings
        folder = Path(s.dir) if s.dir else None
        return {
            "available": config.IMPORT_AVAILABLE,
            "settings": asdict(s),
            "folder_ok": bool(folder and folder.is_dir()),
            "running": bool(s.enabled and folder and folder.is_dir() and config.IMPORT_AVAILABLE),
            "seq": self.seq, "total_ok": self.total_ok, "total_review": self.total_review,
            "last_error": self.last_error, "last_scan": self.last_scan,
            "recent": list(self.recent),
        }

    def update(self, new: ImportSettings) -> None:
        self.settings = new
        save_settings(new)
        self._seen.clear()
        self._skip.clear()

    # ---- 백그라운드 ----
    def start(self) -> None:
        if not config.IMPORT_AVAILABLE or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="folder-import", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.wait(max(2, int(self.settings.interval_sec or 3))):
            if self.settings.enabled:
                try:
                    self.scan()
                except Exception:  # noqa: BLE001
                    log.exception("folder import scan failed")

    # ---- 가져오기 ----
    def scan(self, force: bool = False) -> list[dict]:
        s = self.settings
        folder = Path(s.dir) if s.dir else None
        if folder is None or not folder.is_dir():
            self.last_error = "가져올 폴더가 없습니다" if folder else "가져올 폴더를 정하지 않았습니다"
            return []
        if not self._lock.acquire(blocking=False):
            return []
        try:
            self.last_error = ""
            self.last_scan = config.now().strftime("%Y-%m-%d %H:%M:%S")
            now = time.time()
            ready, alive = [], set()
            for f in self._files(folder):
                key = str(f)
                alive.add(key)
                if key in self._skip:
                    continue
                try:
                    st = f.stat()
                except OSError:
                    continue
                sig = (st.st_size, st.st_mtime)
                if st.st_size > 0 and now - st.st_mtime >= (1.0 if force else STABLE_SEC) and (
                        force or self._seen.get(key) == sig):
                    ready.append(f)
                else:
                    self._seen[key] = sig
            self._seen = {k: v for k, v in self._seen.items() if k in alive}
            ready.sort(key=lambda p: p.name)
            out = [self.import_file(f, folder) for f in ready]
            for f in ready:
                self._seen.pop(str(f), None)
            return out
        finally:
            self._lock.release()

    def _files(self, folder: Path):
        it = folder.rglob("*") if self.settings.recursive else folder.iterdir()
        for f in it:
            try:
                rel = f.relative_to(folder)
            except ValueError:
                continue
            if any(part.startswith(("_", ".")) for part in rel.parts[:-1]):
                continue
            if f.name.startswith((".", "~$")) or f.suffix.lower() not in IMAGE_EXTS:
                continue
            if f.is_file():
                yield f

    def import_file(self, path: Path, folder: Path) -> dict:
        parsed = parse_filename(path.name, self.settings.template)
        if not parsed.ok:
            return self._review(path, folder, parsed.error or "파일 이름을 읽지 못함")
        patient = self.db.find_patient_by_code(parsed.id)
        created = False
        if patient is not None and _same_script_conflict(patient.get("name"), parsed.name):
            return self._review(path, folder, f"아이디 {parsed.id} 는 '{patient['name']}' 인데 파일 이름은 '{parsed.name}'")
        if patient is None:
            pid = self.db.create_patient({"chart_no": parsed.id, "name": parsed.name or parsed.id,
                                          "memo": "폴더 가져오기로 자동 등록"})
            patient, created = self.db.get_patient(pid), True
        when = captured_at(parsed, photo_datetime(path))
        try:
            cap = self._store(path, patient, parsed.eye, when)
        except Exception as e:  # noqa: BLE001
            log.exception("import failed: %s", path)
            self.last_error = f"{path.name}: {e}"
            return self._record(path, False, f"저장 실패: {e}", patient)
        self._dispose(path, folder)
        self.total_ok += 1
        self.seq += 1
        return self._record(path, True, f"{patient['name']}({patient['chart_no']}) · {parsed.eye} · {when}",
                            patient, cap, created)

    def _store(self, src: Path, patient: dict, eye: str, when: str) -> dict:
        from app.routers.captures import _target_paths
        ts = datetime.strptime(when, "%Y-%m-%d %H:%M:%S")
        ext = src.suffix.lower()
        convert = ext not in WEB_EXTS
        out_ext = "png" if convert else ext.lstrip(".")
        rel_path, abs_path = _target_paths(patient, "photo", ts, out_ext)
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        if abs_path.exists():
            abs_path = abs_path.with_name(f"{abs_path.stem}_{secrets.token_hex(3)}{abs_path.suffix}")
            rel_path = rel_path.with_name(abs_path.name)
        try:
            if convert:                                 # TIFF·BMP → PNG (무손실)
                from PIL import Image
                with Image.open(src) as im:
                    im.save(abs_path, "PNG")
            else:
                shutil.copyfile(src, abs_path)
                if abs_path.stat().st_size != src.stat().st_size:
                    raise OSError("복사한 크기가 원본과 다릅니다")
            url = "/media/" + str(rel_path).replace("\\", "/")
            cid = self.db.create_capture({
                "patient_id": patient["id"], "media_type": "photo",
                "file_path": str(rel_path).replace("\\", "/"), "url": url,
                "captured_at": when, "eye": eye if eye in ("OD", "OS", "OU", "NA") else "NA",
                "duration_ms": None, "note": None,
            })
        except BaseException:
            abs_path.unlink(missing_ok=True)
            raise
        return self.db.get_capture(cid)

    def _record(self, path: Path, ok: bool, message: str, patient=None, cap=None, created=False) -> dict:
        item = {
            "time": config.now().strftime("%H:%M:%S"), "file": path.name, "ok": ok, "message": message,
            "patient_id": patient["id"] if patient else None,
            "patient_name": patient["name"] if patient else None,
            "chart_no": patient["chart_no"] if patient else None,
            "capture_id": cap["id"] if cap else None, "new_patient": created,
        }
        self.recent.appendleft(item)
        return item

    def _review(self, path: Path, folder: Path, why: str) -> dict:
        self.total_review += 1
        moved = self._move(path, folder, REVIEW_DIR)
        return self._record(path, False, f"{why} → '{REVIEW_DIR}' 폴더로 옮김" if moved else why)

    def _dispose(self, path: Path, folder: Path) -> None:
        if self.settings.delete:
            try:
                path.unlink()
                return
            except OSError:
                log.warning("could not delete imported source: %s", path, exc_info=True)
        if not self._move(path, folder, DONE_DIR):
            self._skip.add(str(path))

    def _move(self, path: Path, folder: Path, sub: str) -> bool:
        dest_dir = folder / sub
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / path.name
            n = 2
            while dest.exists():
                dest = dest_dir / f"{path.stem} ({n}){path.suffix}"
                n += 1
            shutil.move(str(path), str(dest))
            return True
        except OSError:
            log.warning("could not move %s to %s", path, dest_dir, exc_info=True)
            self._skip.add(str(path))
            return False
