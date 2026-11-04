"""안저판: 안저카메라가 사진을 저장하는 폴더를 감시해 새 사진을 찾는다.

대부분의 안저카메라(또는 카메라 전용 프로그램)는 촬영한 사진을 PC·공유 폴더에 JPG/TIFF 로 저장한다.
이 모듈은 그 폴더를 주기적으로 훑어 '새로 생겼고 다 써진' 이미지 파일만 알려 준다.

- FolderScanner      스레드·Qt 없는 순수 로직 (테스트 쉬움)
- FolderWatchWorker  QThread 로 옮겨 run() 을 돌리는 워커 — 새 파일 경로를 신호로 보낸다
- guess_eye()        파일 이름의 R/L·OD/OS·우안/좌안 으로 안구 추정

폴링 방식을 쓰는 이유: 네트워크 공유 폴더(NAS·다른 PC)에서는 OS 파일 변경 알림이 오지 않거나 늦는 경우가 많다.
"""
from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

log = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
IMPORTED_DIR = "_가져옴"                 # 가져온 원본을 옮겨 두는 폴더 (감시하지 않음)
_SKIP_DIRS = {IMPORTED_DIR, ".thumbs", "$RECYCLE.BIN", "System Volume Information"}

# 파일 이름 조각(구분자 _ - . 공백 괄호 등으로 나눔) → 안구
_EYE_TOKENS = {
    "OD": "OD", "R": "OD", "RE": "OD", "RT": "OD", "RIGHT": "OD", "우": "OD", "우안": "OD",
    "OS": "OS", "L": "OS", "LE": "OS", "LT": "OS", "LEFT": "OS", "좌": "OS", "좌안": "OS",
    "OU": "OU", "양안": "OU",
}
_SPLIT = re.compile(r"[\s_\-.,+()\[\]{}]+")
_NUMBERED = re.compile(r"(OD|OS|OU|RIGHT|LEFT)\d{1,3}")     # 예: OD1, LEFT02


def guess_eye(name: str) -> str | None:
    """파일 이름으로 안구를 추정. 한쪽만 확실히 보이면 'OD'/'OS'/'OU', 아니면 None.

    >>> guess_eye("20261104_103012_R.jpg"), guess_eye("홍길동_좌안.JPG"), guess_eye("IMG_0001.jpg")
    ('OD', 'OS', None)
    """
    stem = Path(name).stem
    found = set()
    for tok in _SPLIT.split(stem):
        t = tok.upper()
        if not t:
            continue
        if t in _EYE_TOKENS:
            found.add(_EYE_TOKENS[t])
        else:
            m = _NUMBERED.fullmatch(t)
            if m:
                found.add(_EYE_TOKENS[m.group(1)])
    return found.pop() if len(found) == 1 else None


class FolderUnavailable(OSError):
    """감시 폴더에 접근할 수 없음 (없음·권한·네트워크 끊김)."""


