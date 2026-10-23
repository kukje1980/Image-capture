from __future__ import annotations

import io


def _make_patient(client, chart="C001", name="홍길동"):
    r = client.post("/api/v1/patients", json={
        "chart_no": chart, "name": name, "sex": "M",
        "phone": "010-1234-5678", "symptoms": "충혈", "memo": "초진",
    })
    assert r.status_code == 201, r.text
    return r.json()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_index_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "슬릿램프" in r.text


def test_favicon(client):
    r = client.get("/favicon.ico")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(("image/", "application/"))


def test_patient_crud(client):
    p = _make_patient(client)
    pid = p["id"]

    got = client.get(f"/api/v1/patients/{pid}").json()
    assert got["name"] == "홍길동"

    r = client.put(f"/api/v1/patients/{pid}", json={**got, "name": "김철수"})
    assert r.status_code == 200
    assert client.get(f"/api/v1/patients/{pid}").json()["name"] == "김철수"

    lst = client.get("/api/v1/patients?q=김철수").json()
    assert len(lst) == 1

    assert client.delete(f"/api/v1/patients/{pid}").status_code == 204
    assert client.get(f"/api/v1/patients/{pid}").status_code == 404


def test_duplicate_chart_no(client):
    _make_patient(client, chart="DUP")
    r = client.post("/api/v1/patients", json={"chart_no": "DUP", "name": "다른사람"})
    assert r.status_code == 400


def test_capture_with_note(client):
    """4분할 저장이 쓰는 note 필드가 저장·반환되는지."""
    p = _make_patient(client, chart="Q100")
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    r = client.post("/api/v1/captures", files={"file": ("q.png", io.BytesIO(png), "image/png")},
                    data={"patient_id": str(p["id"]), "media_type": "photo", "eye": "OD",
                          "ext": "png", "note": "4분할 합성"})
    assert r.status_code == 201, r.text
    assert r.json()["note"] == "4분할 합성"
    assert client.get(f"/api/v1/captures?patient_id={p['id']}").json()[0]["note"] == "4분할 합성"


def test_capture_upload_and_list(client):
    p = _make_patient(client, chart="C100")
    pid = p["id"]

    # 가짜 PNG 바이트 업로드
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 128
    r = client.post("/api/v1/captures", files={"file": ("shot.png", io.BytesIO(png), "image/png")},
                    data={"patient_id": str(pid), "media_type": "photo", "eye": "OD", "ext": "png"})
    assert r.status_code == 201, r.text
    cap = r.json()
    assert cap["media_type"] == "photo"
    assert cap["eye"] == "OD"
    assert cap["url"].startswith("/media/")

    # 목록 조회
    lst = client.get(f"/api/v1/captures?patient_id={pid}").json()
    assert len(lst) == 1

    # 업로드한 파일이 /media 로 제공되는지
    assert client.get(cap["url"]).status_code == 200

    # 삭제
    assert client.delete(f"/api/v1/captures/{cap['id']}").status_code == 204
    assert client.get(f"/api/v1/captures?patient_id={pid}").json() == []


def test_capture_cascade_on_patient_delete(client):
    p = _make_patient(client, chart="C200")
    pid = p["id"]
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    client.post("/api/v1/captures", files={"file": ("s.png", io.BytesIO(png), "image/png")},
                data={"patient_id": str(pid), "media_type": "photo", "eye": "OS", "ext": "png"})
    assert len(client.get(f"/api/v1/captures?patient_id={pid}").json()) == 1
    client.delete(f"/api/v1/patients/{pid}")
    assert client.get(f"/api/v1/captures?patient_id={pid}").json() == []


def test_patient_diagnosis_doctor(client):
    r = client.post("/api/v1/patients", json={"chart_no": "DX1", "name": "진단", "diagnosis": "백내장",
                                               "doctor": "박원장"})
    assert r.status_code == 201
    p = r.json()
    assert (p["diagnosis"], p["doctor"]) == ("백내장", "박원장")
    r = client.put(f"/api/v1/patients/{p['id']}", json={**p, "diagnosis": "녹내장 의증"})
    assert r.json()["diagnosis"] == "녹내장 의증"


def test_patch_capture_note(client):
    p = _make_patient(client, chart="PN1")
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 16
    cap = client.post("/api/v1/captures", files={"file": ("a.png", io.BytesIO(png), "image/png")},
                      data={"patient_id": str(p["id"]), "media_type": "photo", "ext": "png"}).json()
    r = client.patch(f"/api/v1/captures/{cap['id']}", json={"note": "  경과관찰  "})
    assert r.status_code == 200 and r.json()["note"] == "경과관찰"
    assert client.patch("/api/v1/captures/99999", json={"note": "x"}).status_code == 404


def test_old_web_db_migrated(tmp_path):
    import sqlite3
    from app.db.database import Database
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE patients (id INTEGER PRIMARY KEY AUTOINCREMENT, chart_no TEXT UNIQUE,
            patient_id TEXT, name TEXT NOT NULL, birth_date TEXT, sex TEXT, phone TEXT,
            memo TEXT, symptoms TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
        INSERT INTO patients (chart_no, name) VALUES ('OLD', '기존');
    """)
    con.commit(); con.close()
    db = Database(path).init()
    try:
        p = db.list_patients("기존")[0]
        assert p["diagnosis"] is None
        db.update_patient(p["id"], {**p, "diagnosis": "결막염", "doctor": "이의사"})
        assert db.get_patient(p["id"])["doctor"] == "이의사"
    finally:
        db.close()


def test_capture_rejects_non_media_extension(client):
    """html·svg 같은 확장자는 같은 출처에서 스크립트 실행 위험 → 거부."""
    p = _make_patient(client, chart="X1")
    for bad in ("html", "svg", "js"):
        r = client.post("/api/v1/captures", files={"file": ("x", io.BytesIO(b"<script>1</script>"), "text/html")},
                        data={"patient_id": str(p["id"]), "media_type": "photo", "ext": bad})
        assert r.status_code == 400, bad
    ok = client.post("/api/v1/captures", files={"file": ("v.webm", io.BytesIO(b"\x1aE\xdf\xa3"), "video/webm")},
                     data={"patient_id": str(p["id"]), "media_type": "video", "ext": "webm"})
    assert ok.status_code == 201


def test_delete_patient_removes_media_files(client):
    from app import config
    p = _make_patient(client, chart="DEL1")
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    cap = client.post("/api/v1/captures", files={"file": ("a.png", io.BytesIO(png), "image/png")},
                      data={"patient_id": str(p["id"]), "media_type": "photo", "ext": "png"}).json()
    f = config.MEDIA_DIR / cap["url"].removeprefix("/media/")
    assert f.exists()
    assert client.delete(f"/api/v1/patients/{p['id']}").status_code == 204
    assert not f.exists()
    assert not f.parent.exists()                      # 빈 날짜 폴더도 정리
    assert client.get(cap["url"]).status_code == 404
