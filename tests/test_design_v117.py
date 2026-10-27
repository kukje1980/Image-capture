"""v1.17 — Keeler K 4색 디자인 · 홈 화면 사진 · 좁은 창(글자·아이콘 겹침 없음) · 저장 버튼 위치 ·
분할 칸 수 기억 · 참조 영상 비교 화면 저장."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app import brand
from app.ui import split_menu
from tests.test_references import _make_window, _samples, _wait


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def keeler(qapp, app_env, monkeypatch):
    w = _make_window(qapp, app_env, monkeypatch, "keeler")
    yield w
    w.close()
    brand.select("default")


@pytest.fixture()
def win(qapp, app_env, monkeypatch):
    w = _make_window(qapp, app_env, monkeypatch, "default")
    yield w
    w.close()
    brand.select("default")


def _png(path: Path, w=64, h=48) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = np.zeros((h, w, 3), np.uint8)
    img[:, : w // 2] = (30, 120, 220)
    cv2.imencode(".png", img)[1].tofile(str(path))          # 한글 경로도
    return path


# ---------------- Keeler K 4색 ----------------
def test_keeler_k_colors(keeler):
    from app.ui import theme
    w = keeler
    assert w.brand_stripe is not None and w.brand_stripe.objectName() == "BrandStripe"
    assert theme.palette("dark")["od"] == "#6cbce8" and theme.palette("dark")["os"] == "#ed6f1e"
    qss = theme.build_qss("dark")
    assert 'QPushButton#HomeTile[kc="2"] { border-bottom: 3px solid #ed6f1e; }' in qss
    assert w.home.kicker is not None and "SLIT LAMP" in w.home.kicker.text()
    assert [w.home.tiles[k].property("kc") for k in ("newPatient", "patients", "capture")] == ["0", "1", "2"]


def test_default_brand_has_no_stripe(win):
    from app.ui import theme
    assert win.brand_stripe is None and "BrandStripe" not in theme.build_qss("dark")
    assert win.home.kicker is None and win.home.hero.isHidden()          # 기본판: 사진을 넣기 전엔 큰 사진 칸 없음


# ---------------- 홈 화면 사진 ----------------
def test_home_hero_photo(keeler, tmp_path):
    h = keeler.home
    # Keeler: 기본 홈 사진 = 배경을 떼어 낸 Keeler 슬릿램프 장비 사진 (바탕 위에 장비만, 글자 없음)
    assert h.hero_path() == brand.asset("brand/keeler/home.png") and Path(h.hero_path()).is_file()
    assert not h.hero.isHidden() and h.hero.has_photo() and h.hero.is_cutout()
    img = h.hero.photo().toImage()
    assert img.pixelColor(0, 0).alpha() == 0 and img.pixelColor(img.width() // 2, img.height() // 2).alpha() == 255
    pm = h.hero.grab()
    assert not pm.isNull() and pm.width() > 100
    src = _png(tmp_path / "장비 사진" / "keeler 슬릿.png")
    assert h.set_home_image(str(src))
    own = Path(keeler.config.home_image)
    assert own.is_file() and own.parent.name == "home" and own != src  # 데이터 폴더로 복사
    assert h.hero.has_photo() and h.hero_path() == str(own)
    assert not h.hero.is_cutout()                                     # 배경이 있는 사진은 칸을 꽉 채움
    assert not h.hero.grab().isNull()
    assert not h.set_home_image(str(tmp_path / "없는 파일.jpg"))
    h.reset_home_image()
    assert keeler.config.home_image == "" and not own.exists()
    assert h.hero_path() == brand.asset("brand/keeler/home.png") and h.hero.is_cutout()


def test_home_hero_white_photo_cutout(qapp, tmp_path):
    """흰 배경 제품 사진은 불러올 때 배경을 떼어 장비만 보인다."""
    from app.ui.home_hero import HomeHero
    img = np.full((120, 160, 3), 255, np.uint8)
    img[30:100, 50:110] = (60, 50, 40)                                  # 장비
    img[40:60, 60:100] = (220, 222, 225)                               # 장비 안의 밝은 부분은 그대로
    path = tmp_path / "흰 배경.jpg"
    cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tofile(str(path))
    hero = HomeHero()
    hero.resize(400, 300)
    assert hero.set_image(str(path)) and hero.is_cutout()
    q = hero.photo().toImage()
    assert q.pixelColor(2, 2).alpha() == 0 and q.pixelColor(80, 65).alpha() == 255
    assert q.pixelColor(80, 50).alpha() == 255                         # 밝은 회색 부분은 지우지 않음
    assert not hero.grab().isNull()


def test_home_hero_art_without_photo(qapp):
    from app.ui.home_hero import HomeHero
    hero = HomeHero()
    hero.resize(520, 360)
    assert not hero.set_image(None) and not hero.has_photo() and not hero.is_cutout()
    assert not hero.grab().isNull()                                    # 사진이 없으면 슬릿 빛줄기 그림


def test_default_brand_home_photo_optional(win, tmp_path):
    h = win.home
    assert h.set_home_image(str(_png(tmp_path / "home.png")))
    assert not h.hero.isHidden() and h.hero.has_photo()
    h.reset_home_image()
    assert h.hero.isHidden()


# ---------------- 좁은 창 ----------------
def test_narrow_window_no_overlap(qapp, keeler):
    w = keeler
    w.resize(1500, 860)
    _wait(qapp, lambda: not w._topbar_compact, 1.0)
    assert not w._topbar_compact and all(b.is_text_visible() for b in w.nav_buttons)
    # 1280px(1920×1080 · 150% 배율) 화면에도 들어감 — Windows 글꼴은 더 넓어 약 1110px (리눅스 약 1000px)
    min_w = w.minimumSizeHint().width()
    assert min_w < 1200
    w.resize(min_w, 700)                                               # 가장 좁게
    _wait(qapp, lambda: w.width() <= min_w + 2, 2.0)
    for _ in range(20):
        qapp.processEvents()
    # 상단바가 다 들어가지 않으면 아이콘만 (이름은 풍선 도움말)
    assert w._topbar_compact == (w.topbar.width() < w._topbar_full_w)
    assert all(b.is_text_visible() != w._topbar_compact for b in w.nav_buttons)
    if w._topbar_compact:
        assert w.btn_mode_capture.text() == "촬영" and "촬영" in w.btn_mode_capture.toolTip()
    for b in w.nav_buttons:                                            # 눌려 찌그러진 버튼 없음
        assert b.width() >= b.minimumSizeHint().width() and b.height() >= b.minimumSizeHint().height()
    assert w.control_bar.is_compact()                                  # 촬영 도크도 아이콘만
    sc = w.control_bar.parentWidget().parentWidget()                   # HScroll(뷰포트(도크))
    assert sc.objectName() == "HScroll"
    ok = _wait(qapp, lambda: not sc.overflowing(), 2.0)               # 아이콘만으로 셔터까지 한 줄에
    assert ok, (f"window {w.width()} min {min_w} viewport {sc.viewport().width()} "
                f"dock {w.control_bar.minimumSizeHint().width()} thumbs {w.thumbnail_panel.width()} "
                f"eye {[b.width() for b in w.control_bar.eye_buttons.values()]}")
    for b in w.control_bar._sized_buttons:
        if b.isVisible():
            assert b.width() >= b.minimumSizeHint().width()
    w.resize(1600, 900)
    assert _wait(qapp, lambda: not w._topbar_compact and not w.control_bar.is_compact(), 2.0)
    assert all(b.is_text_visible() for b in w.nav_buttons)


def test_topbar_compact_when_narrower_than_full(qapp, keeler):
    w = keeler
    w.resize(1600, 900)
    _wait(qapp, lambda: not w._topbar_compact, 1.0)
    full = w._topbar_full_w
    w.topbar.resize(full - 40, w.topbar.height())                     # 상단바가 다 들어가지 않는 폭
    assert w._topbar_compact and not any(b.is_text_visible() for b in w.nav_buttons)
    w.topbar.resize(full + 40, w.topbar.height())
    assert not w._topbar_compact and all(b.is_text_visible() for b in w.nav_buttons)


def test_smart_bar_hidden_with_wrapper(qapp, win):
    sc = win.smart_bar.parentWidget().parentWidget()
    assert sc.objectName() == "HScroll"
    win._set_smart_bar_visible(False, save=False)
    assert sc.isHidden()
    win._set_smart_bar_visible(True, save=False)
    assert not sc.isHidden() and win.smart_bar.isVisible()


# ---------------- 저장 버튼 위치 ----------------
def test_save_button_next_to_freeze(qapp, win):
    cb = win.control_bar
    win.control_bar.count_chooser = lambda anchor: 4
    shutter_x = cb.btn_capture.mapTo(cb, cb.btn_capture.rect().topLeft()).x()
    QTest.mouseClick(cb.btn_quad, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    assert win._quad and cb.btn_save_quad.isVisible()
    save = cb.btn_save_quad.mapTo(cb, cb.btn_save_quad.rect().topLeft()).x()
    freeze = cb.btn_freeze.mapTo(cb, cb.btn_freeze.rect().topLeft()).x()
    assert save < freeze and freeze - (save + cb.btn_save_quad.width()) <= 12   # 정지영상 바로 왼쪽
    assert cb.btn_capture.mapTo(cb, cb.btn_capture.rect().topLeft()).x() == shutter_x   # 셔터는 제자리
    win._on_save_quad()                                                # 저장 동작은 그대로


# ---------------- 분할 칸 수 기억 ----------------
def test_split_count_remembered(qapp, win, monkeypatch):
    cb = win.control_bar
    asked = []

    def pick(text):
        def run(menu, pos):
            asked.append(text)
            return next(a for a in menu.actions() if a.text() == text)
        return run
    monkeypatch.setattr(win, "_exec_menu", pick("6분할"))
    assert not cb.count_saved
    QTest.mouseClick(cb.btn_quad, Qt.MouseButton.LeftButton)          # 처음 한 번은 묻는다
    assert win._quad and win.quad_view.count() == 6 and asked == ["6분할"]
    assert win.config.split_count == 6 and win.config.split_count_saved and cb.count_saved
    QTest.mouseClick(cb.btn_quad, Qt.MouseButton.LeftButton)          # 끄기
    monkeypatch.setattr(win, "_exec_menu", lambda menu, pos: pytest.fail("저장한 뒤에는 묻지 않아야 함"))
    QTest.mouseClick(cb.btn_quad, Qt.MouseButton.LeftButton)          # 그다음부터는 바로 6분할
    assert win._quad and win.quad_view.count() == 6 and cb.btn_quad.text() == "6분할"
    assert "저장한 6분할" in cb.btn_quad.toolTip()

    monkeypatch.setattr(win, "_exec_menu", pick("2분할"))           # 오른쪽 클릭: 칸 수 바꾸기
    cb.btn_quad.customContextMenuRequested.emit(cb.btn_quad.rect().center())
    assert win._quad and win.quad_view.count() == 2 and win.config.split_count == 2
    assert cb.btn_quad.text() == "2분할"

    monkeypatch.setattr(win, "_exec_menu", pick(split_menu.ASK_TEXT))   # 다시 매번 묻기
    cb.change_split_count()
    assert not win.config.split_count_saved and not cb.count_saved


def test_settings_split_ask_checkbox(qapp, win):
    from app.ui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(win.config, win)
    assert dlg.split_ask.isChecked()                                   # 처음엔 '누를 때마다 묻기'
    dlg.split_count.setCurrentIndex(dlg.split_count.findData(8))       # 칸 수를 고르면 저장한 것으로
    assert not dlg.split_ask.isChecked()
    dlg.apply_to_config()
    assert win.config.split_count == 8 and win.config.split_count_saved
    dlg.close()


# ---------------- 참조 영상 비교 화면 저장 ----------------
def test_reference_compare_screen_save(qapp, win, tmp_path):
    w = win
    assert w._import_samples(folder=str(_samples(tmp_path / "s")))
    w.patient_panel.select_patient(next(p.id for p in w.db.patients.list_all() if p.chart_no == "R1"))
    w._on_capture()
    pid = w._current_patient.id
    assert _wait(qapp, lambda: any(c.media_type == "photo" for c in w.db.captures.list_by_patient(pid)))
    before = len(w.db.captures.list_by_patient(pid))
    lib = w.open_references()
    cmp = lib.compare()
    assert cmp is not None and not cmp.b_save.isHidden()
    qapp.processEvents()
    img = cmp.screen_bgr()
    assert img is not None and img.ndim == 3 and img.shape[1] >= 400
    msg = cmp.save_screen()
    assert msg and "저장" in msg
    caps = w.db.captures.list_by_patient(pid)
    assert len(caps) == before + 1
    saved = next(c for c in caps if (c.note or "").startswith("샘플 비교"))
    assert Path(saved.file_path).is_file()

    out = cmp.save_file(str(tmp_path / "내보내기" / "비교 화면"))      # 확장자 없으면 .png
    assert out.endswith(".png") and Path(out).is_file()
    assert cv2.imdecode(np.fromfile(out, np.uint8), cv2.IMREAD_COLOR) is not None
    out2 = lib.export_current(str(tmp_path / "참조.jpg"))                # 라이브러리: 고른 참조 영상 파일로
    assert out2 and Path(out2).is_file()
    cmp.close()
    lib.close()


def test_compare_without_patient_hides_save(qapp):
    from app.ui.explorer.compare_dialog import CompareDialog
    img = np.zeros((40, 60, 3), np.uint8)
    dlg = CompareDialog([(img, "a"), (img, "b")])
    assert dlg.b_save.isHidden() and not dlg.b_file.isHidden() and dlg.save_screen() is None
    dlg.close()
