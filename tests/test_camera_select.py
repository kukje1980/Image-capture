"""카메라 선택: 설정 창에서 항상 장치를 고를 수 있고, 저장된 카메라가 없으면 분명히 알린다."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from app.ui import settings_dialog as sd
from app.ui import theme


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


NAMES = ["Camera Sensor Front", "Sony Camera (Imaging Edge)"]


def _dialog(config, monkeypatch, names):
    monkeypatch.setattr(sd, "device_names", lambda *a, **k: list(names))
    monkeypatch.setattr(sd, "enumerate_devices", lambda *a, **k: [])
    return sd.SettingsDialog(config)


def test_cameras_listed_even_in_synthetic_mode(qapp, app_env, monkeypatch):
    config, _ = app_env
    config.source_mode = "synthetic"
    config.save = lambda: None
    dlg = _dialog(config, monkeypatch, NAMES)
    labels = [dlg.camera_index.itemText(i) for i in range(dlg.camera_index.count())]
    assert labels == ["0: Camera Sensor Front", "1: ★ Sony Camera (Imaging Edge)"]
    assert not dlg.camera_index.isEditable()             # 목록에서 고르는 상자 (입력칸 아님)
    assert dlg.source_mode.currentData() == "synthetic"
    assert "합성" in dlg.source_mode.currentText()
    dlg.camera_index.setCurrentIndex(1)
    dlg._on_camera_picked(1)                              # 카메라를 고르면 실제 장치 모드로
    dlg.apply_to_config()
    assert config.source_mode == "device"
    assert config.camera_index == 1 and config.camera_name == "Sony Camera (Imaging Edge)"


def test_saved_camera_selected_by_name(qapp, app_env, monkeypatch):
    config, _ = app_env
    config.source_mode = "device"
    config.camera_index, config.camera_name = 0, "Sony Camera (Imaging Edge)"
    dlg = _dialog(config, monkeypatch, NAMES)
    assert dlg.camera_index.currentData() == 1           # 번호가 바뀌어도 이름으로 찾음
    assert dlg.camera_note.isHidden()


def test_missing_saved_camera_is_announced_and_rescan_finds_it(qapp, app_env, monkeypatch):
    config, _ = app_env
    config.source_mode = "device"
    config.camera_index, config.camera_name = 1, "Sony Camera (Imaging Edge)"
    dlg = _dialog(config, monkeypatch, ["Camera Sensor Front"])
    assert not dlg.camera_note.isHidden()
    assert "Sony Camera (Imaging Edge)" in dlg.camera_note.text()
    monkeypatch.setattr(sd, "device_names", lambda *a, **k: list(NAMES))
    dlg.btn_rescan.click()                                # 연결 후 새로고침
    assert dlg.camera_index.count() == 2
    assert dlg.camera_index.currentData() == 1
    assert dlg.camera_note.isHidden()


def test_no_names_allows_typing_index(qapp, app_env, monkeypatch):
    config, _ = app_env
    config.source_mode = "device"
    config.camera_index, config.camera_name = 2, ""
    dlg = _dialog(config, monkeypatch, [])
    assert dlg.camera_index.isEditable()
    assert not dlg.camera_note.isHidden()


def test_combo_and_spin_arrows_in_stylesheet():
    for mode in ("dark", "light"):
        qss = theme.build_qss(mode)
        assert "QComboBox::down-arrow" in qss and "chev-down-" in qss
        assert "QSpinBox::up-arrow" in qss
        # 화살표 규칙이 일반 입력칸 규칙보다 뒤에 있어야 padding 이 덮이지 않는다
        assert qss.index("QComboBox::down-arrow") > qss.index("QLineEdit, QComboBox, QSpinBox")
    import re
    from pathlib import Path
    for f in set(re.findall(r'url\("([^"]+chev-[^"]+)"\)', theme.build_qss("dark"))):
        assert Path(f).read_text(encoding="utf-8").startswith("<svg")