class FolderScanner:
    """폴더를 훑어 새 이미지 파일을 찾는다.

    - prime(): 시작할 때 이미 있던 파일은 '본 것'으로 기억 (예전 사진을 다시 가져오지 않게)
    - poll():  새로 생긴(또는 같은 이름으로 덮어쓴) 파일 중, 크기·수정 시각이 settle 번 연속 같은
               '다 써진' 파일만 돌려준다. 카메라가 아직 쓰는 중인 반쪽 파일을 가져오지 않기 위함.
    한 번 본 파일은 사라져도 잊지 않는다 — 네트워크가 잠깐 끊겼다 돌아와도 예전 사진을 다시 가져오지 않게.
    """

    def __init__(self, folder, recursive: bool = True, max_depth: int = 4, settle: int = 2):
        self.folder = Path(folder)
        self.recursive = recursive
        self.max_depth = max_depth
        self.settle = max(1, settle)
        self._seen: dict[str, tuple[int, int]] = {}
        self._pending: dict[str, tuple[tuple[int, int], int]] = {}

    def _walk(self) -> dict[str, tuple[int, int]]:
        if not self.folder.is_dir():
            raise FolderUnavailable(f"폴더를 찾을 수 없습니다: {self.folder}")
        out: dict[str, tuple[int, int]] = {}
        stack = [(self.folder, 0)]
        first = True
        while stack:
            d, depth = stack.pop()
            try:
                it = os.scandir(d)
            except OSError as e:
                if first:
                    raise FolderUnavailable(f"폴더를 열 수 없습니다: {d} ({e})") from e
                continue                                    # 권한 없는 하위 폴더는 건너뜀
            first = False
            with it:
                for ent in it:
                    name = ent.name
                    if name.startswith((".", "~")):
                        continue                            # 숨김·임시 파일
                    try:
                        if ent.is_dir(follow_symlinks=False):
                            if self.recursive and depth < self.max_depth and name not in _SKIP_DIRS:
                                stack.append((Path(ent.path), depth + 1))
                            continue
                        if Path(name).suffix.lower() not in IMAGE_EXTS:
                            continue
                        st = ent.stat()
                    except OSError:
                        continue                            # 그 사이 지워진 파일 등
                    out[ent.path] = (st.st_size, st.st_mtime_ns)
        return out

    def prime(self) -> int:
        self._seen = dict(self._walk())
        self._pending.clear()
        return len(self._seen)

    def poll(self) -> list[Path]:
        now = self._walk()
        ready: list[tuple[int, Path]] = []
        for path, sig in now.items():
            if self._seen.get(path) == sig:
                continue
            prev = self._pending.get(path)
            count = prev[1] + 1 if prev and prev[0] == sig else 1
            if sig[0] > 0 and count >= self.settle:
                self._seen[path] = sig
                self._pending.pop(path, None)
                ready.append((sig[1], Path(path)))
            else:
                self._pending[path] = (sig, count)
        for path in [p for p in self._pending if p not in now]:
            del self._pending[path]
        ready.sort(key=lambda x: (x[0], str(x[1])))          # 먼저 찍은 사진부터
        return [p for _, p in ready]


class FolderWatchWorker(QObject):
    """QThread 로 moveToThread 한 뒤 run() 을 실행. 위젯은 건드리지 않고 문자열 신호만 보낸다."""

    found = Signal(str)            # 새 사진 경로
    status = Signal(str, bool)     # 상태 문구, 정상 여부
    stopped = Signal()

    def __init__(self, folder: str, recursive: bool = True, interval_ms: int = 1500):
        super().__init__()
        self.folder = folder
        self.recursive = recursive
        self.interval = max(0.3, interval_ms / 1000.0)
        self._running = False

    @Slot()
    def run(self) -> None:
        self._running = True
        scanner = FolderScanner(self.folder, recursive=self.recursive)
        primed = False
        ok_state = None
        while self._running:
            try:
                if not primed:
                    n = scanner.prime()
                    primed = True
                    log.info("watch %s (기존 사진 %d장은 건너뜀)", self.folder, n)
                else:
                    for p in scanner.poll():
                        self.found.emit(str(p))
                if ok_state is not True:
                    ok_state = True
                    self.status.emit(f"감시 중 · {self.folder}", True)
            except FolderUnavailable as e:
                if ok_state is not False:
                    ok_state = False
                    log.warning("watch folder unavailable: %s", e)
                    self.status.emit(f"폴더에 접근할 수 없습니다 · {self.folder}", False)
            except Exception:  # noqa: BLE001
                log.exception("folder watch poll failed")
            t_end = time.monotonic() + self.interval
            while self._running and time.monotonic() < t_end:
                time.sleep(0.05)
        self.stopped.emit()

    @Slot()
    def stop(self) -> None:
        # run() 루프가 스레드 이벤트 루프를 점유하므로 큐 연결 대신 플래그를 직접 내린다 (CameraWorker 와 같음)
        self._running = False
