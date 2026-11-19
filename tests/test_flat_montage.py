"""수동 합치기 (v0.10.5): the photos as they are, laid over each other by hand — the one at the back
opaque, the others semi-transparent — moved and turned, then blended into one picture without seams."""
import math
import os

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fundusview import flat_montage as fm, montage as mt  # noqa: E402

R = 150.0                                  # the image circle of the cut-out photos


def _world(side=640, lines=40):
    """A smooth, textured picture with thin dark lines (vessels) to cut photos from."""
    rng = np.random.default_rng(3)
    base = cv2.GaussianBlur(rng.uniform(90, 200, (side, side, 3)).astype(np.float32), (0, 0), 25)
    img = np.clip((base - base.mean()) * 6 + 130, 40, 215)
    for _ in range(lines):
        p, q = rng.integers(0, side, 2), rng.integers(0, side, 2)
        cv2.line(img, tuple(int(v) for v in p), tuple(int(v) for v in q), (60, 20, 20), 2, cv2.LINE_AA)
    return img.astype(np.uint8)


def _cut(world, cx, cy, angle, gain=1.0):
    """A round photo of ``world`` around (cx, cy), the camera turned by ``angle`` degrees."""
    n = int(2 * R) + 20
    c = n / 2.0
    m = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    m[0, 2] += c - cx
    m[1, 2] += c - cy
    rgb = cv2.warpAffine(world, m, (n, n), flags=cv2.INTER_LINEAR)
    yy, xx = np.ogrid[0:n, 0:n]
    inside = (xx - c) ** 2 + (yy - c) ** 2 <= R * R
    rgb = np.clip(rgb.astype(np.float32) * gain, 0, 255).astype(np.uint8) * inside[..., None]
    return np.ascontiguousarray(rgb), (inside * 255).astype(np.uint8), (c, c, R)


def _shots(world, cuts):
    return [mt.Shot.from_photo(*_cut(world, *c), fov_deg=45.0, fov_type="internal", projection="equidistant",
                               image_id=k + 1, label=f"#{k + 1}") for k, c in enumerate(cuts)]


def test_photos_laid_flat_are_blended_without_a_seam():
    world = _world()
    # two photos of the same picture: the second 120 px to the right, turned 20° and 8 % brighter
    shots = _shots(world, [(250, 320, 0.0), (370, 320, 20.0, 1.08)])
    rhos = fm.unit_radii(shots)
    assert rhos == [1.0, 1.0]
    places = [fm.Placement(0.0, 0.0, 0.0), fm.Placement(120 / R, 0.0, -20.0)]     # where they belong
    assert fm.hit(shots[1], rhos[1], places[1], 120 / R, 0.0) and not fm.hit(shots[1], 1.0, places[1], -0.9, 0.0)
    # a point of the plane ↔ the pixel of the turned photo
    u, v = fm.to_photo(shots[1].circle, 1.0, places[1], 120 / R + 0.5, 0.0)
    c = shots[1].circle[0]
    assert (u - c, v - c) == pytest.approx((75 * math.cos(math.radians(20)), -75 * math.sin(math.radians(20))), abs=1e-6)

    fm.match_gains(shots, rhos, places)
    assert shots[1].gain.mean() < shots[0].gain.mean()              # the brighter photo is turned down
    rgb, cover, (x0, y0, k) = fm.render(shots, rhos, places)
    assert k == pytest.approx(R) and rgb.shape[1] == pytest.approx(2 * R + 120, abs=2)
    # the picture is the world there (up to the common brightness): both photos, where each belongs
    wx0, wy0 = int(round(250 + x0 * k)), int(round(320 + y0 * k))
    ref = world[wy0:wy0 + rgb.shape[0], wx0:wx0 + rgb.shape[1]].astype(np.float32)
    got = rgb.astype(np.float32)
    on = cv2.erode(cover, np.ones((9, 9), np.uint8)) > 250
    ratio = got[on].mean() / ref[on].mean()
    assert 0.95 < ratio < 1.2
    # (blurred a little: the turned photo was resampled twice, which softens the edges of its thin lines)
    err = np.abs(cv2.GaussianBlur(got / ratio, (0, 0), 2) - cv2.GaussianBlur(ref, (0, 0), 2))[on]
    assert np.median(err) < 4.0 and np.percentile(err, 95) < 12.0
    # … and no step of brightness where one photo ends over the other (the edge of photo ② at x = 120 − R)
    col = int(round((120 / R - 1.0 - x0) * k))
    row = int(round((0.0 - y0) * k))
    d = got[row - 20:row + 20, col - 6:col + 6].mean(axis=(0, 2)) / ratio - ref[row - 20:row + 20, col - 6:col + 6].mean(axis=(0, 2))
    assert np.ptp(d) < 6.0
    # cut to what is covered
    cut, ccover, (le, to) = fm.crop(rgb, cover)
    assert ccover[0].any() and ccover[:, 0].any() and cut.shape[0] <= rgb.shape[0]


