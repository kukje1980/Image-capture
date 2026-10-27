"""Explorer 판: 검사(내원) 묶음 · 검색 · 참조 영상(샘플 사진 포함) · 백업/복원 · 겹쳐보기 · Word 보고서 · 카메라 속성 ·
정지영상 · 분할 정지영상 · 영상 목록 세로 배치 · 창 전체 흐름."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from app import brand
from app.capture import camera_props, overlay
from app.capture.sources import SyntheticSource
from app.db.database import Database
from app.models.exam import Exam
from app.models.patient import Patient
from app.services.capture_service import CaptureService
from app.ui import split_menu


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _wait(qapp, cond, timeout=6.0):
    end = time.time() + timeout
    while time.time() < end and not cond():
        qapp.processEvents()
        time.sleep(0.02)
    return cond()


def _img(v=100, h=60, w=80):
    a = np.zeros((h, w, 3), dtype=np.uint8)
    a[:] = (v, v // 2, 255 - v)
    return a


# ---------------- 검사(내원) ----------------
def test_capture_goes_to_today_exam(app_env):
    config, db = app_env
    svc = CaptureService(db, config)
    p = Patient(chart_no="E1", name="검사")
    p.id = db.patients.insert(p)
    a = svc.save_photo(_img(), p, eye="OD")
    b = svc.save_photo(_img(), p, eye="OS")
    assert a.exam_id and a.exam_id == b.exam_id                      # 같은 날 = 같은 검사
    exams = db.exams.list_by_patient(p.id)
    assert len(exams) == 1 and exams[0].n_captures == 2
    eid = db.exams.insert(Exam(patient_id=p.id, exam_date="2020-01-02", title="수술 후 경과"))
    c = svc.save_photo(_img(), p, exam_id=eid)                       # 고른 검사에 저장
    assert c.exam_id == eid
    assert [x.id for x in db.captures.list_by_exam(eid)] == [c.id]
    removed = db.exams.delete(eid)
    assert len(removed) == 1 and db.captures.get(c.id) is None
    assert db.captures.get(a.id) is not None


def test_old_db_captures_are_grouped_into_exams(tmp_path):
    """exam_id 컬럼이 없는 구버전 DB → 컬럼 추가 + 촬영 날짜별 검사로 자동 묶음 (데이터 보존)."""
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE patients (id INTEGER PRIMARY KEY AUTOINCREMENT, chart_no TEXT UNIQUE, patient_id TEXT,
            name TEXT NOT NULL, birth_date TEXT, sex TEXT, phone TEXT, memo TEXT, symptoms TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
        CREATE TABLE captures (id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
            media_type TEXT NOT NULL, file_path TEXT NOT NULL, export_path TEXT, thumbnail_path TEXT,
            captured_at TEXT NOT NULL, eye TEXT, duration_ms INTEGER, note TEXT);
        INSERT INTO patients (chart_no, name) VALUES ('O1', '구환자');
        INSERT INTO captures (patient_id, media_type, file_path, captured_at) VALUES
            (1, 'photo', 'a.png', '2024-05-01 10:00:00'), (1, 'photo', 'b.png', '2024-05-01 11:00:00'),
            (1, 'photo', 'c.png', '2024-06-09 09:00:00');
    """)
    con.commit()
    con.close()
    db = Database(str(path)).init()
    try:
        exams = db.exams.list_by_patient(1)
        assert [(e.exam_date, e.n_captures) for e in exams] == [("2024-06-09", 1), ("2024-05-01", 2)]
        assert all(c.exam_id for c in db.captures.list_by_patient(1))
    finally:
        db.close()


