"""웹 서버 극한 상황 테스트 — 동시 업로드 폭주 · 디스크 가득 참 · 악의적 입력 · 로그인 우회 시도 · 손상된 DB.

환자 영상이 사라지거나 덮어써지거나, 다른 환자와 섞이거나, 로그인 없이 새어 나가지 않아야 한다.
"""
from __future__ import annotations

import errno
import hashlib
import importlib
import io
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

WEB = Path(__file__).resolve().parents[1]


def _png(tag: int | str) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + str(tag).encode() * 64


def _patient(client, chart="E001", name="극한", **kw):
    r = client.post("/api/v1/patients", json={"chart_no": chart, "name": name, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _upload(client, pid, data=b"", ext="png", media_type="photo", **form):
    return client.post("/api/v1/captures",
                       files={"file": ("x." + ext, io.BytesIO(data or _png(1)), "application/octet-stream")},
                       data={"patient_id": str(pid), "media_type": media_type, "ext": ext, **form})


def _media_files(root: Path):
    return sorted(p for p in root.rglob("*") if p.is_file())


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SLITLAMP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SLITLAMP_MEDIA_DIR", str(tmp_path / "data" / "media"))
    monkeypatch.setenv("SLITLAMP_DB_PATH", str(tmp_path / "data" / "x.db"))
    monkeypatch.delenv("SLITLAMP_PASSWORD", raising=False)
    monkeypatch.delenv("SLITLAMP_STORAGE", raising=False)
    from app import config as config_mod
    importlib.reload(config_mod)
    from app import main as main_mod
    importlib.reload(main_mod)
    from app.routers import captures as cap_mod
    with TestClient(main_mod.app) as c:
        yield c, config_mod, cap_mod, main_mod
    importlib.reload(config_mod)
    importlib.reload(main_mod)


# ============================================================ 실제 서버(uvicorn) — 동시성·원시 요청

def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture()
def server(tmp_path):
    def start(password="", extra_env=None):
        port = _free_port()
        env = {**os.environ,
               "SLITLAMP_DATA_DIR": str(tmp_path / "srv"), "SLITLAMP_MEDIA_DIR": str(tmp_path / "srv" / "media"),
               "SLITLAMP_DB_PATH": str(tmp_path / "srv" / "s.db"), "SLITLAMP_PASSWORD": password,
               **(extra_env or {})}
        env.pop("SLITLAMP_STORAGE", None)
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port),
                                 "--log-level", "warning"], cwd=str(WEB), env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        base = f"http://127.0.0.1:{port}"
        for _ in range(200):
            try:
                if httpx.get(base + "/health", timeout=0.5).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.05)
        else:
            proc.kill()
            raise RuntimeError(proc.stderr.read().decode(errors="replace"))
        procs.append(proc)
        return base, port, tmp_path / "srv"

    procs: list = []
    yield start
    for p in procs:
        p.kill()
        p.wait(10)


def _raw_get(port, path, cookie=""):
    """정규화하지 않은 경로를 그대로 보낸다 (브라우저/httpx 는 '..' 를 지워버림)."""
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    req = f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n"
    if cookie:
        req += f"Cookie: {cookie}\r\n"
    s.sendall((req + "\r\n").encode("latin-1"))
    data = b""
    while chunk := s.recv(65536):
        data += chunk
    s.close()
    head, _, body = data.partition(b"\r\n\r\n")
    return int(head.split()[1]), body


