from pathlib import Path

from fundusview import autosetup
from fundusview.config import ACTION_COPY, ACTION_MOVE, Settings, WatchFolder


def test_detect_device_folders(tmp_path):
    d = tmp_path / "D"
    (d / "레티캠" / "VK_3X").mkdir(parents=True)
    (d / "MC" / "Cro" / "PatientCapture").mkdir(parents=True)
    home = tmp_path / "home"
    (home / "MicroClearClient" / "ImageData").mkdir(parents=True)
    found = autosetup.detect([str(d), str(tmp_path / "missing")], home=home)
    assert (str(d / "레티캠"), "reticam") in found
    assert (str(d / "MC" / "Cro" / "PatientCapture"), "apollo") in found
    assert (str(home / "MicroClearClient" / "ImageData"), "apollo") in found


def test_apply_adds_inbox_and_devices_once(tmp_path):
    dev = tmp_path / "D" / "reticam"
    dev.mkdir(parents=True)
    s = Settings(library_dir=str(tmp_path / "lib"), inbox_dir=str(tmp_path / "inbox"))
    added = autosetup.apply(s, [(str(dev), "reticam")])
    assert [(Path(f.path).name, f.profile, f.action) for f in added] == [
        ("inbox", "auto", ACTION_MOVE), ("reticam", "reticam", ACTION_COPY)]
    assert (tmp_path / "inbox").is_dir()
    assert autosetup.apply(s, [(str(dev), "reticam")]) == []          # no duplicates


def test_removed_folders_are_not_re_added(tmp_path):
    dev = tmp_path / "reticam"
    dev.mkdir()
    s = Settings(library_dir=str(tmp_path / "lib"), inbox_dir=str(tmp_path / "inbox"))
    autosetup.apply(s, [(str(dev), "reticam")])
    before = list(s.watch_folders)
    s.watch_folders = [f for f in s.watch_folders if Path(f.path).name != "reticam"]
    autosetup.remember_removed(s, before)
    assert autosetup.apply(s, [(str(dev), "reticam")]) == []


def test_auto_detect_off_keeps_only_inbox(tmp_path):
    dev = tmp_path / "reticam"
    dev.mkdir()
    s = Settings(library_dir=str(tmp_path / "lib"), inbox_dir=str(tmp_path / "inbox"), auto_detect=False,
                 watch_folders=[WatchFolder(path=str(tmp_path / "inbox"))])
    (tmp_path / "inbox").mkdir()
    assert autosetup.apply(s, [(str(dev), "reticam")]) == []


def _with_inbox(tmp_path, name="inbox", **kw):
    s = Settings(library_dir=str(tmp_path / "lib"), inbox_dir=str(tmp_path / name), auto_detect=False, **kw)
    autosetup.apply(s, [])
    return s


def test_change_inbox_moves_the_watch_entry(tmp_path):
    s = _with_inbox(tmp_path)
    s.watch_folders[0].polling = True                  # options chosen for the inbox stay
    s.inbox_dir = str(tmp_path / "새 가져오기")
    entry = autosetup.change_inbox(s, str(tmp_path / "inbox"))
    assert [(Path(f.path).name, f.action, f.polling) for f in s.watch_folders] == [
        ("새 가져오기", ACTION_MOVE, True)]
    assert entry is s.watch_folders[0] and (tmp_path / "새 가져오기").is_dir()
    assert s.ignored_auto_folders == []                # the old one is not "removed by the user"
    s.inbox_dir = str(tmp_path / "inbox")              # switching back works
    autosetup.change_inbox(s, str(tmp_path / "새 가져오기"))
    assert [Path(f.path).name for f in s.watch_folders] == ["inbox"]
    assert autosetup.apply(s, []) == []                 # next start: nothing added twice


def test_change_inbox_to_a_folder_already_watched(tmp_path):
    dev = tmp_path / "reticam"
    dev.mkdir()
    s = _with_inbox(tmp_path)
    s.watch_folders.append(WatchFolder(path=str(dev), profile="reticam", action=ACTION_COPY))
    s.inbox_dir = str(dev)
    entry = autosetup.change_inbox(s, str(tmp_path / "inbox"))
    assert [(Path(f.path).name, f.profile, f.action) for f in s.watch_folders] == [
        ("reticam", "reticam", ACTION_COPY)]            # no duplicate, its own options kept
    assert entry is s.watch_folders[0]


def test_change_inbox_after_the_old_one_was_removed(tmp_path):
    s = _with_inbox(tmp_path)
    before = list(s.watch_folders)
    s.watch_folders = []
    autosetup.remember_removed(s, before)
    s.ignored_auto_folders.append(str(tmp_path / "new"))
    s.inbox_dir = str(tmp_path / "new")
    autosetup.change_inbox(s, str(tmp_path / "inbox"))
    assert [(Path(f.path).name, f.action) for f in s.watch_folders] == [("new", ACTION_MOVE)]
    assert str(tmp_path / "new") not in s.ignored_auto_folders


def test_change_inbox_unchanged_or_inside_library(tmp_path):
    s = _with_inbox(tmp_path)
    assert autosetup.change_inbox(s, str(tmp_path / "inbox")) is None
    s.inbox_dir = str(tmp_path / "lib" / "in")
    assert autosetup.change_inbox(s, str(tmp_path / "inbox")) is None
    assert [Path(f.path).name for f in s.watch_folders] == ["inbox"]


def test_inbox_problem(tmp_path):
    lib = str(tmp_path / "lib")
    assert autosetup.inbox_problem("", lib) is None
    assert "라이브러리" in autosetup.inbox_problem(lib, lib)
    assert "라이브러리" in autosetup.inbox_problem(str(tmp_path / "lib" / "x"), lib)
    assert autosetup.inbox_problem(str(tmp_path / "새 폴더"), lib) is None and (tmp_path / "새 폴더").is_dir()
    (tmp_path / "file").write_text("x")
    assert "만들 수 없습니다" in autosetup.inbox_problem(str(tmp_path / "file" / "sub"), lib)