def test_search_by_diagnosis_and_history(app_env):
    _, db = app_env
    a = db.patients.insert(Patient(chart_no="S1", name="가나", diagnosis="백내장"))
    b = db.patients.insert(Patient(chart_no="S2", name="다라", symptoms="충혈 · 이물감"))
    c = db.patients.insert(Patient(chart_no="S3", name="마바"))
    db.exams.insert(Exam(patient_id=c, exam_date="2026-01-01", diagnosis="점상각막염", memo="CL 착용"))
    ids = lambda q, f: {p.id for p in db.patients.search_by(q, f)}  # noqa: E731
    assert ids("백내장", "diagnosis") == {a}
    assert ids("각막염", "diagnosis") == {c}                          # 검사 소견도 진단명 검색에 포함
    assert ids("이물감", "history") == {b}
    assert ids("CL", "history") == {c}
    assert ids("S2", "chart") == {b}
    assert ids("마바", "name") == {c}
    assert ids("각막염", "all") == {c}
    assert len(db.patients.search_by("", "all")) == 3


# ---------------- 참조 영상 · 백업/복원 ----------------
def test_reference_library_copy(app_env):
    config, db = app_env
    svc = CaptureService(db, config)
    p = Patient(chart_no="R1", name="참조")
    p.id = db.patients.insert(p)
    cap = svc.save_photo(_img(77), p)
    ref = svc.add_reference(cap, "수정체 · 백내장", "핵경화", "확산 조명")
    assert Path(ref.file_path).is_file() and ref.file_path != cap.file_path
    assert db.references.categories() == ["수정체 · 백내장"]
    assert [r.id for r in db.references.list(q="확산")] == [ref.id]
    db.captures.delete(cap.id)                                       # 원본을 지워도 참조는 남는다
    assert db.references.get(ref.id) is not None
    assert db.references.delete(ref.id)["file_path"] == ref.file_path


def test_backup_and_restore(app_env, tmp_path):
    _, db = app_env
    db.patients.insert(Patient(chart_no="B1", name="백업 전"))
    out = db.backup_to(tmp_path / "bk" / "backup.db")
    assert out.is_file()
    db.patients.insert(Patient(chart_no="B2", name="백업 후"))
    assert len(db.patients.list_all()) == 2
    db.restore_from(out)
    assert [p.chart_no for p in db.patients.list_all()] == ["B1"]
    bad = tmp_path / "bad.db"
    sqlite3.connect(bad).close()
    with pytest.raises(ValueError):
        db.restore_from(bad)


# ---------------- 겹쳐보기 ----------------
def test_overlay_modes():
    a, b = _img(10, 40, 40), _img(200, 20, 20)                       # 크기가 달라도 맞춰 합성
    assert np.array_equal(overlay.compose(a, b, "blend", 0.0), a)
    top = overlay.compose(a, b, "blend", 1.0)
    assert top.shape == a.shape and np.array_equal(top, overlay.fit_to(b, (40, 40)))
    assert overlay.compose(a, a, "diff").max() == 0
    assert overlay.compose(a, b, "diff").max() == 255                 # 차이는 끝까지 늘려 보이게
    sp = overlay.compose(a, b, "split", 0.5)
    assert np.array_equal(sp[:, :10], a[:, :10]) and np.array_equal(sp[:, 30:], top[:, 30:])
    ch = overlay.compose(a, b, "checker", cell=10)
    assert np.array_equal(ch[0, 0], a[0, 0]) and np.array_equal(ch[0, 15], top[0, 15])
    s = overlay.shift(np.arange(16, dtype=np.uint8).reshape(4, 4, 1), 1, 0)
    assert s[0, 0, 0] == 0 and s[0, 1, 0] == 0 and s[0, 3, 0] == 2


# ---------------- Word 보고서 ----------------
def test_docx_report(tmp_path):
    from docx import Document

    from app.services.report_docx import build_docx
    items = [(_img(i * 40), f"영상 {i}") for i in range(5)]
    p = Patient(name="홍길동", chart_no="W1", sex="M", diagnosis="백내장", doctor="김의사")
    e = Exam(exam_date="2026-10-26", title="세극등 검사", diagnosis="핵경화 2+")
    for per in (1, 2, 4):
        path = tmp_path / f"r{per}.docx"
        assert build_docx(str(path), p, items, exam=e, findings="소견 1\n소견 2", per_page=per) == 5
        doc = Document(str(path))
        assert len(doc.inline_shapes) == 5
        text = "\n".join(c.text for t in doc.tables for row in t.rows for c in row.cells)
        assert "홍길동" in text and "핵경화 2+" in text and "소견 2" in text
    assert build_docx(str(tmp_path / "none.docx"), p, []) == 0