def test_upload_storm_from_many_clinics_at_once(server):
    """여러 진료실 PC 가 동시에 수백 장을 올려도 한 장도 빠지거나 덮어써지거나 다른 환자에게 붙지 않는다."""
    base, _, data_dir = server()
    with httpx.Client(base_url=base) as c:
        pids = [c.post("/api/v1/patients", json={"chart_no": f"S{i}", "name": f"동시{i}"}).json()["id"]
                for i in range(4)]
    errors, results, lock = [], [], threading.Lock()
    go = threading.Barrier(16)

    def run(k):
        with httpx.Client(base_url=base, timeout=30) as c:
            go.wait()
            for j in range(25):
                tag = f"{k}-{j}"
                pid = pids[(k + j) % 4]
                try:
                    r = c.post("/api/v1/captures", files={"file": ("a.png", _png(tag), "image/png")},
                               data={"patient_id": str(pid), "media_type": "photo", "eye": "OD"})
                    if r.status_code != 201:
                        errors.append((r.status_code, r.text))
                        continue
                    with lock:
                        results.append((tag, pid, r.json()))
                except httpx.HTTPError as e:
                    errors.append(repr(e))

    ts = [threading.Thread(target=run, args=(k,)) for k in range(16)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(120)
    assert not errors, errors[:3]
    assert len(results) == 400
    assert len({r["url"] for _, _, r in results}) == 400, "같은 파일에 덮어씀"
    with httpx.Client(base_url=base) as c:
        listed = {pid: {x["url"] for x in c.get(f"/api/v1/captures?patient_id={pid}").json()} for pid in pids}
        for tag, pid, r in results:
            assert r["patient_id"] == pid and r["url"] in listed[pid]
            got = c.get(r["url"]).content
            assert got == _png(tag), "다른 업로드의 내용으로 바뀜"
    db = sqlite3.connect(str(data_dir / "s.db"))
    try:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT COUNT(*) FROM captures").fetchone()[0] == 400
    finally:
        db.close()


def test_duplicate_chart_race_creates_exactly_one(server):
    """두 PC 가 같은 차트번호로 동시에 신규 환자 등록 — 환자가 둘로 갈라지면 안 된다."""
    base, _, _ = server()
    codes, go = [], threading.Barrier(12)

    def run():
        with httpx.Client(base_url=base) as c:
            go.wait()
            codes.append(c.post("/api/v1/patients", json={"chart_no": "RACE1", "name": "경쟁"}).status_code)

    ts = [threading.Thread(target=run) for _ in range(12)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    assert sorted(codes).count(201) == 1 and len(codes) == 12
    with httpx.Client(base_url=base) as c:
        assert len(c.get("/api/v1/patients?q=RACE1").json()) == 1


@pytest.mark.parametrize("path", [
    "/static/../data/s.db", "/static/..%2f..%2fs.db", "/static/%2e%2e/%2e%2e/srv/s.db",
    "/media/../s.db", "/media/..%2fs.db", "/media/%2e%2e/s.db", "/media//etc/passwd",
    "/login/../api/v1/patients", "/health/../api/v1/patients", "/favicon.ico/../api/v1/patients",
    "/static/../api/v1/patients", "//api/v1/patients", "/api/v1/patients/../patients",
    "/API/v1/patients", "/api/v1/patients?q=%00", "/%2fapi/v1/patients",
])
def test_no_patient_data_without_login_via_path_tricks(server, path):
    """비밀번호를 켜면 어떤 경로 장난으로도 환자 정보·영상·DB 가 새지 않는다."""
    base, port, data_dir = server(password="pw-extreme")
    with httpx.Client(base_url=base) as c:
        assert c.post("/login", data={"password": "pw-extreme", "next": "/"}).status_code in (200, 303)
        ck = c.cookies.get("slitlamp_auth")
        c.cookies.set("slitlamp_auth", ck)
        pid = c.post("/api/v1/patients", json={"chart_no": "LEAK1", "name": "비밀환자"},
                     cookies={"slitlamp_auth": ck}).json()["id"]
        c.post("/api/v1/captures", files={"file": ("a.png", _png("secret"), "image/png")},
               data={"patient_id": str(pid), "media_type": "photo"}, cookies={"slitlamp_auth": ck})
    status, body = _raw_get(port, path)
    assert b"LEAK1" not in body and "비밀환자".encode() not in body and b"SQLite format" not in body
    assert _png("secret") not in body and b"root:" not in body
    assert status in (301, 303, 307, 400, 401, 403, 404), (status, body[:200])


@pytest.mark.parametrize("cookie", ["", "slitlamp_auth=", "slitlamp_auth=0", "slitlamp_auth=" + "a" * 64,
                                    "slitlamp_auth=" + hashlib.sha256(b"").hexdigest(),
                                    "slitlamp_auth=" + "a" * 100000])
def test_forged_cookies_rejected(server, cookie):
    base, port, _ = server(password="pw2")
    status, _ = _raw_get(port, "/api/v1/patients", cookie=cookie)
    assert status in (400, 401, 431)


def test_media_of_logged_in_session_still_needs_login(server):
    base, port, _ = server(password="pw3")
    with httpx.Client(base_url=base) as c:
        c.post("/login", data={"password": "pw3", "next": "/"})
        pid = c.post("/api/v1/patients", json={"chart_no": "M1", "name": "영상"}).json()["id"]
        url = c.post("/api/v1/captures", files={"file": ("a.png", _png("m"), "image/png")},
                     data={"patient_id": str(pid), "media_type": "photo"}).json()["url"]
        assert c.get(url).content == _png("m")
    status, body = _raw_get(port, url)
    assert status == 401 and _png("m") not in body


# ============================================================ 업로드 장애·악의적 입력 (프로세스 내)

def test_disk_full_mid_upload_leaves_no_trace(env, monkeypatch):
    """서버 디스크가 가득 차면 실패를 알리고, 반쯤 쓴 파일이나 DB 기록을 남기지 않는다."""
    c, config, cap_mod, _ = env
    p = _patient(c)
    import builtins
    real_open = builtins.open

    class _Full:
        def __init__(self, f):
            self._f = f

        def write(self, b):
            self._f.write(b[:10])
            raise OSError(errno.ENOSPC, "No space left on device")

        def __getattr__(self, n):
            return getattr(self._f, n)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self._f.close()

    monkeypatch.setattr(cap_mod, "open", lambda f, m="r", *a, **k: _Full(real_open(f, m, *a, **k)), raising=False)
    with TestClient(c.app, raise_server_exceptions=False) as cc:
        r = _upload(cc, p["id"], data=_png(7) * 1000)
    assert r.status_code >= 500 or r.status_code in (409, 413, 507)
    monkeypatch.undo()
    assert c.get(f"/api/v1/captures?patient_id={p['id']}").json() == []
    assert _media_files(config.MEDIA_DIR) == []


def test_db_failure_after_upload_leaves_no_orphan_file(env, monkeypatch):
    c, config, _, main = env
    p = _patient(c)

    def boom(_):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(main.app.state.db, "create_capture", boom)
    r = _upload(c, p["id"])
    assert r.status_code == 409
    assert _media_files(config.MEDIA_DIR) == []


def test_oversize_upload_rejected_without_trace(env, monkeypatch):
    c, config, _, _ = env
    monkeypatch.setattr(config, "MAX_UPLOAD_MB", 1)
    p = _patient(c)
    r = _upload(c, p["id"], data=b"\x00" * (1024 * 1024 + 1))
    assert r.status_code == 413
    assert _media_files(config.MEDIA_DIR) == []
    assert c.get(f"/api/v1/captures?patient_id={p['id']}").json() == []


def test_upload_for_missing_or_deleted_patient(env):
    c, config, _, _ = env
    assert _upload(c, 999999).status_code == 404
    p = _patient(c)
    c.delete(f"/api/v1/patients/{p['id']}")
    assert _upload(c, p["id"]).status_code == 404
    assert _media_files(config.MEDIA_DIR) == []


@pytest.mark.parametrize("ext", ["html", "svg", "htm", "js", "php", "exe", "png/../../x", "../png",
                                 "png\x00.html", "png.html", " html", "PNG.HTML", "", "." * 10])
def test_dangerous_extensions_never_stored(env, ext):
    """같은 주소에서 실행될 수 있는 파일(html·svg·js)은 어떤 모양으로도 저장되지 않는다."""
    c, config, _, _ = env
    p = _patient(c)
    r = _upload(c, p["id"], ext=ext, data=b"<script>alert(1)</script>")
    if r.status_code == 201:
        assert r.json()["url"].rsplit(".", 1)[-1] in ("png", "jpg", "jpeg", "webp")
    else:
        assert r.status_code in (400, 422)
    for f in _media_files(config.MEDIA_DIR):
        assert f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
        assert config.MEDIA_DIR.resolve() in f.resolve().parents


@pytest.mark.parametrize("evil", ["../../../../etc", "..", "/abs", "C:\\Windows", "\\\\srv\\share", "a/../../b",
                                  "con", "x" * 5000, "가" * 3000, "\u202egnp.exe", "😀", "'; DROP TABLE x;--"])
def test_hostile_patient_fields_stay_in_media_dir(env, evil):
    c, config, _, _ = env
    p = _patient(c, chart=evil, name=evil, patient_id=evil)
    r = _upload(c, p["id"])
    assert r.status_code == 201, r.text
    files = _media_files(config.MEDIA_DIR)
    assert len(files) == 1 and config.MEDIA_DIR.resolve() in files[0].resolve().parents
    for part in files[0].relative_to(config.MEDIA_DIR).parts:
        assert len(part.encode()) <= 200 and part not in (".", "..")
    assert c.get(r.json()["url"]).content == _png(1)
    assert c.get(f"/api/v1/patients/{p['id']}").json()["name"] == evil


def test_multipart_filename_is_ignored(env):
    c, config, _, _ = env
    p = _patient(c)
    r = c.post("/api/v1/captures",
               files={"file": ("../../../../../tmp/pwn.png", io.BytesIO(_png(2)), "image/png")},
               data={"patient_id": str(p["id"]), "media_type": "photo"})
    assert r.status_code == 201
    assert "pwn" not in r.json()["url"]
    assert not Path("/tmp/pwn.png").exists() or Path("/tmp/pwn.png").read_bytes() != _png(2)


@pytest.mark.parametrize("form,code", [
    ({"media_type": "exe"}, 400), ({"media_type": ""}, (400, 422)),
    ({"eye": "LEFT"}, 201), ({"eye": "' OR 1=1"}, 201),
    ({"duration_ms": "-5"}, (201, 400, 422)), ({"duration_ms": str(2 ** 70)}, (400, 409, 422)),
    ({"duration_ms": "abc"}, 422), ({"patient_id": "1 OR 1=1"}, 422), ({"patient_id": "-1"}, 404),
])
def test_garbage_form_fields(env, form, code):
    c, config, _, _ = env
    p = _patient(c)
    data = {"patient_id": str(p["id"]), "media_type": "photo", **form}
    r = c.post("/api/v1/captures", files={"file": ("a.png", io.BytesIO(_png(3)), "image/png")}, data=data)
    assert r.status_code in (code if isinstance(code, tuple) else (code,)), r.text
    if r.status_code == 201:
        assert r.json()["eye"] in ("OD", "OS", "OU", "NA")
    else:
        assert _media_files(config.MEDIA_DIR) == [], "거절된 업로드의 파일이 남음"


def test_whitespace_variants_of_chart_number_are_the_same_patient(env):
    """' C001', 'C001 ' 은 화면에서 C001 과 똑같이 보인다 — 다른 환자로 등록되면 영상이 엉뚱한 환자에게 간다."""
    c, _, _, _ = env
    _patient(c, chart="C001", name="홍길동")
    for v in (" C001", "C001 ", "\tC001\n"):
        r = c.post("/api/v1/patients", json={"chart_no": v, "name": "다른사람"})
        assert r.status_code == 400, f"{v!r} 이 별도 환자로 등록됨"
    r = c.post("/api/v1/patients", json={"chart_no": "   ", "name": "빈칸"})
    assert r.status_code == 422
    r = c.post("/api/v1/patients", json={"chart_no": "C002", "name": "   "})
    assert r.status_code == 422


def test_search_wildcards_match_literally(env):
    c, _, _, _ = env
    _patient(c, chart="1_2", name="언더바")
    _patient(c, chart="102", name="일공이")
    _patient(c, chart="50%", name="퍼센트")
    names = [x["name"] for x in c.get("/api/v1/patients", params={"q": "1_2"}).json()]
    assert names == ["언더바"], names
    assert [x["name"] for x in c.get("/api/v1/patients", params={"q": "%"}).json()] == ["퍼센트"]


def test_huge_and_weird_text_fields(env):
    c, _, _, _ = env
    big = "가" * 200_000
    p = _patient(c, chart="BIG", name="이름\x00널", memo=big, symptoms="\u202e\U0001f441" * 1000)
    got = c.get(f"/api/v1/patients/{p['id']}").json()
    assert got["memo"] == big and got["name"] == "이름\x00널"


def test_delete_capture_never_touches_files_outside_media(env, tmp_path):
    """DB 가 조작/손상돼 경로가 미디어 폴더 밖을 가리켜도 삭제가 그 파일을 지우지 않는다."""
    c, config, _, main = env
    p = _patient(c)
    victim = tmp_path / "victim.txt"
    victim.write_text("소중한 파일")
    db = main.app.state.db
    ids = []
    for fp in ("../../victim.txt", str(victim), "../" * 20 + str(victim).lstrip("/")):
        ids.append(db.create_capture({"patient_id": p["id"], "media_type": "photo", "file_path": fp,
                                      "url": "/media/x", "captured_at": "2026-01-01 00:00:00"}))
    for cid in ids:
        assert c.delete(f"/api/v1/captures/{cid}").status_code == 204
    assert victim.read_text() == "소중한 파일"
    ids.append(db.create_capture({"patient_id": p["id"], "media_type": "photo", "file_path": str(victim),
                                  "url": "/media/x", "captured_at": "2026-01-01 00:00:00"}))
    assert c.delete(f"/api/v1/patients/{p['id']}").status_code == 204
    assert victim.read_text() == "소중한 파일"


def test_delete_patient_keeps_other_patients_files(env):
    c, config, _, _ = env
    a = _patient(c, chart="D:A", patient_id="SAME")         # 두 환자 모두 'D_A_SAME' 폴더
    b = _patient(c, chart="D/A", patient_id="SAME")
    ra = _upload(c, a["id"], data=_png("a"))
    rb = _upload(c, b["id"], data=_png("b"))
    assert c.delete(f"/api/v1/patients/{a['id']}").status_code == 204
    assert c.get(rb.json()["url"]).content == _png("b")
    assert c.get(ra.json()["url"]).status_code == 404


def test_corrupt_db_is_never_overwritten(tmp_path, monkeypatch):
    dbp = tmp_path / "data" / "bad.db"
    dbp.parent.mkdir(parents=True)
    junk = os.urandom(4096)
    dbp.write_bytes(junk)
    monkeypatch.setenv("SLITLAMP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SLITLAMP_DB_PATH", str(dbp))
    from app import config as config_mod
    importlib.reload(config_mod)
    from app import main as main_mod
    importlib.reload(main_mod)
    with pytest.raises(sqlite3.DatabaseError):
        with TestClient(main_mod.app):
            pass
    assert dbp.read_bytes() == junk
    importlib.reload(config_mod)
    importlib.reload(main_mod)


_KILL = r"""
import sys
sys.path.insert(0, sys.argv[2])
from app.db.database import Database
db = Database(sys.argv[1]).init()
pid = db.create_patient({"chart_no": "K", "name": "kill"})
print("ready", flush=True)
i = 0
while True:
    db.create_capture({"patient_id": pid, "media_type": "photo", "file_path": f"x/{i}.png",
                       "url": f"/media/x/{i}.png", "captured_at": "2026-01-01 00:00:00"})
    print(i, flush=True)
    i += 1
"""


def test_web_db_survives_hard_kill(tmp_path):
    if sys.platform.startswith("win"):
        pytest.skip("POSIX 전용")
    dbp, script = tmp_path / "k.db", tmp_path / "k.py"
    script.write_text(_KILL, encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(script), str(dbp), str(WEB)], stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "ready"
    last, t0 = -1, time.time()
    while time.time() - t0 < 1.0:
        line = proc.stdout.readline().strip()
        if line.isdigit():
            last = int(line)
    proc.kill()
    proc.wait(10)
    db = sqlite3.connect(str(dbp))
    try:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT COUNT(*) FROM captures").fetchone()[0] >= last + 1
    finally:
        db.close()


def test_login_lockout_blocks_even_correct_password_then_recovers(env, monkeypatch):
    c, config, _, main = env
    monkeypatch.setattr(config, "PASSWORD", "right")
    main._LOGIN_FAILS.clear()
    for _ in range(5):
        c.post("/login", data={"password": "wrong", "next": "/"}, follow_redirects=False)
    r = c.post("/login", data={"password": "right", "next": "/"}, follow_redirects=False)
    assert "error=2" in r.headers["location"] and "slitlamp_auth" not in r.cookies
    now = time.time()
    monkeypatch.setattr(main.time, "time", lambda: now + 61)
    r = c.post("/login", data={"password": "right", "next": "/"}, follow_redirects=False)
    assert r.cookies.get("slitlamp_auth")