def test_the_start_comes_from_the_photos_on_the_eye():
    world = _world()
    shots = _shots(world, [(250, 320, 0.0), (370, 320, 0.0)])
    places = fm.from_sphere(shots, 0)
    assert (places[0].x, places[0].y, places[0].angle) == pytest.approx((0, 0, 0), abs=1e-6)
    mt.move_on_plane(shots[1], 0.5 * shots[0].tmax, 0.0)             # half a radius to the right on the eye
    mt.roll_about(shots[1], 10.0)
    places = fm.from_sphere(shots, 0)
    assert places[1].x == pytest.approx(0.5, abs=0.01) and abs(places[1].y) < 0.01
    assert places[1].angle == pytest.approx(10.0, abs=0.5)
    sp = fm.spread([1.0, 1.0, 1.0], 1)
    assert (sp[1].x, sp[1].y) == (0.0, 0.0) and math.hypot(sp[0].x, sp[0].y) == pytest.approx(0.9)


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _sources(world):
    from fundusview.ui.montage_dialog import MontageSource

    out = []
    for k, c in enumerate([(250, 320, 0.0), (370, 320, 20.0), (300, 230, -10.0)]):
        rgb, alpha, circle = _cut(world, *c)
        out.append(MontageSource(k + 1, rgb, alpha, circle, 45.0, "internal", "equidistant", label=f"#{k + 1}",
                                 disc=(circle[0] + 30.0, circle[1]), laterality="OD"))
    return out