# ---------------- 카메라 속성 ----------------
def test_camera_props_sanitize_and_synthetic():
    assert camera_props.sanitize({"gain": 500, "auto_wb": True, "bogus": 1, "exposure": "x"}) == \
        {"gain": 100.0, "auto_wb": 1.0}
    src = SyntheticSource(64, 48, 120)
    src.open()
    base = src.read()[1].astype(int).mean()
    assert src.set_property("brightness", 60) and not src.set_property("wb_temperature", 4000)
    assert src.read()[1].astype(int).mean() > base + 20
    assert src.get_property("brightness") == 60.0


def test_camera_controller_applies_property(qapp, app_env):
    from app.capture.camera_controller import CameraController
    config, _ = app_env
    config.source_mode = "synthetic"
    config.capture_width, config.capture_height = 160, 120
    cam = CameraController(config)
    got = []
    cam.property_set.connect(lambda k, ok, v: got.append((k, ok, v)))
    cam.start()
    try:
        assert _wait(qapp, lambda: cam.last_frame is not None)
        cam.set_property("gain", 30)
        assert _wait(qapp, lambda: ("gain", True, 30.0) in got)
        assert config.camera_props["gain"] == 30.0                     # 다음 실행에도 쓰도록 기억
        cam.set_property("sharpness", 10)                              # 합성 소스는 미지원
        assert _wait(qapp, lambda: any(k == "sharpness" and not ok for k, ok, _ in got))
    finally:
        cam.stop()


# ---------------- 판 / 빌드 파일 ----------------
def test_explorer_brand_and_build_files(monkeypatch):
    monkeypatch.delenv(brand.ENV_KEY, raising=False)
    b = brand.select("explorer")
    try:
        assert brand.layout() == "explorer" and brand.asset(b["icon"])
    finally:
        brand.select("default")
    assert brand.layout() == "standard"
    root = Path(__file__).resolve().parents[1]
    iss = (root / "installer" / "explorer.iss").read_text(encoding="utf-8-sig")
    assert "SlitLampExplorer.exe" in iss and "brand\\explorer\\app.ico" in iss
    ids = {f: (root / "installer" / f).read_text(encoding="utf-8-sig").split("AppId=")[1].split("\n")[0]
           for f in ("slitlamp.iss", "keeler.iss", "explorer.iss", "keeler_explorer.iss", "agent.iss")}
    assert len(set(ids.values())) == 5                               # 모든 판을 나란히 설치 가능
    assert "brand_explorer.py" in (root / "build.spec").read_text(encoding="utf-8")
    assert (root / "tools" / "rthooks" / "brand_explorer.py").is_file()
    for f in ("app.ico", "app.icns", "app.png"):
        assert (root / "assets" / "brand" / "explorer" / f).is_file(), f


# ---------------- 창 전체 흐름 ----------------
@pytest.fixture()
def win(qapp, app_env, monkeypatch):
    config, db = app_env
    config.source_mode = "synthetic"
    config.capture_width, config.capture_height = 320, 240
    config.save = lambda: None
    db.patients.insert(Patient(chart_no="X1", name="탐색기", diagnosis="백내장", doctor="박원장"))
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Ok)
    from app.ui.explorer.explorer_window import ExplorerWindow
    w = ExplorerWindow(config, db)
    w.show()
    assert _wait(qapp, lambda: w.camera.last_frame is not None)
    yield w
    w.close()


