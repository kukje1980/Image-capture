"""폴더 가져오기 (웹 서버판): 안저 카메라 폴더 → 파일 이름으로 환자 DB 등록 → 원본 삭제."""
from __future__ import annotations

import io
import os
import time
from pathlib import Path

from PIL import Image


def _img(path: Path, fmt="JPEG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (180, 70, 30)).save(buf, fmt)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue())
    t = time.time() - 10
    os.utime(path, (t, t))
    return buf.getvalue()


def _allow_remote(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "IMPORT_REMOTE_EDIT", True)


def test_settings_only_from_server_pc(client, tmp_path):
    st = client.get("/api/v1/import").json()
    assert st["available"] and st["can_edit"] is False          # TestClient 는 다른 PC 로 보임
    r = client.put("/api/v1/import", json={"enabled": True, "dir": str(tmp_path)})
    assert r.status_code == 403


def test_import_run_registers_and_deletes(client, tmp_path, monkeypatch):
    _allow_remote(monkeypatch)
    watch = tmp_path / "fundus"
    data = _img(watch / "12345_홍길동_20261109_143015_R.jpg")
    _img(watch / "12345_홍길동_20261109_143100_L.tif", "TIFF")   # 브라우저용 PNG 로 바뀜
    _img(watch / "IMG_0001.jpg")
    r = client.put("/api/v1/import", json={"enabled": False, "dir": str(watch), "template": ""})
    assert r.status_code == 200 and r.json()["settings"]["dir"] == str(watch)
    r = client.post("/api/v1/import/run").json()
    ok = [i for i in r["items"] if i["ok"]]
    assert len(ok) == 2 and r["seq"] == 2 and r["total_review"] == 1
    pid = ok[0]["patient_id"]
    p = client.get(f"/api/v1/patients/{pid}").json()
    assert p["chart_no"] == "12345" and p["name"] == "홍길동"
    caps = client.get(f"/api/v1/captures?patient_id={pid}&order=asc").json()
    assert [(c["eye"], c["captured_at"]) for c in caps] == [("OD", "2026-11-09 14:30:15"), ("OS", "2026-11-09 14:31:00")]
    assert client.get(caps[0]["url"]).content == data             # 원본 그대로
    assert caps[1]["url"].endswith(".png")
    assert sorted(f.name for f in watch.iterdir()) == ["_확인필요"]   # 등록한 원본은 지움
    assert (watch / "_확인필요" / "IMG_0001.jpg").exists()


def test_preview_and_bad_template(client, tmp_path, monkeypatch):
    r = client.post("/api/v1/import/preview", json={"filename": "20261109143015_12345_OD.jpg",
                                                     "template": "{date}{time}_{id}_{eye}"}).json()
    assert r["ok"] and r["id"] == "12345" and r["time"] == "14:30:15" and r["eye"] == "OD"
    _allow_remote(monkeypatch)
    r = client.put("/api/v1/import", json={"enabled": False, "dir": str(tmp_path), "template": "{nope}"})
    assert r.status_code == 400
    r = client.put("/api/v1/import", json={"enabled": True, "dir": str(tmp_path / "missing")})
    assert r.status_code == 400


def test_import_settings_persist(client, tmp_path, monkeypatch):
    _allow_remote(monkeypatch)
    client.put("/api/v1/import", json={"enabled": True, "dir": str(tmp_path), "template": "{id}_{eye}", "delete": False})
    from app.folder_import import load_settings
    s = load_settings()
    assert s.enabled and s.dir == str(tmp_path) and s.template == "{id}_{eye}" and s.delete is False
