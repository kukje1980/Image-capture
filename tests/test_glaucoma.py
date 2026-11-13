"""3D · 녹내장 — 계산(유두 찾기·C/D)·렌더링·창."""
import cv2
import numpy as np
import pytest

from app.services import glaucoma as G


def fundus(size=480, disc=(0.7, 0.49), disc_r=0.07, cup_r=0.03):
    img = np.zeros((size, size, 3), np.uint8)
    yy, xx = np.mgrid[0:size, 0:size]
    d = np.hypot(xx - size / 2, yy - size / 2)
    img[d < size * 0.47] = (30, 70, 190)
    c = (int(size * disc[0]), int(size * disc[1]))
    cv2.circle(img, c, int(size * disc_r), (120, 200, 250), -1)
    cv2.circle(img, c, int(size * cup_r), (235, 250, 255), -1)
    img = cv2.GaussianBlur(img, (0, 0), 1.5)
    img[d >= size * 0.47] = 0
    return img


def test_detect_disc_finds_bright_disc():
    img = fundus()
    disc = G.detect_disc(img)
    assert abs(disc.cx - 480 * 0.7) < 12 and abs(disc.cy - 480 * 0.49) < 12
    assert 480 * 0.08 < disc.w < 480 * 0.3


def test_detect_disc_on_blank_image_returns_default():
    disc = G.detect_disc(np.zeros((200, 300, 3), np.uint8))
    assert (disc.cx, disc.cy) == (150, 100) and disc.w > 0


def test_cup_is_inside_disc_and_ratio_grows_with_cup():
    small, large = fundus(cup_r=0.02), fundus(cup_r=0.05)
    rs = []
    for img in (small, large):
        disc = G.detect_disc(img)
        cup = G.estimate_cup(img, disc)
        assert cup.w <= disc.w and cup.h <= disc.h
        rs.append(G.cd_ratios(disc, cup)["vertical"])
    assert rs[1] > rs[0]


def test_cd_ratios_and_comment():
    r = G.cd_ratios(G.Ellipse(0, 0, 100, 120), G.Ellipse(0, 0, 50, 84))
    assert r["horizontal"] == pytest.approx(0.5) and r["vertical"] == pytest.approx(0.7)
    assert r["area"] == pytest.approx(0.35) and r["rim_area"] == pytest.approx(0.65)
    assert "0.7 이상" in G.cd_comment(0.72) and "0.6 미만" in G.cd_comment(0.4)
    assert G.cd_ratios(G.Ellipse(0, 0, 0, 0), G.Ellipse(0, 0, 5, 5))["vertical"] == 0.0


def test_relief_cup_is_deeper_than_rim():
    img = fundus()
    disc = G.detect_disc(img)
    tex = G.crop_square(img, disc.cx, disc.cy, disc.w * 1.1, 200)
    hm = G.relief_height(tex)
    assert hm.shape == (200, 200) and 0 <= hm.min() and hm.max() <= 1
    assert hm[100, 100] > hm[10, 10] + 0.3                 # 가운데(함몰)가 주변 망막보다 깊다
    out = G.render_relief(tex, hm, size=300, overlays=[(G.Ellipse(100, 100, 80, 80), (255, 0, 0))])
    assert out.shape == (300, 300, 3) and out.reshape(-1, 3).max(axis=1).mean() > 20


def test_eyeball_render_and_stage_darkens_retina():
    img = fundus()
    disc = G.detect_disc(img)
    uv = (disc.cx / 480, disc.cy / 480)
    normal = G.render_eyeball(img, fov_deg=120, size=300, stage=0, disc_uv=uv)
    late = G.render_eyeball(img, fov_deg=120, size=300, stage=3, disc_uv=uv)
    assert normal.shape == (300, 300, 3)
    assert tuple(normal[2, 2]) == (16, 13, 11)             # 안구 밖은 배경
    assert late.astype(int).sum() != normal.astype(int).sum()
    yy, xx = np.mgrid[0:300, 0:300]
    ring = (np.hypot(xx - 150, yy - 150) < 120)
    assert late[ring].mean() < normal[ring].mean()         # 말기: 신경섬유층 결손으로 어두워짐


