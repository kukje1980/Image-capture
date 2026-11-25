"""질환 샘플: sample photos of retinal diseases, kept by disease, to set beside a patient's photo
(ui/sample_compare.py, the 질환 샘플 menu).

They live in the library folder, ``질환 샘플`` — one folder per disease, the photos in it — with an
``index.json`` that keeps the order of the diseases and a note (설명) for each photo. The folder can be
copied to another computer as it is; photos put into a disease's folder by hand show up too.

A photo is copied in under a name of its own (the disease and a number), never under the name it had:
a patient's photo taken as a sample carries no name, ID or date of that patient with it.

The program brings sample photos of its own (``sample_photos/``: openly licensed photos from Wikimedia
Commons, each with its author, licence and source in ``sample_photos/samples.json``). ``install_builtin``
copies those not yet given to this library in — once: a sample the user deletes is not brought back,
unless asked (``restore_builtin``). Each keeps its credit (``credit``), shown under it.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import numpy as np

FOLDER = "질환 샘플"
INDEX = "index.json"
BUILTIN_DIR = Path(__file__).with_name("sample_photos")     # the program's own samples
BUILTIN_INDEX = "samples.json"
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
# the diseases a new sample library starts with (they can be renamed, removed and added to)
DEFAULT_DISEASES = (
    "정상 안저",
    "당뇨망막병증",
    "나이관련 황반변성",
    "녹내장 (시신경 유두)",
    "망막정맥폐쇄",
    "망막동맥폐쇄",
    "고혈압망막병증",
    "망막박리",
    "황반원공",
    "황반전막",
    "중심장액맥락망막병증",
    "병적 근시",
    "시신경 유두부종",
    "망막색소변성",
)
_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def folder_name(disease: str) -> str:
    """A disease's folder: its name, without what a file system does not take."""
    name = _BAD.sub("_", disease).strip().rstrip(".")
    return name or "_"


# A disease's name is its folder's and the start of its photos' file names ("이름_001.jpg"): a file
# name holds 255 bytes, and a Korean letter takes three.
NAME_MAX = 60


def _check_name(name: str) -> None:
    if not name:
        raise ValueError("질환 이름을 적으세요")
    if len(name) > NAME_MAX:
        raise ValueError(f"질환 이름이 너무 깁니다 ({NAME_MAX}자까지)")


