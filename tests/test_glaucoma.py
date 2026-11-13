"""녹내장 분석: 정합·시차·C/D·광각 좌표 계산과 분석 창 흐름."""
from __future__ import annotations

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from app.capture import glaucoma as G
from app.db.database import Database  # noqa: F401  (app_env 픽스처가 사용)
from app.models.patient import Patient
from app.services.capture_service import CaptureService


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _texture(h=300, w=300, seed=3):
    rng = np.random.default_rng(seed)
    img = cv2.GaussianBlur(rng.integers(0, 255, (h, w, 3), dtype=np.uint8), (0, 0), 2)
    return cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)


def _stereo_pair(d=5):
    """가운데 원(컵)만 깊이가 있는 스테레오 쌍: 왼쪽 영상에서는 왼쪽, 오른쪽 영상에서는 오른쪽으로 밀린다."""
    base = _texture()
    h, w = base.shape[:2]
    yy, xx = np.mgrid[:h, :w]
    cup = (xx - w / 2) ** 2 + (yy - h / 2) ** 2 < 60 ** 2
    left, right = base.copy(), base.copy()
    left[cup] = np.roll(base, -d, axis=1)[cup]
    right[cup] = np.roll(base, d, axis=1)[cup]
    return left, right, cup


def test_find_shift_recovers_translation():
    a = _texture()
    b = G.shifted(a, 9, 5)                                # b 는 a 를 (9, 5) 옮긴 것
    dx, dy = G.find_shift(a, b)
    assert abs(dx + 9) <= 1 and abs(dy + 5) <= 1          # 되돌리는 이동량
    back = G.shifted(b, dx, dy)
    assert np.abs(back[40:-40, 40:-40].astype(int) - a[40:-40, 40:-40]).mean() < 12


def test_stereo_views_and_depth_sign():
    left, right, cup = _stereo_pair()
    assert G.side_by_side(left, right).shape == (300, 610, 3)
    ana = G.anaglyph(left, right)
    assert np.array_equal(ana[..., 0], ana[..., 1])       # 청록 = 오른쪽 눈
    assert np.array_equal(ana[..., 2], cv2.cvtColor(left, cv2.COLOR_BGR2GRAY))
    disp = G.disparity(left, right)
    small = cv2.resize(cup.astype(np.uint8), disp.shape[::-1]) > 0
    assert disp[small].mean() > 2 and abs(disp[~small].mean()) < 1     # 컵 = 양수(깊음)
    assert G.disparity(right, left)[small].mean() < -2                 # 좌우를 바꾸면 뒤집힌다
    deep, _ = G.disparity_range(disp, 300)
    assert deep > 5
    assert G.depth_overlay(left, disp).shape == left.shape
    assert G.depth_profile(disp, 150, 300, 300).shape == (120, 300, 3)


def test_cdr_metrics_and_isnt():
    disc = {"cx": 300, "cy": 300, "rx": 150, "ry": 160}
    m = G.cdr_metrics(disc, {"cx": 300, "cy": 300, "rx": 75, "ry": 80}, "OD")
    assert m["vertical"] == pytest.approx(0.5) and m["horizontal"] == pytest.approx(0.5)
    assert m["area"] == pytest.approx(0.25) and m["rim"]["I"] == pytest.approx(0.25)
    # 컵이 아래로 치우치면 하측 림이 얇아져 ISNT 가 어긋난다
    m = G.cdr_metrics(disc, {"cx": 300, "cy": 330, "rx": 75, "ry": 80}, "OD")
    assert m["rim"]["I"] < m["rim"]["S"] and "하측 림이 상측보다 얇음" in m["isnt"]
    # 컵이 화면 왼쪽으로 치우침: 우안은 이측, 좌안은 비측이 얇다
    cup = {"cx": 270, "cy": 300, "rx": 75, "ry": 80}
    assert G.cdr_metrics(disc, cup, "OD")["rim"]["T"] < G.cdr_metrics(disc, cup, "OD")["rim"]["N"]
    assert G.cdr_metrics(disc, cup, "OS")["rim"]["N"] < G.cdr_metrics(disc, cup, "OS")["rim"]["T"]


