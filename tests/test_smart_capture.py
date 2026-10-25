"""스마트 캡처 엔진 · 분석 모듈 · Pro 연동 테스트."""
from __future__ import annotations

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from app.capture import analysis
from app.capture.smart_capture import (
    SmartCaptureEngine,
    SmartSettings,
    focus_score,
    peaking_mask,
    quality,
    roi_rect,
)
from app.models.patient import Patient
from app.services.capture_service import CaptureService


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _texture(seed=0, h=360, w=640):
    rng = np.random.default_rng(seed)
    img = (rng.random((h, w, 3)) * 255).astype(np.uint8)
    img = cv2.GaussianBlur(img, (0, 0), 3)
    return cv2.normalize(img, None, 30, 220, cv2.NORM_MINMAX)


def _blur(img, sigma):
    return cv2.GaussianBlur(img, (0, 0), sigma) if sigma > 0.4 else img


# ---------------- 선명도 ----------------
def test_focus_score_prefers_sharp_and_ignores_glare():
    sharp = _texture()
    assert focus_score(sharp) > focus_score(_blur(sharp, 2)) > focus_score(_blur(sharp, 6))
    glare = _blur(sharp, 6)
    glare[100:200, 200:400] = 255                       # 포화 반사광 — 그 경계는 매우 날카롭다
    assert focus_score(glare) < focus_score(_blur(sharp, 2))    # 반사광 경계에 속지 않음
    assert roi_rect(1000, 500, 0.5) == (250, 125, 500, 250)
    assert focus_score(np.zeros((50, 50, 3), np.uint8)) == 0.0  # 계산할 화소가 없으면 0


def test_peaking_mask_marks_edges_not_glare():
    img = _texture(h=200, w=300)
    img[:, :150] = _blur(img, 5)[:, :150]               # 왼쪽 흐림 · 오른쪽 선명
    img[20:60, 200:260] = 255                           # 반사광 블록 (선명한 쪽)
    m = peaking_mask(img, 2)
    assert m.shape == (200, 300)
    assert m[:, 160:].mean() > 5 * max(1.0, m[:, :140].mean())   # 선명한 쪽에 표시가 몰림
    assert not m[17:63, 197:263].any()                  # 반사광과 그 테두리(3px)는 제외


def test_quality_scores_and_advice():
    from app.capture.smart_capture import FrameMetrics
    good = quality(FrameMetrics(0, 500, brightness=120), 95)
    assert good["ok"] and good["focus"] == 95 and good["exposure"] == 100
    bad = quality(FrameMetrics(0, 50, brightness=230, overexposed=0.1, motion=12), 40)
    assert not bad["ok"] and bad["reflection"] < 50 and bad["stability"] < 20
    assert any("초점" in s for s in bad["issues"]) and any("반사" in s for s in bad["issues"])


# ---------------- 엔진: Best Shot · 자동 촬영 ----------------
def _sweep(engine, base, sigmas, fps=30.0, t0=0.0):
    trig, t = [], t0
    for i, s in enumerate(sigmas):
        r = engine.push(_blur(base, s), t)
        t += 1 / fps
        if r.triggered:
            trig.append(i)
    return trig, t


def test_best_shot_picks_sharpest_recent_frame():
    eng = SmartCaptureEngine(SmartSettings(best_window=1.0))
    base = _texture()
    t = 0.0
    for s in [6, 4, 2, 0, 2, 4, 6]:                     # 초점이 들어왔다 나감 (0.23초)
        eng.push(_blur(base, s), t)
        t += 1 / 30
    best, m = eng.best(now=t)
    assert best is not None and np.array_equal(best, base)
    assert eng.buffered() == 7


def test_buffer_is_bounded_by_time_and_memory():
    eng = SmartCaptureEngine(SmartSettings(buffer_seconds=0.5, buffer_max_mb=1))
    base = _texture(h=240, w=320)                      # 230KB/프레임
    for i in range(60):
        eng.push(base, i / 30)
    assert eng.buffered() <= 5                          # 1MB ≈ 4~5 프레임
    eng2 = SmartCaptureEngine(SmartSettings(buffer_seconds=0.5, buffer_max_mb=400))
    for i in range(60):
        eng2.push(base, i / 30)
    assert 14 <= eng2.buffered() <= 16                  # 0.5초 ≈ 15프레임


