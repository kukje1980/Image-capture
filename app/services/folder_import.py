"""가져오기 폴더: 카메라·다른 장비가 지정한 폴더에 넣은 사진을 지금 환자에게 가져온다.

- 폴더 바로 아래의 사진(JPG·PNG·BMP·TIFF)만 본다. 하위 폴더는 보지 않는다.
- 가져온 원본은 그 폴더 안의 '가져옴' 폴더로 옮긴다 (같은 사진을 두 번 가져오지 않게, 원본은 그대로 보관).
- 크기·수정 시각이 한 번 이상 그대로이고 파일 끝까지 써진 것을 확인한 뒤에 가져온다 (복사 중인 반쪽 파일 방지).
- 감시를 시작할 때 이미 있던 사진과 환자를 고르지 않은 동안 들어온 사진은 바로 가져오지 않는다
  — 메인 창이 "지금 환자에게 가져올까요?" 를 물은 뒤 import_held() / skip_held() 를 부른다 (다른 환자 기록에 섞이지 않게).
- Qt 를 쓰지 않는다: 메인 창의 타이머가 poll() 을 주기적으로(1초) 부른다.
"""
from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app import paths

log = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
DONE_DIR = "가져옴"
LONG_SETTLE = 3     # 끝 표시가 없는 파일도 이만큼(약 3초) 그대로면 다 써진 것으로 본다 (끝에 덧붙인 데이터가 있는 사진 등)
GIVE_UP = 30        # 다른 프로그램이 잡고 있어 이만큼(약 30초) 열지 못하면 포기하고 알린다


@dataclass
class _Entry:
    sig: tuple            # (크기, 수정 시각 ns)
    held: bool            # True = 바로 가져오지 않고 확인을 받을 사진
    stable: int = 0       # 바뀌지 않고 지나간 살피기 횟수
    tries: int = 0        # 열지 못한 횟수


@dataclass
class PollResult:
    imported: list = field(default_factory=list)   # 가져온 Capture
    failed: list = field(default_factory=list)     # (파일 이름, 이유) — 이번 실행에서는 다시 시도하지 않음
    warnings: list = field(default_factory=list)   # 가져왔지만 원본을 옮기지 못함 등
    held: int = 0          # 확인을 기다리는 사진 수 (전부터 있던 사진 · 환자 없이 들어온 사진)
    waiting: int = 0       # 환자를 고르지 않아 기다리는 사진 수
    error: Optional[str] = None   # 폴더를 열 수 없음


def looks_complete(data: bytes, ext: str) -> bool:
    """파일 끝까지 써졌는지 형식별 끝 표시로 확인 (JPEG EOI · PNG IEND · BMP 헤더 크기). 그 밖의 형식은 True."""
    ext = ext.lower()
    if not data:
        return False
    if ext in (".jpg", ".jpeg"):
        return data[:2] == b"\xff\xd8" and b"\xff\xd9" in data[-4096:]
    if ext == ".png":
        return data[:8] == b"\x89PNG\r\n\x1a\n" and b"IEND" in data[-32:]
    if ext == ".bmp":
        return data[:2] == b"BM" and len(data) >= int.from_bytes(data[2:6], "little")
    return True


def _norm(p) -> str:
    try:
        return os.path.normcase(str(Path(p).expanduser().resolve()))
    except (OSError, RuntimeError):
        return os.path.normcase(os.path.abspath(str(p)))


def check_import_folder(folder: str, media_root: str = "", export_root: str = "") -> Optional[str]:
    """설정 창에서 고른 가져오기 폴더를 쓸 수 있는지. 문제가 있으면 안내 문구, 없으면(또는 끔) None."""
    folder = (folder or "").strip()
    if not folder:
        return None
    if not Path(folder).expanduser().is_dir():
        return f"가져오기 폴더를 찾을 수 없습니다:\n{folder}"
    me = _norm(folder)
    for label, root in (("기본 저장 폴더", media_root), ("저장 폴더(export)", export_root)):
        if not root:
            continue
        r = _norm(root)
        if me == r or me.startswith(r.rstrip(os.sep) + os.sep):
            return (f"가져오기 폴더는 {label}와 같거나 그 안에 둘 수 없습니다.\n"
                    "(저장한 사진을 다시 가져오게 됩니다) 다른 폴더를 고르세요.")
    return None


