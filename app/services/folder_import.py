"""폴더 가져오기: 안저 카메라가 사진을 넣는 폴더를 지켜보다가, 파일 이름에서 아이디·이름·날짜·좌우를
읽어 환자 DB 에 등록하고 원본 사진은 지운다.

흐름 (scan 한 번)
  1) 폴더(하위 폴더 포함 가능)의 사진 파일을 찾는다 — '_' 나 '.' 로 시작하는 폴더는 건너뜀
  2) 카메라가 아직 쓰는 중인 파일은 건너뛴다 (두 번 연속 크기·시각이 같고 1.5초 지난 파일만)
  3) 파일 이름 해석 (app/services/fundus_filename.py) — 못 읽으면 '_확인필요' 폴더로 옮김
  4) 아이디(차트번호·환자ID)로 환자를 찾고, 없으면 새로 만든다.
     이미 있는 환자인데 이름이 다르면(같은 글자 종류끼리 비교) 잘못 들어갈 수 있으니 '_확인필요' 로
  5) 원본 그대로 복사해 등록 (CaptureService.import_photo) → 복사 크기 확인 → 원본 삭제
     (삭제를 끄거나 삭제가 안 되면 '_가져옴' 폴더로 옮겨 다시 가져오지 않게)
"""
from __future__ import annotations

import logging
import re
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.models.capture import Capture
from app.models.patient import Patient
from app.services.fundus_filename import ParsedName, captured_at, parse_filename

log = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
REVIEW_DIR = "_확인필요"          # 파일 이름을 읽지 못했거나 환자가 헷갈리는 사진
DONE_DIR = "_가져옴"              # 등록했지만 지우지 않은(지우지 못한) 원본
STABLE_SEC = 1.5


@dataclass
class ImportItem:
    source: str
    ok: bool
    parsed: ParsedName | None = None
    capture: Capture | None = None
    patient: Patient | None = None
    new_patient: bool = False
    message: str = ""


def photo_datetime(path: Path) -> datetime:
    """사진 정보(EXIF 촬영 시각)가 있으면 그것, 없으면 파일 수정 시각."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            exif = im.getexif()
            raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)   # DateTimeOriginal · DateTime
        if raw:
            return datetime.strptime(str(raw).strip()[:19], "%Y:%m:%d %H:%M:%S")
    except Exception:  # noqa: BLE001
        pass
    return datetime.fromtimestamp(path.stat().st_mtime)


def _same_script_conflict(a: str | None, b: str | None) -> bool:
    """두 이름이 같은 글자 종류(한글끼리·영문끼리)인데 다르면 True."""
    if not a or not b:
        return False
    na, nb = re.sub(r"[\s_^]+", "", a).upper(), re.sub(r"[\s_^]+", "", b).upper()
    hangul = re.compile(r"[가-힣]")
    if bool(hangul.search(na)) != bool(hangul.search(nb)):
        return False                                        # 한글 ↔ 영문은 비교할 수 없음
    return na != nb


class FolderImporter:
    def __init__(self, db, service, config):
        self.db = db
        self.service = service
        self.config = config
        self._seen: dict[str, tuple[int, float]] = {}
        self._skip: set[str] = set()                        # 지우지도 옮기지도 못한 파일
        self._lock = threading.Lock()
        self.total_ok = 0
        self.total_review = 0
        self.last_error = ""

    # ---- 공개 API ----
    def folder(self) -> Path | None:
        d = (self.config.import_dir or "").strip()
        return Path(d) if d else None

    def scan(self, force: bool = False) -> list[ImportItem]:
        """폴더를 한 번 살펴 준비된 사진을 가져온다. force=True 면 1초 지난 파일은 바로."""
        folder = self.folder()
        if folder is None or not folder.is_dir():
            self.last_error = "가져올 폴더가 없습니다" if folder else "가져올 폴더를 정하지 않았습니다"
            return []
        if not self._lock.acquire(blocking=False):          # 이전 검사가 아직 진행 중
            return []
        try:
            self.last_error = ""
            now = time.time()
            ready: list[Path] = []
            alive = set()
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
                age = now - st.st_mtime
                if st.st_size > 0 and age >= (1.0 if force else STABLE_SEC) and (
                        force or self._seen.get(key) == sig):
                    ready.append(f)
                else:
                    self._seen[key] = sig
            self._seen = {k: v for k, v in self._seen.items() if k in alive}
            ready.sort(key=lambda p: p.name)
            out = [self.import_file(f) for f in ready]
            for f in ready:
                self._seen.pop(str(f), None)
            return out
        finally:
            self._lock.release()

    def import_file(self, path: Path) -> ImportItem:
        path = Path(path)
        parsed = parse_filename(path.name, self.config.import_template)
        if not parsed.ok:
            return self._review(path, parsed, parsed.error or "파일 이름을 읽지 못함")
        try:
            patient, created = self._patient_for(parsed)
        except _NameConflict as e:
            return self._review(path, parsed, str(e))
        when = captured_at(parsed, photo_datetime(path))
        try:
            cap = self.service.import_photo(path, patient, eye=parsed.eye, captured_at=when)
        except Exception as e:  # noqa: BLE001
            log.exception("import failed: %s", path)
            self.last_error = f"{path.name}: {e}"
            return ImportItem(str(path), False, parsed, patient=patient, message=f"저장 실패: {e}")
        self._dispose(path)
        self.total_ok += 1
        return ImportItem(str(path), True, parsed, cap, patient, created,
                          f"{patient.name}({patient.chart_no}) · {parsed.eye} · {when}")

    # ---- 내부 ----
    def _files(self, folder: Path):
        it = folder.rglob("*") if self.config.import_recursive else folder.iterdir()
        for f in it:
            try:
                rel = f.relative_to(folder)
            except ValueError:
                continue
            if any(part.startswith(("_", ".")) for part in rel.parts[:-1]):
                continue                                    # _확인필요 · _가져옴 · .thumbs 등
            name = f.name
            if name.startswith((".", "~$")) or f.suffix.lower() not in IMAGE_EXTS:
                continue
            if f.is_file():
                yield f

    def _patient_for(self, parsed: ParsedName) -> tuple[Patient, bool]:
        p = self.db.patients.find_by_code(parsed.id)
        if p is not None:
            if _same_script_conflict(p.name, parsed.name):
                raise _NameConflict(f"아이디 {parsed.id} 는 '{p.name}' 인데 파일 이름은 '{parsed.name}'")
            return p, False
        p = Patient(chart_no=parsed.id, name=parsed.name or parsed.id,
                    memo="폴더 가져오기로 자동 등록")
        p.id = self.db.patients.insert(p)
        return p, True

    def _review(self, path: Path, parsed: ParsedName, why: str) -> ImportItem:
        self.total_review += 1
        moved = self._move(path, REVIEW_DIR)
        log.warning("import needs review: %s (%s)", path, why)
        return ImportItem(str(path), False, parsed,
                          message=f"{why} → '{REVIEW_DIR}' 폴더로 옮김" if moved else why)

    def _dispose(self, path: Path) -> None:
        """등록한 원본: 지우기(기본) — 끄거나 지우지 못하면 '_가져옴' 으로."""
        if self.config.import_delete:
            try:
                path.unlink()
                return
            except OSError:
                log.warning("could not delete imported source: %s", path, exc_info=True)
        if not self._move(path, DONE_DIR):
            self._skip.add(str(path))

    def _move(self, path: Path, sub: str) -> bool:
        folder = self.folder() or path.parent
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


class _NameConflict(Exception):
    pass