def test_window_capture_and_tools(qapp, win, tmp_path):
    w = win
    assert w.patient is not None and w.exam is None
    w.set_eye("OD")
    a = w.capture()
    w.set_eye("OS")
    b = w.capture()
    assert a.eye == "OD" and b.eye == "OS" and a.exam_id == b.exam_id
    assert w.exam is not None and w.exam.id == a.exam_id                 # 새 검사가 트리에서 선택됨
    assert w.thumbs.count() == 2 and w.exam.n_captures == 2
    assert "저장 대상" in w.lbl_target.text()

    w.act_freeze.trigger()                                               # 정지영상 → 그 장면을 캡처
    frozen = w._freeze
    assert frozen is not None and w.btn_freeze.text() == "라이브"
    c = w.capture()
    w.act_freeze.trigger()                                               # 다시 누르면 라이브
    assert not w._paused and w.btn_freeze.text() == "정지영상"
    from app.ui.pro.pro_workspace import load_bgr
    assert np.array_equal(load_bgr(c.file_path), frozen)

    w.thumbs.select_ids([a.id, b.id])
    assert w.act_overlay.isEnabled() and w.act_compare.isEnabled()
    ov = w.open_overlay()
    ov.c_mode.setCurrentIndex(1)
    ov.sp_dx.setValue(5)
    n0 = len(w.db.captures.list_by_exam(a.exam_id))
    ov._save()
    assert len(w.db.captures.list_by_exam(a.exam_id)) == n0 + 1          # 겹친 영상 저장
    ov.close()
    cp = w.open_compare()
    assert len(cp.canvases) == 2
    cp.c_channel.setCurrentIndex(1)
    assert all(cv.adjust().channel == "green" for cv in cp.canvases)
    cp.close()

    w.thumbs.select_ids([a.id])
    ref = w.add_reference(("각막", "대표", ""))
    assert ref is not None and w.db.references.categories() == ["각막"]
    lib = w.open_reference_library()
    assert len(lib.refs()) == 1 and lib.b_compare.isEnabled()
    lib.compare()
    assert len(lib._compare_dlg.canvases) == 2
    lib.close()

    rp = w.open_report()
    assert rp.export_docx(str(tmp_path / "r.docx")) == 1                 # 선택한 1장
    assert rp.export_pdf(str(tmp_path / "r.pdf")) == 1
    assert (tmp_path / "r.pdf").stat().st_size > 0
    rp.close()

    w.thumbs.list.clearSelection()
    show = w.start_slideshow()
    total = len(show._items)
    assert total == len([x for x in w.thumbs.captures() if x.media_type == "photo"])
    i0 = show.index()
    show.next()
    assert show.index() == (i0 + 1) % total
    show.toggle_pause()
    assert show.paused
    show.close()


def test_window_import_export_delete_backup(qapp, win, tmp_path):
    w = win
    import cv2
    src = tmp_path / "외부.png"
    cv2.imencode(".png", _img(150, 50, 70))[1].tofile(str(src))     # 한글 경로 (Windows 에서 imwrite 불가)
    assert w.import_images([str(src), str(tmp_path / "없음.png")]) == 1
    assert w.thumbs.count() == 1 and w.thumbs.captures()[0].note == "가져옴"
    w.thumbs.list.selectAll()
    out = tmp_path / "out"
    out.mkdir()
    assert w.export_selected(str(out)) == 1 and len(list(out.iterdir())) == 1
    bk = w.backup_db(str(tmp_path / "bk.db"))
    cap = w.thumbs.captures()[0]
    assert w.delete_selected(confirm=False) == 1
    assert w.thumbs.count() == 0 and not Path(cap.file_path).exists()
    assert w.restore_db(str(bk), confirm=False)
    assert w.db.captures.get(cap.id) is not None                          # 기록 복원

    w.tree.search.setText("없는환자")
    assert w.patient is None and not w.act_capture.isEnabled()
    w.tree.search.setText("")
    assert w.patient is not None


def test_window_record_and_exam_menu(qapp, win):
    w = win
    w.act_record.setChecked(True)
    assert w.camera.recording
    t0 = time.time()
    _wait(qapp, lambda: time.time() - t0 > 1.2, timeout=3)
    w.act_record.setChecked(False)
    assert not w.camera.recording
    vids = [c for c in w.thumbs.captures() if c.media_type == "video"]
    assert len(vids) == 1 and vids[0].duration_ms > 0 and vids[0].exam_id == w.exam.id
    w.thumbs.set_filter("video")
    assert w.thumbs.count() == 1
    w.thumbs.set_filter("all")
    w.delete_exam(confirm=False)
    assert w.exam is None and w.db.exams.list_by_patient(w.patient.id) == []



