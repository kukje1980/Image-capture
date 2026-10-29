"""macOS support: settings folder, volumes and network shares, ⌘ wording,
trackpad pinch zoom and the app icon. Runs on every platform."""
import os
import sys
from pathlib import Path

import pytest

from fundusview import autosetup, config, watcher
from fundusview.ui.keys import keys

MOUNT_OUTPUT = """\
/dev/disk3s1s1 on / (apfs, sealed, local, read-only, journaled)
devfs on /dev (devfs, local, nobrowse)
/dev/disk3s5 on /System/Volumes/Data (apfs, local, journaled, nobrowse)
map auto_home on /System/Volumes/Data/home (autofs, automounted, nobrowse)
//clinic@nas.local/PatientCapture on /Volumes/PatientCapture (smbfs, nodev, nosuid, mounted by doctor)
afp_0TQJ3q00gYwl00ZtI00bdjU0-1.2d000017 on /Volumes/Old Share (afpfs, nodev, nosuid, mounted by doctor)
/dev/disk4s1 on /Volumes/RETICAM USB (msdos, local, nodev, nosuid, noowners, mounted by doctor)
"""


def test_settings_folder_on_macos(monkeypatch, tmp_path):
    monkeypatch.delenv("FUNDUSVIEW_HOME", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert config.config_dir() == tmp_path / "Library" / "Application Support" / "FundusViewer"
    assert config.default_inbox_dir() == tmp_path / "Documents" / "안저사진 가져오기"


def test_portable_home_wins_on_macos(monkeypatch, tmp_path):
    monkeypatch.setenv("FUNDUSVIEW_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "darwin")
    assert config.config_dir() == tmp_path


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need extra rights on Windows")
def test_volume_roots_skip_the_startup_disk(tmp_path):
    vols = tmp_path / "Volumes"
    (vols / "RETICAM USB" / "reticam").mkdir(parents=True)
    (vols / "PatientCapture").mkdir()
    (vols / "Macintosh HD").symlink_to("/")
    (vols / "stray-file").write_text("x")
    roots = autosetup.mac_volume_roots(str(vols))
    assert roots == [str(vols / "PatientCapture"), str(vols / "RETICAM USB")]
    found = autosetup.detect(roots, home=tmp_path / "home")
    assert (str(vols / "RETICAM USB" / "reticam"), "reticam") in found


def test_drive_roots_are_volumes_on_macos(monkeypatch, tmp_path):
    (tmp_path / "NAS").mkdir()
    monkeypatch.setattr(sys, "platform", "darwin")
    assert autosetup.drive_roots(str(tmp_path)) == [str(tmp_path / "NAS")]
    assert autosetup.mac_volume_roots(str(tmp_path / "missing")) == []


def test_network_shares_from_the_mount_table():
    mounts = watcher.mac_network_mounts(MOUNT_OUTPUT)
    assert mounts == ["/Volumes/PatientCapture", "/Volumes/Old Share"]
    assert watcher.is_network_path("/Volumes/PatientCapture/2026/10", mounts)
    assert watcher.is_network_path("/Volumes/Old Share", mounts)
    assert not watcher.is_network_path("/Volumes/PatientCaptureX", mounts)
    assert not watcher.is_network_path("/Volumes/RETICAM USB/reticam", mounts)
    assert watcher.is_network_path("//nas/share", [])          # UNC stays a network path


def test_command_key_wording():
    assert keys("두 번째 사진을 Ctrl+클릭 (Ctrl+Z)", mac=True) == "두 번째 사진을 ⌘클릭 (⌘Z)"
    assert keys("Ctrl+F", mac=False) == "Ctrl+F"


def test_icns_icon(tmp_path):
    from PIL import Image

    from fundusview.ui.icon import write_icns
    p = tmp_path / "FundusViewer.icns"
    write_icns(p)
    im = Image.open(p)
    assert im.format == "ICNS" and im.size == (1024, 1024)


# -- trackpad pinch ------------------------------------------------------------------
pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_pinch_zooms_the_photo_at_the_fingers(app):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QNativeGestureEvent, QPointingDevice

    from fundusview.demo import synth_fundus
    from fundusview.ui.image_view import ImageView

    v = ImageView()
    v.resize(800, 600)
    v.show()
    v.set_rgb(synth_fundus(eye="OD", size=(900, 600), circle=(450, 300, 330), seed=5))
    app.processEvents()
    v.zoom_to(1.0)
    at = QPoint(300, 200)
    under = v.mapToScene(at)
    v.pinch(0.5, at)
    assert v._zoom == pytest.approx(1.5)
    back = v.mapToScene(at)
    assert (back.x(), back.y()) == pytest.approx((under.x(), under.y()), abs=1.0)

    # a real gesture event, as the Mac trackpad delivers it
    ev = QNativeGestureEvent(Qt.NativeGestureType.ZoomNativeGesture, QPointingDevice.primaryPointingDevice(),
                             2, QPointF(at), QPointF(at), QPointF(v.viewport().mapToGlobal(at)),
                             -0.2, QPointF(0, 0))
    app.sendEvent(v.viewport(), ev)
    assert v._zoom == pytest.approx(1.2)


def test_pinch_zooms_the_3d_eye(app):
    from PySide6.QtCore import QPointF

    from fundusview.ui.eye3d import EyeView
    e = EyeView()
    e.resize(900, 700)
    m0 = e.magnification
    e.pinch(0.5, QPointF(450, 350))
    assert e.magnification == pytest.approx(m0 * 1.5, rel=0.02)
    e.pinch(-1.0, QPointF(450, 350))        # degenerate value: ignored
    assert e.magnification == pytest.approx(m0 * 1.5, rel=0.02)
