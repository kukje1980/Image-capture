"""질환별 참고 사진: 라이브러리 · 저장소(DB+파일) · 아이콘 줄 · 패널 · 비교 창."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from app import dx_library
from app.models.patient import Patient
from app.services.capture_service import CaptureService
from app.services.reference_service import ReferenceStore
from app.ui import icons
from app.ui.dx_bar import DxBar
from app.ui.dx_compare_dialog import DxCompareDialog
from app.ui.dx_images import load_bgr, load_pixmap
from app.ui.dx_panel import DxPanel

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_library_complete():
    ds = dx_library.diseases()
    assert len(ds) >= 10 and ds[0]["id"] == "normal"
    ids = [d["id"] for d in ds]
    assert len(set(ids)) == len(ids)
    for d in ds:
        for k in ("id", "name", "short", "en", "icon", "summary", "findings", "explain", "compare", "illustrations"):
            assert d.get(k), (d["id"], k)
        assert d["icon"] in icons.names(), d["icon"]                 # 데스크탑 아이콘 존재
        assert len(d["short"]) <= 4
        for ill in d["illustrations"]:
            assert dx_library.illustration_path(ill["file"]), ill["file"]
    assert dx_library.get("cataract")["name"] == "백내장"
    assert dx_library.get("nope") is None
    assert dx_library.illustration_path("../library.json") is None   # 경로 탈출 금지
    assert "실제 사진이 아닙니다" in dx_library.notice()


def test_web_copy_is_identical():
    """웹(web/static/dx)과 데스크탑(assets/dx)은 같은 라이브러리·모식도를 써야 한다 (tools/generate_dx_illustrations.py)."""
    a, b = ROOT / "assets" / "dx", ROOT / "web" / "static" / "dx"
    names = sorted(p.name for p in a.iterdir())
    assert names == sorted(p.name for p in b.iterdir())
    for n in names:
        assert (a / n).read_bytes() == (b / n).read_bytes(), n
    # 웹 스프라이트에도 같은 이름의 아이콘이 있어야 한다
    html = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    for d in json.loads((a / "library.json").read_text(encoding="utf-8"))["diseases"]:
        assert f'id="{d["icon"]}"' in html, d["icon"]


def test_store_add_list_delete(qapp, app_env, tmp_path):
    config, db = app_env
    store = ReferenceStore(db, config)
    items = store.items("cataract")
    assert items and items[0]["kind"] == "ill" and items[0]["path"].endswith("cataract.svg")

    frame = np.zeros((60, 80, 3), np.uint8)
    ref = store.add_frame("cataract", frame, "  사례 1  ")
    assert ref.id and ref.caption == "사례 1" and Path(ref.file_path).is_file()
    assert "_references" in ref.file_path and "cataract" in ref.file_path

    src = tmp_path / "외부사진.png"
    import cv2
    cv2.imencode(".png", frame)[1].tofile(str(src))
    ref2 = store.add_file("cataract", src, "")
    assert ref2.caption is None and Path(ref2.file_path).suffix == ".png"
    with pytest.raises(ValueError):
        store.add_file("cataract", tmp_path / "x.svg", "")
    with pytest.raises(ValueError):
        store.add_frame("nope", frame, "")

    users = [i for i in store.items("cataract") if i["kind"] == "user"]
    assert [u["ref"].id for u in users] == [ref.id, ref2.id]
    assert users[1]["caption"].startswith("참고 사진 ")
    assert store.items("pterygium") == [i for i in store.items("pterygium") if i["kind"] == "ill"]

    store.delete(ref)
    assert not Path(ref.file_path).exists()
    assert [i["ref"].id for i in store.items("cataract") if i["kind"] == "user"] == [ref2.id]
    assert db.references.get(ref.id) is None


def test_images_load(qapp):
    p = dx_library.illustration_path("normal.svg")
    pm = load_pixmap(p, 300)
    assert pm is not None and pm.width() == 300 and pm.height() == 200
    bgr = load_bgr(p, 480)
    assert bgr.shape == (320, 480, 3) and bgr.dtype == np.uint8
    assert bgr[160, 240].tolist() != [0, 0, 0]                     # 동공 주변은 검정이 아님
    assert load_pixmap(str(ROOT / "nope.png")) is None


def test_bar_and_panel(qapp, app_env):
    config, db = app_env
    store = ReferenceStore(db, config)
    bar = DxBar()
    assert set(bar.buttons) == {d["id"] for d in dx_library.diseases()}
    seen = []
    bar.diseaseClicked.connect(seen.append)
    bar.buttons["pterygium"].click()
    assert seen == ["pterygium"]
    bar.set_active("pterygium")
    assert bar.active() == "pterygium" and bar.buttons["pterygium"].isChecked()
    bar.set_active(None)
    assert bar.active() is None

    panel = DxPanel(store)
    assert panel.isHidden()
    chosen = []
    panel.referenceChosen.connect(lambda did, it: chosen.append((did, it["kind"])))
    panel.show_disease("pterygium")
    assert panel.disease == "pterygium" and panel.lbl_name.text() == "익상편"
    assert panel.card_count() == len(store.items("pterygium")) == 1
    store.add_frame("pterygium", np.zeros((30, 40, 3), np.uint8), "사례")
    panel.refresh()
    assert panel.card_count() == 2
    panel.close_panel()
    assert panel.isHidden()


def test_compare_dialog_compose_and_pdf(qapp, app_env, tmp_path):
    config, db = app_env
    store = ReferenceStore(db, config)
    svc = CaptureService(db, config)
    pid = db.patients.insert(Patient(chart_no="C7", name="홍길동", diagnosis="백내장"))
    p = db.patients.get(pid)
    img = np.full((120, 160, 3), 90, np.uint8)
    svc.save_photo(img, p, eye="OD")
    caps = db.captures.list_by_patient(pid)
    live = np.zeros((48, 64, 3), np.uint8)

    dlg = DxCompareDialog(store, svc, config, "cataract", store.items("cataract")[0], p, caps, live)
    assert dlg.pt["kind"] == "capture" and dlg.ref["kind"] == "ill"
    assert "백내장" in dlg.side.text() and "수술" in dlg.side.text()
    comp = dlg.compose()
    assert comp.shape[0] == 900 + 54 + 48 and comp.shape[2] == 3
    assert comp[30, 30].tolist() == [0, 0, 0]                          # 검은 바탕 + 라벨
    assert len(dlg.print_items()) == 2 and "참고 · 백내장 (모식도)" in dlg.print_items()[0][1]
    assert "[환자에게 설명]" in dlg.notes_text()
    pdf = tmp_path / "cmp.pdf"
    assert dlg.export_pdf(str(pdf)) == 1 and pdf.stat().st_size > 1000

    dlg.save_composite = dlg.save_composite        # 실제 저장 (메시지 상자는 offscreen 에서 막히므로 compose 만 확인)
    before = len(db.captures.list_by_patient(pid))
    svc.save_photo(comp, p, eye="OD", note="비교: 백내장")
    assert len(db.captures.list_by_patient(pid)) == before + 1

    # 실시간 화면 선택 · 참고 사진 없음/환자 없음 상태
    dlg.set_patient_item(dlg._live_item())
    assert dlg.pt["kind"] == "live" and dlg.print_items()[1][0].shape == live.shape
    empty = DxCompareDialog(store, svc, config, "cataract", None, None, [], None)
    assert empty.pt is None and not empty.btn_save.isEnabled() and empty.btn_print.isEnabled() is False