# ---------------- 샘플 사진 → 참조 영상 ----------------
def _sample_folder(root: Path) -> Path:
    import hashlib
    import json

    import cv2
    files = {
        "01_건성안/리사민그린_1.jpg": {"description": "중증 건성각결막염; 리사민그린 염색.",
                                    "author": "EyeRounds", "license": "CC BY-NC-ND 3.0",
                                    "source": "https://example.org/kcs"},
        "01_건성안/리사민그린_2.jpg": {"title": "건성안 2"},
        "04_백내장/핵백내장_1.jpg": {"title": "핵경화 백내장"},
    }
    meta = []
    for i, (rel, info) in enumerate(files.items()):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        data = cv2.imencode(".jpg", _img(40 + i * 60, 90, 120))[1].tobytes()
        path.write_bytes(data)
        meta.append({"file": rel, "sha256": hashlib.sha256(data).hexdigest(), **info})
    (root / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return root


def test_sample_photos_as_references(app_env, tmp_path):
    from app.services import sample_import
    config, db = app_env
    assert sample_import.sample_references(db) == []
    sample_import.import_samples(db, config, _sample_folder(tmp_path / "samples"))
    db.patients.insert(Patient(chart_no="N1", name="일반 환자"))              # 샘플이 아닌 환자는 제외
    assert sample_import.sample_categories(db) == [("건성안", 2), ("백내장", 1)]
    refs = sample_import.sample_references(db)
    assert len(refs) == 3 and all(r.is_sample and Path(r.file_path).is_file() for r in refs)
    first = refs[0]
    assert first.category == "건성안" and first.title.startswith("중증 건성각결막염")
    assert "CC BY-NC-ND 3.0" in first.description and "https://example.org/kcs" in first.description
    assert [r.title for r in sample_import.sample_references(db, category="백내장")] == ["핵경화 백내장 (저해상도 120×90)"]
    assert len(sample_import.sample_references(db, q="리사민")) == 1
    assert db.references.list() == []                                    # 복사하지 않고 원본을 가리킴


def test_reference_library_shows_samples(qapp, app_env, tmp_path, monkeypatch):
    from app.services import sample_import
    from app.ui.explorer.reference_library import LIBRARY, SAMPLE, ReferenceLibraryDialog
    config, db = app_env
    svc = CaptureService(db, config)
    p = Patient(chart_no="L1", name="라이브러리")
    p.id = db.patients.insert(p)
    svc.add_reference(svc.save_photo(_img(90), p), "각막", "등록한 참조")
    sample_import.import_samples(db, config, _sample_folder(tmp_path / "samples"))

    dlg = ReferenceLibraryDialog(db, current=(_img(10), "현재 환자"))
    texts = [dlg.cats.item(i).text() for i in range(dlg.cats.count())]
    assert texts[0].startswith("전체  (4)") and "샘플 사진" in texts and any(t.startswith("건성안") for t in texts)
    assert len(dlg.refs()) == 4                                            # 전체 = 등록 1 + 샘플 3
    assert dlg.select_category(SAMPLE, "건성안") and len(dlg.refs()) == 2
    r = dlg.current_ref()
    assert r.is_sample and not dlg.b_delete.isEnabled() and not dlg.b_edit.isEnabled()
    assert "CC BY-NC-ND 3.0" in dlg.info.text()
    cmp = dlg.compare()
    assert len(cmp.canvases) == 2 and cmp.canvases[1]._caption.startswith("샘플 · 건성안")
    dlg.delete_current(confirm=False)                                      # 샘플은 지워지지 않음
    assert len(sample_import.sample_references(db)) == 3
    assert dlg.select_category(LIBRARY, "각막") and dlg.b_delete.isEnabled()
    dlg.search.setText("핵경화")
    assert dlg.select_category(SAMPLE, "백내장") and [x.title for x in dlg.refs()] == ["핵경화 백내장 (저해상도 120×90)"]
    assert not dlg.b_samples.isVisible() and dlg.b_samples.isHidden()      # 가져오기 콜백 없으면 버튼 숨김
    dlg.close()


def test_window_imports_samples_into_library(qapp, win, tmp_path):
    w = win
    assert w.import_samples(folder=str(_sample_folder(tmp_path / "s")))
    names = [w.tree.tree.topLevelItem(i).text(0) for i in range(w.tree.tree.topLevelItemCount())]
    assert any(n.startswith("샘플 · 건성안") for n in names)
    lib = w.open_reference_library()
    assert len(lib.refs()) == 3 and not lib.b_samples.isHidden()
    lib.close()


# ---------------- 분할 정지영상 ----------------
def test_window_split_freeze(qapp, win):
    w = win
    w.start_split(4)
    assert w._split and w.view.currentIndex() == 2 and w.act_split.isChecked()
    assert _wait(qapp, lambda: w.quad.has_any())
    for i in range(4):
        w.set_eye("OD" if i % 2 == 0 else "OS")
        w.freeze()
        if i < 3:
            assert _wait(qapp, lambda: w.quad.has_any() and w.quad._frames[w.quad._active] is not None)
    assert w.quad.is_full() and w.btn_freeze.text() == "처음부터"
    saved = w.save_split()
    assert len(saved) == 5                                                 # 칸 4장 + 합성 1장
    assert [c.note for c in saved] == ["4분할"] * 4 + ["4분할 합성"]
    assert [c.eye for c in saved[:4]] == ["OD", "OS", "OD", "OS"]
    assert len({c.exam_id for c in saved}) == 1 and w.thumbs.count() == 5
    w.freeze()                                                             # 다 찬 뒤 누르면 처음부터
    assert not w.quad.is_full() and not w.quad.has_any() and w.btn_freeze.text() == "정지영상"
    w._on_split_cell_clicked(2)
    assert w.quad._active == 2
    w.stop_split()
    assert not w._split and w.view.currentIndex() == 0 and not w.act_split.isChecked()

    # 처음 한 번: 메뉴를 닫으면 켜지 않음
    assert not w.config.split_count_saved
    w._exec_menu = lambda menu, pos: None
    w.act_split.setChecked(True)
    qapp.processEvents()
    assert not w._split and not w.act_split.isChecked() and not w.btn_split.isChecked()

    # 메뉴에서 칸 수 고르기 → 고른 칸 수가 저장되고, 그다음부터는 묻지 않고 그 칸 수로 바로
    asked = []

    def pick(text):
        def run(menu, pos):
            asked.append(text)
            return next(a for a in menu.actions() if a.text() == text)
        return run
    w._exec_menu = pick("6분할")
    w.act_split.setChecked(True)
    assert w._split and w.quad.count() == 6 and w.config.split_count == 6 and w.config.split_count_saved
    w.act_split.setChecked(False)
    w._exec_menu = lambda menu, pos: pytest.fail("저장한 뒤에는 묻지 않아야 함")
    w.btn_split.click()
    assert w._split and w.quad.count() == 6 and asked == ["6분할"]
    assert "저장한 6분할" in w.btn_split.toolTip()

    # 칸 수 바꾸기 (오른쪽 클릭 · 카메라 메뉴): 분할 중이면 새 칸 수로 다시 시작
    w._exec_menu = pick("2분할")
    w.act_split_count.trigger()
    assert w._split and w.quad.count() == 2 and w.config.split_count == 2
    w.stop_split()
    # '누를 때마다 칸 수 묻기' 를 다시 켜면 다음부터 또 묻는다
    w._exec_menu = pick(split_menu.ASK_TEXT)
    w.change_split_count()
    assert not w.config.split_count_saved and not w._split
    w._exec_menu = pick("8분할")
    w.act_split.setChecked(True)
    assert w._split and w.quad.count() == 8 and asked[-1] == "8분할"


# ---------------- 영상 목록 세로 배치 ----------------
def test_window_thumbs_vertical(qapp, win):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidget
    w = win
    assert w.dockWidgetArea(w.thumb_dock) == Qt.DockWidgetArea.BottomDockWidgetArea
    w.act_thumbs_vertical.trigger()
    assert w.dockWidgetArea(w.thumb_dock) == Qt.DockWidgetArea.RightDockWidgetArea
    assert w.thumbs.is_vertical() and w.thumbs.list.flow() == QListWidget.Flow.TopToBottom
    assert w.config.explorer_thumbs_vertical is True
    w._on_thumb_dock_moved(Qt.DockWidgetArea.BottomDockWidgetArea)        # 끌어서 아래로 옮긴 경우
    assert not w.thumbs.is_vertical() and not w.act_thumbs_vertical.isChecked()
    assert w.config.explorer_thumbs_vertical is False



# ---------------- Keeler Explorer 판 ----------------
def test_keeler_explorer_brand_and_build_files(monkeypatch):
    monkeypatch.delenv(brand.ENV_KEY, raising=False)
    try:
        b = brand.select("Keeler-Explorer")                            # 대소문자·'-' 섞여도 같은 판
        assert b["key"] == "keeler_explorer" and brand.layout() == "explorer"
        assert "Keeler" in b["app_name"] and "Explorer" in b["window_title"]
        assert b["report_title"] == brand.BRANDS["keeler"]["report_title"]
        for k in ("logo", "logo_dark", "icon"):
            assert brand.asset(b[k]), k
        from app.ui import theme
        assert theme.palette("dark")["accent"] == "#6cbce8"             # Keeler 색
        assert brand.key_from(["app", "--brand", "keeler explorer"]) == "keeler_explorer"
    finally:
        brand.select("default")
    root = Path(__file__).resolve().parents[1]
    iss = (root / "installer" / "keeler_explorer.iss").read_text(encoding="utf-8-sig")
    assert "KeelerExplorer.exe" in iss and "brand\\keeler\\app.ico" in iss and "SlitLampExplorer" not in iss
    for spec in ("build.spec", "build_mac.spec"):
        text = (root / spec).read_text(encoding="utf-8")
        assert "KeelerExplorer" in text and "brand_keeler_explorer.py" in text
    assert (root / "tools" / "rthooks" / "brand_keeler_explorer.py").is_file()
    assert "keeler_explorer" in (root / "build_mac.sh").read_text(encoding="utf-8")
    assert "keeler_explorer" in (root / "build_installer.bat").read_text(encoding="utf-8")
    for wf in ("build-windows.yml", "build-mac.yml"):
        assert "KeelerExplorer" in (root / ".github" / "workflows" / wf).read_text(encoding="utf-8")


def test_keeler_explorer_window_shows_logo(qapp, app_env, monkeypatch):
    config, db = app_env
    config.source_mode = "synthetic"
    config.capture_width, config.capture_height = 160, 120
    config.save = lambda: None
    monkeypatch.setenv(brand.ENV_KEY, "keeler_explorer")
    from app.ui.explorer.explorer_window import ExplorerWindow
    w = ExplorerWindow(config, db)
    try:
        assert w.windowTitle() == "Keeler 슬릿램프 영상 시스템 Explorer"
        assert w.brand_logo is not None and not w.brand_logo.pixmap().isNull()
        dark = w.brand_logo.pixmap().toImage()
        w.toggle_theme()                                                  # 밝은 테마여도 머리는 Keeler 네이비
        assert w.brand_logo.pixmap().toImage() == dark                    # 네이비 헤더용 흰 글자 로고 그대로
        from app.ui.theme import build_qss
        for mode in ("dark", "light"):
            qss = build_qss(mode)
            assert "QToolBar#ExplorerTools { background: #052133;" in qss    # 홈페이지 헤더 네이비
            assert "rgba(237, 111, 30, 0.85)" in qss                          # 셔터 링 = 로고 마크 주황
    finally:
        w.close()
        brand.select("default")
