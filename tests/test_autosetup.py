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