class SampleLibrary:
    def __init__(self, library: Path | str):
        self.root = Path(library) / FOLDER
        self._index: dict | None = None

    # -- the index ------------------------------------------------------------------------------
    def _load(self) -> dict:
        if self._index is None:
            idx = {}
            try:
                idx = json.loads((self.root / INDEX).read_text("utf-8"))
            except (OSError, ValueError):
                pass
            if not isinstance(idx, dict):         # (an index that is JSON, but not ours)
                idx = {}
            if isinstance(idx.get("diseases"), list):
                idx["diseases"] = [d for d in idx["diseases"] if isinstance(d, str) and d.strip()]
            if not isinstance(idx.get("diseases"), list):
                # a new library: the usual diseases (and the folders put there by hand)
                idx["diseases"] = list(DEFAULT_DISEASES)
            for key in ("notes", "credits", "builtin"):
                if not isinstance(idx.get(key), dict):
                    idx[key] = {}
            self._index = idx
            for d in self._folders_by_hand():
                if d not in idx["diseases"]:
                    idx["diseases"].append(d)
        return self._index

    def _folders_by_hand(self) -> list[str]:
        if not self.root.is_dir():
            return []
        known = {folder_name(d) for d in (self._index or {}).get("diseases", [])}
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and p.name not in known)

    def _save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / (INDEX + ".tmp")
        tmp.write_text(json.dumps(self._load(), ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(self.root / INDEX)

    # -- diseases -------------------------------------------------------------------------------
    def diseases(self) -> list[str]:
        return list(self._load()["diseases"])

    def add_disease(self, name: str) -> str:
        name = " ".join(name.split())
        _check_name(name)
        if any(folder_name(d) == folder_name(name) for d in self.diseases()):
            raise ValueError(f"'{name}'은(는) 이미 있습니다")
        # the folder first: a name the disk refuses (OSError) must not stay in the list
        (self.root / folder_name(name)).mkdir(parents=True, exist_ok=True)
        self._load()["diseases"].append(name)
        self._save()
        return name

    def rename_disease(self, old: str, new: str) -> str:
        new = " ".join(new.split())
        idx = self._load()
        if old not in idx["diseases"]:
            raise ValueError(f"'{old}'이(가) 없습니다")
        if new == old:
            return old
        _check_name(new)
        if folder_name(new) != folder_name(old) and any(folder_name(d) == folder_name(new) for d in idx["diseases"]):
            raise ValueError(f"'{new}'은(는) 이미 있습니다")
        src, dst = self.root / folder_name(old), self.root / folder_name(new)
        if src.is_dir() and src != dst:
            src.rename(dst)
        old_pre, new_pre = folder_name(old) + "/", folder_name(new) + "/"
        for key in ("notes", "credits"):
            idx[key] = {(new_pre + k[len(old_pre):] if k.startswith(old_pre) else k): v for k, v in idx[key].items()}
        idx["builtin"] = {f: (new_pre + k[len(old_pre):] if k.startswith(old_pre) else k) for f, k in idx["builtin"].items()}
        idx["diseases"][idx["diseases"].index(old)] = new
        self._save()
        return new

    def remove_disease(self, name: str) -> None:
        """The disease and its photos."""
        idx = self._load()
        if name not in idx["diseases"]:
            return
        folder = self.root / folder_name(name)
        if folder.is_dir():
            shutil.rmtree(folder)
        pre = folder_name(name) + "/"
        for key in ("notes", "credits"):
            idx[key] = {k: v for k, v in idx[key].items() if not k.startswith(pre)}
        idx["diseases"].remove(name)
        self._save()

    # -- photos ---------------------------------------------------------------------------------
    def photos(self, disease: str) -> list[Path]:
        """The disease's photos, in the order they were added (by their numbers)."""
        folder = self.root / folder_name(disease)
        try:
            if not folder.is_dir():
                return []
        except OSError:                       # (a name no file system takes, from an older index)
            return []
        return sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in PHOTO_EXTS),
                      key=lambda p: (p.stat().st_mtime, p.name))

    def count(self, disease: str) -> int:
        return len(self.photos(disease))

    def _new_path(self, disease: str, suffix: str) -> Path:
        folder = self.root / folder_name(disease)
        folder.mkdir(parents=True, exist_ok=True)
        k = len(self.photos(disease)) + 1
        while True:
            p = folder / f"{folder_name(disease)}_{k:03d}{suffix}"
            if not p.exists():
                return p
            k += 1

    def add_file(self, disease: str, src: Path | str, note: str = "") -> Path:
        """Copy a photo file in (under a name of its own)."""
        src = Path(src)
        if src.suffix.lower() not in PHOTO_EXTS:
            raise ValueError(f"사진 파일이 아닙니다: {src.name}")
        if disease not in self.diseases():
            self.add_disease(disease)
        dst = self._new_path(disease, src.suffix.lower())
        shutil.copyfile(src, dst)
        if note:
            self.set_note(dst, note)
        return dst

    def add_rgb(self, disease: str, rgb: np.ndarray, note: str = "") -> Path:
        """Save a photo (pixels: as shown, nothing else of it) in."""
        from PIL import Image

        if disease not in self.diseases():
            self.add_disease(disease)
        dst = self._new_path(disease, ".jpg")
        Image.fromarray(np.ascontiguousarray(rgb[..., :3])).save(dst, quality=93)
        if note:
            self.set_note(dst, note)
        return dst

    def remove_photo(self, path: Path | str) -> None:
        path = Path(path)
        key = self._key(path)
        if path.is_file():
            path.unlink()
        idx = self._load()
        if key in idx["notes"] or key in idx["credits"]:
            idx["notes"].pop(key, None)
            idx["credits"].pop(key, None)
            self._save()

    def _key(self, path: Path) -> str:
        return f"{path.parent.name}/{path.name}"

    def note(self, path: Path | str) -> str:
        return str(self._load()["notes"].get(self._key(Path(path)), ""))

    def set_note(self, path: Path | str, text: str) -> None:
        notes = self._load()["notes"]
        key = self._key(Path(path))
        text = text.strip()
        if text:
            notes[key] = text
        else:
            notes.pop(key, None)
        self._save()

    def credit(self, path: Path | str) -> str:
        """Who made a sample and under what licence (the program's own samples), or ''."""
        return str(self._load()["credits"].get(self._key(Path(path)), ""))

    # -- the program's own samples -----------------------------------------------------------------
    @staticmethod
    def builtin_list(folder: Path | None = None) -> list[dict]:
        """The program's own samples: ``{disease, file, note, credit, …}`` for each photo that is there."""
        folder = BUILTIN_DIR if folder is None else Path(folder)
        try:
            data = json.loads((folder / BUILTIN_INDEX).read_text("utf-8"))
        except (OSError, ValueError):
            return []
        out = []
        for it in data.get("photos", []):
            if isinstance(it, dict) and it.get("disease") and it.get("file") and (folder / it["file"]).is_file():
                out.append(it)
        return out

    def _add_builtin(self, it: dict, folder: Path) -> Path:
        src = folder / it["file"]
        dst = self.add_file(it["disease"], src, it.get("note", ""))
        if it.get("credit"):
            self._load()["credits"][self._key(dst)] = it["credit"]
        self._load()["builtin"][it["file"]] = self._key(dst)
        self._save()
        return dst

    def install_builtin(self, folder: Path | None = None) -> int:
        """Copy in the program's samples this library has not had yet; how many."""
        folder = BUILTIN_DIR if folder is None else Path(folder)
        had = self._load()["builtin"]
        n = 0
        for it in self.builtin_list(folder):
            if it["file"] in had:
                continue
            self._add_builtin(it, folder)
            n += 1
        return n

    def restore_builtin(self, folder: Path | None = None) -> int:
        """Bring back the program's samples that were deleted (or never copied in); how many."""
        folder = BUILTIN_DIR if folder is None else Path(folder)
        had = self._load()["builtin"]
        n = 0
        for it in self.builtin_list(folder):
            key = had.get(it["file"])
            if key and (self.root / key).is_file():
                continue
            self._add_builtin(it, folder)
            n += 1
        return n