def test_the_editor_back_photo_opaque_drag_turn_and_save(app, tmp_path):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from fundusview.ui.flat_montage_dialog import FlatMontageDialog

    world = _world(lines=0)                    # (smooth: single screen pixels are compared with the photos)
    saved = []
    dlg = FlatMontageDialog(_sources(world), save_record=lambda res: (saved.append(res), 77)[1])
    try:
        dlg.resize(1300, 860)
        dlg.show()
        app.processEvents()
        c = dlg.canvas
        assert dlg.included() == [0, 1, 2] and c.base == 0 and c.order() == [0, 1, 2] and c.selected == 1
        assert dlg.b_record.isEnabled() and "불투명" in dlg.c_base.toolTip()
        # every photo starts in view, the others half over the one at the back
        for pl in dlg.places:
            x, y = c.to_screen(pl.x, pl.y)
            assert 0 < x < c.width() and 0 < y < c.height()

        # the one at the back is opaque, a photo over it lets it through: where ② alone lies the screen shows
        # ② dimmed over the dark ground, and where only ① lies, ① as it is
        dlg.places[1].x, dlg.places[1].y = 1.2, 0.0
        dlg.places[2].x, dlg.places[2].y = 0.0, 5.0                   # (out of the way)
        dlg._changed()
        c.fit()
        app.processEvents()
        img = c.grab().toImage()

        def px(x, y):
            q = img.pixelColor(*(int(round(v)) for v in c.to_screen(x, y)))
            return np.array([q.red(), q.green(), q.blue()], float)

        def photo(k, x, y):
            u, v = fm.to_photo(dlg.shots[k].circle, dlg.rhos[k], dlg.places[k], x, y)
            return dlg.shots[k].rgb[int(v), int(u)].astype(float)

        assert np.abs(px(-0.6, 0.3) - photo(0, -0.6, 0.3)).max() < 14            # ① alone: as it is
        only2 = photo(1, 1.9, 0.3) * 0.55 + np.array([17, 19, 22]) * 0.45
        assert np.abs(px(1.9, 0.3) - only2).max() < 14                          # ② alone: semi-transparent
        both = photo(1, 0.6, 0.3) * 0.55 + photo(0, 0.6, 0.3) * 0.45
        assert np.abs(px(0.6, 0.3) - both).max() < 14                           # ② over ①: ① shows through
        dlg.s_opacity.setValue(100)
        app.processEvents()
        img = c.grab().toImage()
        assert np.abs(px(0.6, 0.3) - photo(1, 0.6, 0.3)).max() < 14
        dlg.s_opacity.setValue(55)
        # another photo at the back: that one is opaque
        dlg.c_base.setCurrentIndex(1)
        assert c.base == 1 and c.order() == [1, 0, 2] and "맨 뒤" in dlg.lbl_place.text()
        app.processEvents()
        img = c.grab().toImage()
        assert np.abs(px(1.9, 0.3) - photo(1, 1.9, 0.3)).max() < 14
        dlg.c_base.setCurrentIndex(0)

        # drag photo ② by a point of it: it follows the mouse; the others stay
        x, y = c.to_screen(1.9, 0.0)
        start = QPoint(int(x), int(y))
        QTest.mousePress(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        QTest.mouseMove(c, start + QPoint(-60, 30))
        QTest.mouseRelease(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start + QPoint(-60, 30))
        assert c.selected == 1 and dlg.places[1].x == pytest.approx(1.2 - 60 / c.scale, abs=1e-6)
        assert dlg.places[1].y == pytest.approx(30 / c.scale, abs=1e-6) and dlg.places[0].x == 0.0
        # right-drag (or Ctrl+drag) turns it about its centre: a quarter turn of the mouse = 90°
        px_, py_ = c.to_screen(dlg.places[1].x, dlg.places[1].y)
        a = QPoint(int(px_) + 80, int(py_))
        b = QPoint(int(px_), int(py_) - 80)
        QTest.mousePress(c, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, a)
        QTest.mouseMove(c, b)
        QTest.mouseRelease(c, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, b)
        assert dlg.places[1].angle == pytest.approx(90.0, abs=1.5) and "회전 +9" in dlg.lbl_place.text()
        # keys: an arrow = one screen pixel, [ ] = 0.2° (Shift: 1°); the buttons turn too
        was = dlg.places[1].copy()
        QTest.keyClick(c, Qt.Key.Key_Left)
        QTest.keyClick(c, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
        assert dlg.places[1].x == pytest.approx(was.x - 1 / c.scale) and dlg.places[1].y == pytest.approx(was.y + 10 / c.scale)
        QTest.keyClick(c, Qt.Key.Key_BracketLeft)
        assert dlg.places[1].angle == pytest.approx(was.angle + 0.2)
        dlg._roll(-1.0)
        assert dlg.places[1].angle == pytest.approx(was.angle - 0.8)
        # 되돌리기 (Ctrl+Z): step by step back
        for _ in range(4):
            dlg.undo()
        assert (dlg.places[1].x, dlg.places[1].y, dlg.places[1].angle) == pytest.approx((was.x, was.y, was.angle))
        dlg.undo()
        dlg.undo()
        assert (dlg.places[1].x, dlg.places[1].y, dlg.places[1].angle) == pytest.approx((1.2, 0.0, 0.0))
        # the empty ground pans; the wheel zooms; a photo left out is not shown
        QTest.keyClick(c, Qt.Key.Key_Tab)
        assert c.selected == 2
        dlg.list.item(2).setCheckState(Qt.CheckState.Unchecked)
        assert dlg.included() == [0, 1] and c.order() == [0, 1]

        # where they belong: 완성 shows the picture blended, and it is saved from the original photos
        dlg.places[1].x, dlg.places[1].y, dlg.places[1].angle = 120 / R, 0.0, -20.0
        dlg._changed()
        dlg.tabs.setCurrentIndex(1)
        app.processEvents()
        assert dlg.done_view.has_image() and "완성 미리보기" in dlg.status.text()
        path = str(tmp_path / "flat.png")
        dlg.save_file(path)
        out = cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2RGB)
        assert out.shape[1] == pytest.approx(2 * R + 120, abs=3) and out.shape[0] == pytest.approx(2 * R, abs=3)
        ref = world[320 - 150:320 + 150, 250 - 150:250 + 270].astype(np.float32)
        h, w = min(out.shape[0], ref.shape[0]), min(out.shape[1], ref.shape[1])
        mid = (slice(h // 2 - 60, h // 2 + 60), slice(w // 2 - 120, w // 2 + 120))
        assert np.median(np.abs(out[:h, :w].astype(np.float32)[mid] - ref[:h, :w][mid])) < 6.0
        assert "저장했습니다" in dlg.status.text()

        # 환자 기록에 저장: a montage on a square map around the photo at the back, with its arrangement
        dlg.save_to_record()
        res = saved[0]
        assert dlg.saved_id == 77 and res.rgb.shape[0] == res.rgb.shape[1] == res.geom.size
        assert res.image_ids == [1, 2] and res.laterality == "OD" and res.definition["flat"]
        assert res.definition["ref"] == 0 and res.definition["included"] == [0, 1] and len(res.definition["shots"]) == 3
        n = res.geom.size
        assert res.disc == pytest.approx((n / 2 + 30.0, n / 2), abs=1.5)        # ①'s disc: 30 px right of its centre
        assert res.fov_deg == pytest.approx(45.0 * (n / 2) / R, rel=0.02) and res.span[0] > res.span[1] > 40
        d = res.definition
    finally:
        dlg.close()

    # … and that arrangement opens again
    again = FlatMontageDialog(_sources(world), definition=d)
    try:
        assert again.included() == [0, 1] and again.canvas.base == 0
        assert (again.places[1].x, again.places[1].angle) == pytest.approx((120 / R, -20.0))
    finally:
        again.close()


def test_the_montage_editor_opens_it_from_its_own_arrangement(app, monkeypatch):
    from fundusview.ui import flat_montage_dialog as fd
    from fundusview.ui.montage_dialog import MontageDialog

    world = _world()
    opened = []
    monkeypatch.setattr(fd.FlatMontageDialog, "exec", lambda self: opened.append(self) or 0)
    dlg = MontageDialog(_sources(world), auto=False)
    try:
        assert "수동 합치기" in dlg.b_flat.text() and dlg.b_flat.isEnabled()
        mt.spread(dlg.shots, 0)
        mt.roll_about(dlg.shots[1], 15.0)
        dlg.list.item(2).setCheckState(__import__("PySide6.QtCore").QtCore.Qt.CheckState.Unchecked)
        dlg.b_flat.click()
        flat = opened[0]
        assert len(flat.shots) == 2 and flat.canvas.base == 0 and flat.places[0].x == 0.0
        want = fm.from_sphere(dlg.shots[:2], 0)[1]
        assert (flat.places[1].x, flat.places[1].y) == pytest.approx((want.x, want.y)) and abs(want.x) + abs(want.y) > 0.5
        assert flat.places[1].angle == pytest.approx(want.angle)
    finally:
        dlg.close()
    # a montage saved by 수동 합치기 opens there again (다시 편집)
    d = {"version": 1, "flat": True, "ref": 1, "included": [0, 1],
         "shots": [{"image_id": 1, "x": 0.4, "y": 0.1, "angle": 3.0}, {"image_id": 2, "x": 0, "y": 0, "angle": 0},
                   {"image_id": 3, "x": 2, "y": 2, "angle": 0}]}
    dlg = MontageDialog(_sources(world), definition=d)
    try:
        app.processEvents()
        flat = opened[-1]
        assert len(opened) == 2 and flat.canvas.base == 1 and flat.included() == [0, 1]
        assert (flat.places[0].x, flat.places[0].y, flat.places[0].angle) == (0.4, 0.1, 3.0)
    finally:
        dlg.close()