def test_auto_trigger_fires_once_at_focus_plateau_then_cooldown():
    eng = SmartCaptureEngine(SmartSettings(auto_mode="freeze", cooldown_freeze=4.0))
    base = _texture()
    sigmas = list(np.linspace(8, 0.3, 30)) + [0.3] * 15 + list(np.linspace(0.3, 8, 20))
    trig, t = _sweep(eng, base, sigmas)
    assert len(trig) == 1 and 30 <= trig[0] <= 40      # 최고점 도달 후 안정 구간에서 1회
    # 같은 스윕을 쿨다운 안에 반복 → 안 찍힘, 쿨다운 뒤 새 스윕 → 다시 찍힘
    trig2, t = _sweep(eng, base, sigmas[:45], t0=t)
    assert trig2 == []
    trig3, _ = _sweep(eng, base, sigmas[:45], t0=t + 4.0)
    assert len(trig3) == 1


def test_auto_trigger_rejects_static_scene_blink_and_off_mode():
    base = _texture()
    eng = SmartCaptureEngine(SmartSettings(auto_mode="freeze"))
    trig, _ = _sweep(eng, base, [0.3] * 60)             # 처음부터 선명한 정지 화면 — 스윕 없음
    assert trig == []
    eng = SmartCaptureEngine(SmartSettings(auto_mode="off"))
    trig, _ = _sweep(eng, base, list(np.linspace(8, 0.3, 30)) + [0.3] * 15)
    assert trig == []
    # 깜빡임: 최고점 직전에 밝기 급변 → 0.3초 금지
    eng = SmartCaptureEngine(SmartSettings(auto_mode="save"))
    t = 0.0
    for s in np.linspace(8, 0.3, 30):
        eng.push(_blur(base, s), t)
        t += 1 / 30
    dark = (base * 0.3).astype(np.uint8)
    r = eng.push(dark, t)
    assert r.metrics.blink
    t += 1 / 30
    fired = [eng.push(base, t + i / 30).triggered for i in range(6)]
    assert not any(fired)                               # 금지 구간 안에서는 안 찍힘
    best, m = eng.best(now=t + 6 / 30)
    assert not m.blink                                  # Best Shot 도 깜빡임 프레임은 제외