def test_field_narrows_with_stage():
    means = [G.field_simulation(s, 240).mean() for s in range(4)]
    assert means[0] > means[1] > means[2] > means[3]
    f0, f3 = G.field_simulation(0, 240), G.field_simulation(3, 240)
    h, w = f3.shape[:2]
    assert np.abs(f3[h // 2, w // 2].astype(int) - f0[h // 2, w // 2].astype(int)).max() < 12   # 가운데는 남는다
    assert f3[4, 4].mean() < f0[4, 4].mean() * 0.4                                               # 주변은 어두워진다


def test_dialog_stage_and_sliders(qapp):
    from app.ui.fundus.glaucoma3d import Glaucoma3DDialog
    dlg = Glaucoma3DDialog(fundus(), "OD", "테스트")
    before = dlg.ratios()["vertical"]
    assert 0.1 < before < 0.95
    dlg.set_stage(3)
    assert dlg.stage == 3 and dlg.stage_group.checkedId() == 3
    dlg.s_ch.setValue(90)
    assert dlg.ratios()["vertical"] == pytest.approx(0.9, abs=0.01)
    dlg._on_crop_click(0.6, 0.5)                            # 유두 중심 이동
    dlg.auto_detect()
    assert dlg.ratios()["vertical"] == pytest.approx(before, abs=0.02)
    dlg._on_eye_drag(30, 0)
    dlg._on_relief_drag(10, 10)
    dlg.close()


def test_dialog_3d_view_tab(qapp):
    from app.ui.fundus.glaucoma3d import Glaucoma3DDialog
    dlg = Glaucoma3DDialog(fundus(), "OS", "테스트")           # 기본 = 3D 보기, 자동 회전으로 열림
    assert dlg.tabs.currentIndex() == 0 and dlg.eye_pane.is_spinning()
    y0 = dlg.eye_pane.yaw
    dlg.eye_pane._spin()
    assert dlg.eye_pane.yaw != y0
    dlg.eye_pane.set_fov(200)
    assert dlg.glaucoma_pane.fov() == 200                    # 화각은 두 탭이 함께 쓴다
    dlg.eye_pane.c_view.setCurrentIndex(1)
    dlg.eye_pane.s_zoom.setValue(200)
    dlg.eye_pane.reset_view()
    assert (dlg.eye_pane.yaw, dlg.eye_pane.pitch) == (0.0, 0.0) and not dlg.eye_pane.is_spinning()
    dlg.eye_pane.set_spinning(True)
    dlg.tabs.setCurrentIndex(1)
    assert not dlg.eye_pane.is_spinning()                    # 다른 탭으로 가면 멈춘다
    assert Glaucoma3DDialog(fundus(), tab="disc").tabs.currentIndex() == 2
    dlg.close()


def test_channel_view_and_zoom():
    img = fundus()
    g = G.channel_view(img, "redfree")
    assert (g[..., 0] == img[..., 1]).all() and (g[..., 0] == g[..., 2]).all()
    assert (G.channel_view(img, "choroid")[..., 0] == img[..., 2]).all()
    assert G.channel_view(img, "color") is img
    big = G.render_eyeball(img, 0, 0, 120, 200, zoom=3.0)
    assert tuple(big[2, 2]) != (16, 13, 11)                  # 확대하면 화면 모서리까지 안구 안쪽


def test_review_tool_buttons_registered():
    """안저 검토 도구줄에 '3D 보기' · '녹내장' 버튼을 붙이는 배선이 있다."""
    import inspect

    from app.ui.main_window import MainWindow
    src = inspect.getsource(MainWindow)
    assert 'add_tool("3d"' in src and 'add_tool("glaucoma"' in src and "Glaucoma3DDialog" in src