class FolderImporter:
    def __init__(self, service, folder):
        self.service = service
        self.folder = Path(folder).expanduser()
        self._entries: dict[str, _Entry] = {}
        self._skip: dict[str, tuple] = {}     # 이번 실행에서 다시 보지 않을 파일 → 그때의 sig (바뀌면 새 사진으로 봄)
        self._first = True

    # ---- 공개 API ----
    def poll(self, patient, eye: str = "NA") -> PollResult:
        """폴더를 한 번 살핀다. 환자가 있으면 새로 들어온 사진을 그 환자에게 가져온다."""
        res = PollResult()
        try:
            ready = self._scan(have_patient=patient is not None)
        except OSError as e:
            res.error = f"가져오기 폴더를 열 수 없습니다: {self.folder} ({e.strerror or e})"
            return res
        if patient is None:
            res.waiting = len(ready)
            return res
        for name in ready:
            if self._entries[name].held:
                res.held += 1
            else:
                self._import_one(name, patient, eye, res)
        return res

    def import_held(self, patient, eye: str = "NA") -> PollResult:
        """확인을 받은 사진(전부터 있던 사진 등)을 가져온다."""
        res = PollResult()
        for name in self._ordered(n for n, e in self._entries.items() if e.held and e.stable > 0 and e.sig[0] > 0):
            self._import_one(name, patient, eye, res)
        return res

    def skip_held(self) -> int:
        """확인을 기다리던 사진을 가져오지 않고 폴더에 그대로 둔다 (이번 실행 동안 다시 묻지 않음)."""
        names = [n for n, e in self._entries.items() if e.held]
        for n in names:
            self._skip[n] = self._entries.pop(n).sig
        return len(names)

    # ---- 내부 ----
    def _ordered(self, names) -> list[str]:
        """들어온 순서(수정 시각) → 이름 순 (카메라 파일 번호 순서대로)."""
        return sorted(names, key=lambda n: (self._entries[n].sig[1], n))

    def _scan(self, have_patient: bool) -> list[str]:
        seen, ready = set(), []
        with os.scandir(self.folder) as it:
            for de in it:
                name = de.name
                if name.startswith((".", "~")) or Path(name).suffix.lower() not in IMAGE_EXTS:
                    continue
                try:
                    if not de.is_file():
                        continue
                    st = os.stat(de.path)      # 폴더 목록의 크기는 쓰는 중에 늦게 바뀔 수 있어(윈도우) 파일에서 직접 읽는다
                except OSError:
                    continue
                sig = (st.st_size, st.st_mtime_ns)
                seen.add(name)
                if name in self._skip:
                    if self._skip[name] == sig:
                        continue
                    del self._skip[name]        # 같은 이름의 새 사진 (카메라 번호가 처음으로 돌아감 등)
                ent = self._entries.get(name)
                if ent is None:
                    self._entries[name] = _Entry(sig, held=self._first or not have_patient)
                elif ent.sig != sig:
                    ent.sig, ent.stable = sig, 0          # 아직 쓰는 중
                else:
                    ent.stable += 1
                    if sig[0] > 0:
                        ready.append(name)
        for gone in set(self._entries) - seen:          # 다른 프로그램이 옮기거나 지운 사진
            del self._entries[gone]
        for gone in set(self._skip) - seen:
            del self._skip[gone]
        self._first = False
        return self._ordered(ready)

    def _import_one(self, name: str, patient, eye: str, res: PollResult) -> None:
        ent = self._entries.get(name)
        if ent is None:
            return
        src = self.folder / name
        try:
            data = src.read_bytes()
        except OSError:                                 # 다른 프로그램이 아직 잡고 있음 → 다음에 다시
            ent.tries += 1
            if ent.tries >= GIVE_UP:
                self._give_up(name, "파일을 열 수 없습니다 (다른 프로그램이 사용 중)", res)
            return
        if len(data) != ent.sig[0]:                     # 읽는 사이에 바뀜 → 다음에 다시
            ent.stable = 0
            return
        settled = ent.stable >= LONG_SETTLE
        if not looks_complete(data, src.suffix) and not settled:
            return                                      # 끝까지 안 써졌을 수 있음 → 조금 더 기다린다
        try:
            cap = self.service.import_photo(data, src.suffix, patient, eye=eye, note=f"가져옴 · {name}")
        except ValueError as e:                         # 읽을 수 없는 사진 — 쓰는 중일 수 있어 잠시 더 기다린 뒤 포기
            if settled:
                self._give_up(name, str(e), res)
            return
        except Exception as e:  # noqa: BLE001
            log.exception("import failed: %s", src)
            self._give_up(name, f"저장 실패: {e}", res)
            return
        res.imported.append(cap)
        del self._entries[name]
        if not self._move_done(src):
            self._skip[name] = ent.sig
            res.warnings.append(f"'{name}' 원본을 '{DONE_DIR}' 폴더로 옮기지 못했습니다 (폴더 쓰기 권한을 확인하세요)")

    def _give_up(self, name: str, why: str, res: PollResult) -> None:
        ent = self._entries.pop(name, None)
        if ent is not None:
            self._skip[name] = ent.sig
        log.warning("import skipped %s: %s", name, why)
        res.failed.append((name, why))

    def _move_done(self, src: Path) -> bool:
        try:
            done = paths.ensure_dir(self.folder / DONE_DIR)
            shutil.move(str(src), str(paths.unique_path(done / src.name)))
            return not src.exists()                     # 정말 옮겨졌는지 (남아 있으면 다시 가져오지 않게)
        except OSError:
            log.warning("could not move imported original %s", src, exc_info=True)
            return False