# ---------------- 분석 ----------------
def test_classify_illumination():
    assert analysis.classify_illumination(_texture()) == "diffuse"
    slit = np.zeros((300, 400, 3), np.uint8)
    slit[:, 180:220] = (200, 210, 220)
    assert analysis.classify_illumination(slit) == "slit"
    cobalt = np.zeros((300, 400, 3), np.uint8)
    cobalt[:] = (150, 30, 10)
    assert analysis.classify_illumination(cobalt) == "cobalt"
    gray = cv2.cvtColor(cv2.cvtColor(_texture(), cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    assert analysis.classify_illumination(gray) == "ir"


def test_fluorescein_area_and_redness():
    img = np.zeros((400, 400, 3), np.uint8)
    img[:] = (120, 20, 10)                              # 코발트블루 배경
    img[100:150, 100:200] = (40, 220, 90)               # 녹색 형광 5000px
    r = analysis.fluorescein_area(img, None, px_per_mm=10.0)
    assert abs(r["area_px"] - 5000) < 400 and abs(r["area_mm2"] - 50) < 4
    assert r["mask"].shape == (400, 400) and r["mask"][120, 150] and not r["mask"][300, 300]
    roi = analysis.fluorescein_area(img, (90, 90, 210, 160))
    assert roi["ratio"] > r["ratio"]                    # ROI 를 좁히면 비율이 커진다
    pale = np.full((300, 300, 3), (180, 180, 190), np.uint8)
    red = pale.copy()
    red[::6] = (40, 40, 190)                            # 혈관 줄무늬
    a, b = analysis.redness_index(pale), analysis.redness_index(red)
    assert b["index"] > a["index"] and b["vessel_pct"] > 10 > a["vessel_pct"]


def test_align_to_recovers_shift_and_rotation():
    base = _texture(h=480, w=640)
    M = cv2.getRotationMatrix2D((320, 240), 3, 1)
    M[0, 2] += 15
    moved = cv2.warpAffine(base, M, (640, 480))
    aligned, ok = analysis.align_to(moved, base)
    assert ok and aligned.shape == base.shape
    c = (slice(80, -80), slice(80, -80))
    err_before = np.abs(moved[c].astype(int) - base[c]).mean()
    err_after = np.abs(aligned[c].astype(int) - base[c]).mean()
    assert err_after < err_before / 3


# ---------------- Pro 연동 ----------------
def _workspace(app_env, n=2):
    from app.ui.pro.pro_workspace import ProWorkspace
    config, db = app_env
    config.save = lambda: None
    svc = CaptureService(db, config)
    pid = db.patients.insert(Patient(chart_no="S1", name="스마트"))
    patient = db.patients.get(pid)
    for k in range(n):
        svc.save_photo(_texture(k), patient, eye="OD")
    ws = ProWorkspace(db, svc, config, get_eye=lambda: "OD")
    ws.resize(1200, 800)
    ws.set_patient(patient)
    return ws, db, patient


def test_pro_live_best_shot_and_quality(qapp, app_env):
    ws, _, _ = _workspace(app_env, n=0)
    ws.set_mode("live")
    base = _texture()
    t = 0
    for s in [6, 3, 0, 3, 6]:                           # 가장 선명한 프레임은 가운데
        ws.set_live_frame(_blur(base, s))
        t += 1
    assert ws.smart.bars["focus"].value() < 80          # 지금은 흐림
    ws.b_capture.setChecked(True)                       # Best Shot(기본) → 선명한 프레임으로 정지
    assert np.array_equal(ws.live_canvas.image(), base)
    cap = ws.save_live()
    assert cap is not None and np.array_equal(ws.live_canvas.image(), base) is not None
    ws.smart.chk_best.setChecked(False)
    ws.set_live_frame(_blur(base, 6))
    ws.b_capture.setChecked(True)
    assert not np.array_equal(ws.live_canvas.image(), base)   # 끄면 현재 프레임
    ws.b_capture.setChecked(False)


def test_pro_auto_freeze_and_auto_save(qapp, app_env, monkeypatch):
    ws, db, patient = _workspace(app_env, n=0)
    ws.set_mode("live")
    ws.smart.c_auto.setCurrentIndex(1)                  # Smart Freeze
    assert ws.engine.s.auto_mode == "freeze" and ws.config.smart_auto_mode == "freeze"
    base = _texture()
    times = iter(i / 30 for i in range(10000))
    monkeypatch.setattr("app.ui.pro.pro_workspace.time.monotonic", lambda: next(times))
    sigmas = list(np.linspace(8, 0.3, 30)) + [0.3] * 15
    for s in sigmas:
        ws.set_live_frame(_blur(base, s))
    assert ws.b_capture.isChecked() and np.array_equal(ws.live_canvas.image(), base)
    assert "자동 정지" in ws.smart.lbl_log.text()
    ws.b_capture.setChecked(False)

    ws.smart.c_auto.setCurrentIndex(2)                  # Auto Save
    for _ in range(90):                                 # 쿨다운 소진
        ws.set_live_frame(_blur(base, 8))
    for s in sigmas:
        ws.set_live_frame(_blur(base, s))
    caps = db.captures.list_by_patient(patient.id)
    assert len(caps) == 1 and caps[0].note == "자동 촬영"
    assert not ws.b_capture.isChecked()


def test_pro_peaking_overlay_not_in_saved_image(qapp, app_env):
    ws, _, _ = _workspace(app_env, n=0)
    ws.set_mode("live")
    ws.smart.chk_peak.setChecked(True)
    img = np.full((200, 300, 3), 80, np.uint8)
    img[:, 150:] = 160
    for _ in range(4):
        ws.set_live_frame(img)
    assert ws.live_canvas.has_overlay()
    ws.b_capture.setChecked(True)
    assert not ws.live_canvas.has_overlay()             # 정지 화면은 원본 그대로
    ws.set_mode("multi")
    assert not ws.live_canvas.has_overlay()


def test_pro_analysis_measure_record_and_compare(qapp, app_env):
    ws, db, _ = _workspace(app_env, n=0)
    config, _ = app_env
    img = np.zeros((400, 400, 3), np.uint8)
    img[:] = (120, 20, 10)
    img[100:150, 100:200] = (40, 220, 90)
    svc = ws.service
    p = ws._patient
    svc.save_photo(img, p, eye="OD")
    svc.save_photo(np.roll(img, 12, axis=1), p, eye="OD")
    ws.reload()
    ws.open_index(0)
    assert "코발트블루" in ws.analysis.lbl_tag.text()
    ws.single_canvas.add_circle(QPointF(80, 80), QPointF(220, 170))
    r = ws.measure_fluorescein()
    assert r is not None and r["ratio"] > 40 and ws.single_canvas.has_overlay()
    rendered = ws.single_canvas.render_to_bgr()
    assert np.array_equal(rendered[300:, 300:], img[300:, 300:])   # 마스크 레이어는 저장본에 없음
    ws.record_measurement()
    note = db.captures.get(ws.captures()[0].id).note
    assert "코발트블루" in note and "형광 염색 면적" in note
    ws.clear_analysis()
    assert not ws.single_canvas.has_overlay()
    assert ws.measure_redness() is not None

    ws.set_mode("multi")
    ws.select_for_compare(0, 1)
    ws.set_mode("compare")
    ws.analysis.s_ghost.setValue(50)
    assert ws.cmp_right.has_overlay()
    assert ws.align_pair()
    ws.set_blink(True)
    assert ws._blink_timer.isActive()
    ws.set_mode("single")
    assert not ws._blink_timer.isActive()