def test_wide_geometry():
    disc, fovea = (610, 300), (452, 318)                  # 디스크가 오른쪽 = 우안
    assert G.axes(disc, fovea)["od"] and G.disc_fovea_angle(disc, fovea) > 0
    it = G.sector_info(disc, fovea, (550, 410))           # 디스크의 왼쪽 아래 = 하이측
    assert (it["hour"], it["sector"]) == (7, "하이측") and "상측" in it["field"]
    assert G.sector_info(disc, fovea, (610, 200))["hour"] == 12
    assert G.sector_info(disc, fovea, (700, 300))["sector"] == "비측"
    # 좌안(디스크가 왼쪽)에서는 이측이 3시
    assert G.sector_info((300, 300), (460, 318), (400, 310))["hour"] == 3
    pts = G.vf_points(disc, fovea)
    assert len(pts) == 54
    assert all((y > 300) == upper for _x, y, upper in pts if abs(y - 309) > 25)   # 상측 시야 = 하측 망막
    assert min(np.hypot(x - disc[0], y - disc[1]) for x, y, _u in pts) < 40       # 맹점이 디스크 근처
    assert [name for name, _rgb, _poly in G.sector_polygons(disc, fovea)] == [s[0] for s in G.SECTORS]


def test_enhance_and_diff():
    img = _texture()
    rf = G.enhance_wide(img, red_free=True, k=1.5)
    assert np.array_equal(rf[..., 0], rf[..., 2]) and rf.std() > img[..., 1].std()
    assert np.array_equal(G.enhance_wide(img, red_free=False, k=0), img)
    changed = img.copy()
    changed[100:140, 100:140] = 255
    d = G.diff_map(img, changed)
    assert d[120, 120, 2] > 200 and d[120, 120, 1] < 120                  # 변화 = 분홍
    assert np.array_equal(d[20, 20], np.repeat(d[20, 20, :1], 3))         # 그대로인 곳은 회색


# ---------------- 분석 창 ----------------
def _workspace(app_env, frames):
    from app.ui.pro.pro_workspace import ProWorkspace

    config, db = app_env
    svc = CaptureService(db, config)
    pid = db.patients.insert(Patient(chart_no="G1", name="녹내장환자"))
    patient = db.patients.get(pid)
    for f in frames:
        svc.save_photo(f, patient, eye="OS")
    ws = ProWorkspace(db, svc, config, get_eye=lambda: "OS")
    ws.resize(1200, 800)
    ws.set_patient(patient)
    return ws, db, patient


def test_dialog_uses_selected_pair_and_saves(qapp, app_env):
    left, right, _cup = _stereo_pair()
    ws, db, patient = _workspace(app_env, [left, G.shifted(right, 8, 4)])
    ws.select_for_compare(0, 1)
    dlg = ws.open_glaucoma(show=False)
    st = dlg.stereo
    assert st.has_image() and abs(st.dx + 8) <= 1.5 and abs(st.dy + 4) <= 1.5   # 열면서 자동 정렬
    for mode, shape in (("sbs", (300, 610)), ("cross", (300, 610)), ("ana", (300, 300)), ("depth", (420, 300))):
        st.set_mode(mode)
        assert st.compose().shape[:2] == shape
    assert "시차" in st.status.text()

    cap = dlg.save()                                       # 스테레오 탭 저장
    assert cap is not None and cap.note == "스테레오 깊이 지도" and cap.eye == "OS"
    dlg.tabs.setCurrentWidget(dlg.disc)
    assert dlg.disc.eye == "OS" and dlg.disc.metrics()["vertical"] == pytest.approx(0.5)
    assert dlg.save().note == "CDR 0.50"
    dlg.tabs.setCurrentWidget(dlg.progress)
    dlg.progress.set_mode("diff")
    assert dlg.save().note == "경과 비교"
    notes = [c.note for c in db.captures.list_by_patient(patient.id, order="asc")]
    assert notes[2:] == ["스테레오 깊이 지도", "CDR 0.50", "경과 비교"]
    assert len(ws.captures()) == 5 and ws.multi.selection() == [0, 1]     # 목록 갱신, 선택 유지


def test_dialog_wide_marks_and_empty_state(qapp, app_env):
    ws, _db, _patient = _workspace(app_env, [_texture(620, 900)])
    dlg = ws.open_glaucoma(show=False)
    assert not dlg.stereo.has_image() and not dlg.progress.has_image()    # 2장이 없으면 비어 있다
    dlg.tabs.setCurrentWidget(dlg.stereo)
    assert dlg.save() is None and "없습니다" in dlg.lbl_msg.text()

    w = dlg.wide
    assert w.tool == "disc" and w.findings() == []
    w.click(610, 300)                                      # 디스크 → 자동으로 황반 지정 차례
    assert w.tool == "fovea"
    w.click(452, 318)
    assert w.tool == "mark"
    w.click(550, 410)
    f = w.findings()[0]
    assert (f["kind"], f["hour"], f["sector"]) == ("RNFL 결손", 7, "하이측")
    assert "7시 방향" in w.lbl_list.text()
    dlg.tabs.setCurrentWidget(w)
    out = w.render()
    assert out.shape == (620, 900, 3)
    assert dlg.save().note == "광각 RNFL 분석"
    w.clear_marks()
    assert w.findings() == []
