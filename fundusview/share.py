"""Sharing one library between several computers (설정 → 공유).

One computer — the **server** — opens the database and stores the photos, as before. It also
answers the other computers over the local network (HTTP):

* the same viewer on another PC, set to **서버에 연결** (:class:`RemoteDatabase` in place of
  :class:`~fundusview.db.Database`): every view and tool works, the photos are fetched once and
  kept in a local cache, and whatever is edited (환자 정보, 메모, 황반·유두 표시, 몽타주 …) is
  stored on the server;
* a web browser (``http://<server>:<port>/``): the patient list and the photos, with the notes.

Only the server ever opens the SQLite file, so the database cannot be damaged by two computers
writing to a shared folder at once (SQLite on a network share is not safe, WAL even less).

The connection is plain HTTP guarded by one shared password (접속 암호): meant for the network
inside the clinic, not for the internet.
"""
from __future__ import annotations

import hashlib
import hmac
import http.client
import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, quote, unquote, urlsplit

from . import APP_NAME, __version__
from .config import Settings, WatchFolder, config_dir
from .importer import ImportResult
from .models import ExtractedMeta, PatientAssign
from .share_page import WEB_PAGE

DEFAULT_PORT = 8765
MODE_OFF, MODE_SERVER, MODE_CLIENT = "off", "server", "client"

# Database methods another computer may call, and which of them change something.
READS = ("get_patient", "find_patient", "list_patients", "count_patients", "get_image", "image_by_sha",
         "images_for_patient", "count_unassigned", "unassigned_summary", "recent_logs", "patients_named",
         "patients_examined")
WRITES = ("upsert_patient", "update_patient", "delete_patient", "merge_patients", "update_image",
          "delete_image", "log")
# Where the files are is the server's own business: another computer never sets a path.
PATH_COLUMNS = ("file_path", "display_path", "thumb_path", "original_path", "sha256")
FILE_KINDS = {"file": "file_path", "display": "display_path", "thumb": "thumb_path"}
CACHE_LIMIT = 4 * 1024 ** 3      # the client's photo cache: the oldest files go beyond this


def token_for(key: str) -> str:
    """What is sent in place of the password (a header must be ASCII; the password may be Korean)."""
    return hashlib.sha256(("fundusview:" + (key or "")).encode("utf-8")).hexdigest()


def new_key() -> str:
    """A password for a server that was given none: six digits, easy to read out."""
    return f"{secrets.randbelow(900000) + 100000}"


def lan_address() -> str:
    """This computer's address on the local network (what the other computers type in)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))        # nothing is sent: it only picks the outgoing interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def normalize_url(text: str) -> str:
    """``192.168.0.10`` / ``192.168.0.10:8765`` / ``http://…/`` → ``http://192.168.0.10:8765``."""
    text = (text or "").strip().rstrip("/")
    if not text:
        return ""
    if "://" not in text:
        text = "http://" + text
    parts = urlsplit(text)
    host = parts.hostname or ""
    if not host:
        return ""
    return f"http://{host}:{parts.port or DEFAULT_PORT}"


def _row(row) -> dict | None:
    return None if row is None else {k: row[k] for k in row.keys()}


def _jsonable(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if hasattr(value, "keys"):                   # sqlite3.Row
        return _row(value)
    if hasattr(value, "item"):                   # numpy scalar
        return value.item()
    return str(value)


# =========================================================================================
# server
# =========================================================================================
class ShareServer:
    """Answers the other computers. ``on_change`` is called (on a server thread) after another
    computer changed something, so the server's own window can show it."""

    def __init__(self, db, settings: Settings, importer=None, *, port: int | None = None,
                 key: str | None = None, on_change: Callable[[], None] | None = None):
        from .importer import Importer

        self.db = db
        self.settings = settings
        self.importer = importer or Importer(db, settings)
        self.key = settings.share_key if key is None else key
        self.on_change = on_change or (lambda: None)
        self.boot = uuid.uuid4().hex[:8]
        self._import_lock = threading.Lock()
        server = self

        class Handler(_Handler):
            share = server

        self.httpd = ThreadingHTTPServer(("0.0.0.0", settings.share_port if port is None else port), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> str:
        return f"http://{lan_address()}:{self.port}"

    def start(self) -> None:
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="fundus-share", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        thread, self._thread = self._thread, None
        if thread is None:                       # not started, or stopped already
            return
        self.httpd.shutdown()
        self.httpd.server_close()
        thread.join(timeout=3)

    def serve_forever(self) -> None:
        self.httpd.serve_forever()

    def rev(self) -> str:
        return f"{self.boot}:{self.db.revision()}"

    # -- what the handler calls ---------------------------------------------------------------
    def call(self, method: str, args: list, kwargs: dict):
        if method not in READS and method not in WRITES:
            raise PermissionError(method)
        if method == "upsert_patient":
            meta = args[0] if args else kwargs
            args, kwargs = [ExtractedMeta(**{k: meta.get(k) for k in ("patient_id", "name", "birth_date", "sex")})], {}
        elif method == "update_image":
            kwargs = {k: v for k, v in kwargs.items() if k not in PATH_COLUMNS}
        return _jsonable(getattr(self.db, method)(*args, **kwargs))

    def file_of(self, image_id: int, kind: str) -> Path | None:
        """A file of a photo in the database — the only files that are ever sent."""
        row = self.db.get_image(image_id)
        if row is None:
            return None
        if kind == "view":                       # what a browser can show
            path = row["display_path"] or row["file_path"]
        else:
            path = row[FILE_KINDS[kind]]
        if (not path or not os.path.isfile(path)) and kind in ("file", "view"):
            path = row["original_path"]
        return Path(path) if path and os.path.isfile(path) else None

    def add_derived(self, info: dict, data: bytes) -> int:
        import numpy as np
        from PIL import Image

        row = self.db.get_image(int(info["row_id"]))
        if row is None:
            raise LookupError("image")
        with Image.open(io.BytesIO(data)) as img:
            rgb = np.asarray(img.convert("RGB"))
        fields = {k: v for k, v in (info.get("fields") or {}).items() if k not in PATH_COLUMNS}
        with self._import_lock:
            return self.importer.add_derived(row, rgb, info.get("note") or "편집 영상",
                                             suffix=info.get("suffix") or "편집",
                                             derived_from=info.get("derived_from"), **fields)

    def import_upload(self, name: str, data: bytes, force: bool = True,
                      assign: PatientAssign | None = None) -> ImportResult:
        """A photo sent by another computer (파일 가져오기 there): imported like a dropped file —
        with ``assign``, the patient confirmed there (사진 가져오기 → 환자 정보 확인)."""
        parts = [p for p in re.split(r"[\\/]+", name) if p not in ("", ".", "..")]
        parts = [re.sub(r'[<>:"|?*\x00-\x1f]', "_", p) for p in parts][-4:] or ["image"]
        root = config_dir() / "uploads" / uuid.uuid4().hex
        path = root.joinpath(*parts)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            with self._import_lock:
                res = self.importer.import_file(path, WatchFolder(path=str(root)), force=force, wait=False,
                                                assign=assign)
        finally:
            shutil.rmtree(root, ignore_errors=True)
        res.path = name
        return res


def _assign_of(text: str) -> PatientAssign | None:
    """The patient sent along with an uploaded photo (JSON), or None."""
    try:
        d = json.loads(text) if text else None
    except ValueError:
        return None
    if not isinstance(d, dict) or not str(d.get("patient_id") or "").strip():
        return None
    return PatientAssign(**{k: (str(d[k]) if d.get(k) not in (None, "") else None)
                            for k in ("patient_id", "name", "birth_date", "sex")})


class _Handler(BaseHTTPRequestHandler):
    share: ShareServer
    protocol_version = "HTTP/1.1"
    server_version = f"{APP_NAME}/{__version__}"

    def log_message(self, *args) -> None:        # no console in the packaged program
        pass

    # -- plumbing -------------------------------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str, headers: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code: int = 200, headers: dict | None = None) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", headers)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n > 0 else b""

    def _authorized(self) -> bool:
        want = token_for(self.share.key)
        got = self.headers.get("X-Fundus-Token") or ""
        if not got:
            m = re.search(r"(?:^|;\s*)fvtoken=([0-9a-f]+)", self.headers.get("Cookie") or "")
            got = m.group(1) if m else ""
        return hmac.compare_digest(got, want)

    def _guard(self) -> bool:
        if self._authorized():
            return True
        self._body()                             # keep the connection in step
        self._json({"error": "unauthorized"}, 401)
        return False

    # -- GET ------------------------------------------------------------------------------------
    def do_GET(self) -> None:
        url = urlsplit(self.path)
        path = url.path
        try:
            if path in ("/", "/index.html"):
                self._send(200, WEB_PAGE.encode("utf-8"), "text/html; charset=utf-8",
                           {"Cache-Control": "no-cache"})
            elif path == "/api/ping":
                self._json({"app": APP_NAME, "version": __version__, "auth": self._authorized(),
                            "rev": self.share.rev() if self._authorized() else ""})
            elif path == "/api/rev":
                if self._guard():
                    self._json({"rev": self.share.rev()})
            elif path.startswith("/api/file/"):
                if self._guard():
                    self._file(path)
            else:
                self._json({"error": "not found"}, 404)
        except (BrokenPipeError, ConnectionError):
            pass
        except Exception as exc:
            self._fail(exc)

    do_HEAD = do_GET

    def _file(self, path: str) -> None:
        m = re.fullmatch(r"/api/file/(\d+)/(file|display|thumb|view)", path)
        f = self.share.file_of(int(m.group(1)), m.group(2)) if m else None
        if f is None:
            self._json({"error": "not found"}, 404)
            return
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        size = f.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "private, max-age=86400")
        self.end_headers()
        if self.command != "HEAD":
            with open(f, "rb") as fh:
                shutil.copyfileobj(fh, self.wfile, 256 * 1024)

    # -- POST -----------------------------------------------------------------------------------
    def do_POST(self) -> None:
        url = urlsplit(self.path)
        path, query = url.path, parse_qs(url.query)
        try:
            if path == "/api/login":
                key = json.loads(self._body() or b"{}").get("key") or ""
                if hmac.compare_digest(token_for(key), token_for(self.share.key)):
                    self._json({"ok": True}, headers={
                        "Set-Cookie": f"fvtoken={token_for(key)}; Path=/; HttpOnly; SameSite=Strict; Max-Age=2592000"})
                else:
                    self._json({"ok": False}, 401)
                return
            if not self._guard():
                return
            before = self.share.rev()
            if path == "/api/db":
                req = json.loads(self._body())
                method = req.get("method") or ""
                result = self.share.call(method, req.get("args") or [], req.get("kwargs") or {})
                changed = method in WRITES and method != "log"
            elif path == "/api/derived":
                info = json.loads(unquote(self.headers.get("X-Fundus-Args") or "%7B%7D"))
                result = self.share.add_derived(info, self._body())
                changed = True
            elif path == "/api/import":
                name = (query.get("name") or ["image"])[0]
                res = self.share.import_upload(name, self._body(), (query.get("force") or ["1"])[0] == "1",
                                               _assign_of((query.get("assign") or [""])[0]))
                result = {"status": res.status, "path": res.path, "message": res.message,
                          "image_id": res.image_id, "patient_ref": res.patient_ref}
                changed = res.status == "imported"
            else:
                self._body()
                self._json({"error": "not found"}, 404)
                return
            if changed:          # told before the answer goes out: once the other computer has its
                try:             # answer, the server's window already knows (no race with a reply)
                    self.share.on_change()
                except Exception:
                    pass
            self._json({"result": result, "before": before, "rev": self.share.rev()})
        except (BrokenPipeError, ConnectionError):
            pass
        except Exception as exc:
            self._fail(exc)

    def _fail(self, exc: Exception) -> None:
        code = 403 if isinstance(exc, PermissionError) else 404 if isinstance(exc, LookupError) else 500
        try:
            self._json({"error": f"{type(exc).__name__}: {exc}"}, code, {"Connection": "close"})
        except Exception:
            pass
        self.close_connection = True


# =========================================================================================
# client
# =========================================================================================
class ShareError(Exception):
    """The server could not be reached, or refused (``unauthorized``: wrong password)."""

    def __init__(self, message: str, unauthorized: bool = False):
        super().__init__(message)
        self.unauthorized = unauthorized


class RemoteRow(dict):
    """A database row that came from the server. Read like ``sqlite3.Row`` (by name or by number);
    the paths of a photo's files are those of the local copies, fetched when first asked for."""

    def __init__(self, data: dict, remote: "RemoteDatabase"):
        super().__init__(data)
        self._remote = remote

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        value = super().__getitem__(key)
        if value and key in FILE_KINDS.values() and "sha256" in self:
            return self._remote.local_file(self, key)
        return value

    def __hash__(self):
        return hash((self.get("id"), len(self)))


class RemoteDatabase:
    """The server's database, with the methods of :class:`~fundusview.db.Database` the viewer uses.

    When the server cannot be reached, reading gives nothing (an empty list, ``None``, 0) and a
    change is not stored; ``on_error`` is told either way, and for the next few seconds nothing
    is tried again, so the window does not hang on one timeout after another.
    """
    RETRY_AFTER = 4.0

    def __init__(self, url: str, key: str = "", cache_dir: Path | str | None = None,
                 on_error: Callable[[str], None] | None = None, timeout: float = 20.0):
        self.url = normalize_url(url)
        parts = urlsplit(self.url)
        self.host, self.port = parts.hostname or "", parts.port or DEFAULT_PORT
        self.token = token_for(key)
        self.timeout = timeout
        self.on_error = on_error or (lambda message: None)
        self.cache = Path(cache_dir) if cache_dir else config_dir() / "cache" / f"{self.host}_{self.port}"
        self.path = self.url                      # where the data is (Database.path)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._rev: str | None = None
        self._foreign = False                     # another computer changed something
        self._down_until = 0.0
        self.online = True

    # -- transport ------------------------------------------------------------------------------
    def _conn(self, fresh: bool = False) -> http.client.HTTPConnection:
        con = getattr(self._local, "con", None)
        if con is None or fresh:
            if con is not None:
                con.close()
            con = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
            self._local.con = con
        return con

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None,
                *, quiet: bool = False) -> tuple[bytes, dict]:
        """One request, on this thread's kept-open connection. Raises :class:`ShareError`."""
        if not quiet and time.monotonic() < self._down_until:
            raise ShareError("서버에 연결할 수 없습니다")
        head = {"X-Fundus-Token": self.token, **(headers or {})}
        last: Exception | None = None
        for attempt in (0, 1):                    # a kept-open connection may have been closed: once more
            try:
                con = self._conn(fresh=attempt == 1)
                con.request(method, path, body=body, headers=head)
                resp = con.getresponse()
                data = resp.read()
                break
            except (OSError, http.client.HTTPException) as exc:
                last = exc
                self._local.con = None
        else:
            self._down_until = time.monotonic() + self.RETRY_AFTER
            self.online = False
            raise ShareError(f"서버({self.host})에 연결할 수 없습니다: {last}")
        self._down_until, self.online = 0.0, True
        if resp.status == 401:
            raise ShareError("접속 암호가 맞지 않습니다", unauthorized=True)
        if resp.status != 200:
            try:
                detail = json.loads(data).get("error", "")
            except ValueError:
                detail = ""
            raise ShareError(f"서버 오류 {resp.status} {detail}".strip())
        return data, dict(resp.getheaders())

    def _post(self, path: str, body: bytes, headers: dict | None = None):
        data, _ = self.request("POST", path, body, headers)
        reply = json.loads(data)
        with self._lock:
            if self._rev is not None and reply.get("before") != self._rev:
                self._foreign = True
            self._rev = reply.get("rev")
        return reply.get("result")

    def ping(self) -> dict:
        """Is the server there, and is the password right? Raises :class:`ShareError`."""
        data, _ = self.request("GET", "/api/ping", quiet=True)
        info = json.loads(data)
        if info.get("app") != APP_NAME:
            raise ShareError("이 주소는 안저 사진 뷰어 서버가 아닙니다")
        if not info.get("auth"):
            raise ShareError("접속 암호가 맞지 않습니다", unauthorized=True)
        with self._lock:
            self._rev = info.get("rev")
        return info

    def changed(self) -> bool:
        """Did another computer (or the server itself) change something since the last look?"""
        try:
            data, _ = self.request("GET", "/api/rev", quiet=True)
        except ShareError:
            return False
        rev = json.loads(data).get("rev")
        with self._lock:
            hit = self._foreign or (self._rev is not None and rev != self._rev)
            self._rev, self._foreign = rev, False
        return hit

    # -- database -------------------------------------------------------------------------------
    def _wrap(self, value):
        if isinstance(value, dict):
            return RemoteRow(value, self)
        if isinstance(value, list):
            return [self._wrap(v) for v in value]
        return value

    def _call(self, method: str, *args, _default=None, **kwargs):
        body = json.dumps({"method": method, "args": _jsonable(list(args)), "kwargs": _jsonable(kwargs)},
                          ensure_ascii=False).encode("utf-8")
        try:
            return self._wrap(self._post("/api/db", body, {"Content-Type": "application/json"}))
        except ShareError as exc:
            write = method in WRITES and method != "log"
            self.on_error(f"{exc} — 변경한 내용이 저장되지 않았습니다" if write else str(exc))
            return _default

    def close(self) -> None:
        con = getattr(self._local, "con", None)
        if con is not None:
            con.close()
            self._local.con = None

    def upsert_patient(self, meta: ExtractedMeta):
        return self._call("upsert_patient", {k: getattr(meta, k) for k in ("patient_id", "name", "birth_date", "sex")})

    def update_patient(self, ref: int, **fields) -> None:
        self._call("update_patient", ref, **fields)

    def get_patient(self, ref: int):
        return self._call("get_patient", ref)

    def find_patient(self, patient_id: str):
        return self._call("find_patient", patient_id)

    def list_patients(self, search: str = ""):
        return self._call("list_patients", search, _default=[])

    def count_patients(self) -> int:
        return self._call("count_patients", _default=0)

    def patients_named(self, name: str):
        return self._call("patients_named", name, _default=[])

    def patients_examined(self, start: str, end: str) -> set:
        return set(self._call("patients_examined", start, end, _default=[]) or [])

    def delete_patient(self, ref: int) -> None:
        self._call("delete_patient", ref)

    def merge_patients(self, from_ref: int, into_ref: int) -> None:
        self._call("merge_patients", from_ref, into_ref)

    def update_image(self, image_id: int, **values) -> None:
        values = {k: v for k, v in values.items() if k not in PATH_COLUMNS}
        if values:
            self._call("update_image", image_id, **values)

    def get_image(self, image_id: int):
        return self._call("get_image", image_id)

    def image_by_sha(self, sha256: str):
        return self._call("image_by_sha", sha256)

    def images_for_patient(self, ref: int | None):
        return self._call("images_for_patient", ref, _default=[])

    def count_unassigned(self) -> int:
        return self._call("count_unassigned", _default=0)

    def unassigned_summary(self):
        return self._call("unassigned_summary",
                          _default=RemoteRow({"n_images": 0, "n_exams": 0, "last_exam": None}, self))

    def delete_image(self, image_id: int) -> None:
        self._call("delete_image", image_id)

    def log(self, level: str, message: str, path: str = "") -> None:
        self._call("log", level, message, path)

    def recent_logs(self, limit: int = 200):
        return self._call("recent_logs", limit, _default=[])

    def seen_index(self) -> dict:
        return {}

    # -- files ----------------------------------------------------------------------------------
    def local_file(self, row: dict, column: str) -> str:
        """The local copy of a photo's file (fetched on first use; a photo never changes, so a
        copy is good for ever). The path is returned even when the file could not be fetched —
        the viewer then says that the photo cannot be opened, as for a missing file."""
        kind = next(k for k, c in FILE_KINDS.items() if c == column)
        sha = (dict.get(row, "sha256") or "0")[:24]
        server_path = dict.get(row, column) or ""
        if kind == "file":
            name = re.split(r"[\\/]", server_path)[-1] or "image"
            dest = self.cache / "files" / sha / name
        else:
            suffix = os.path.splitext(server_path)[1] or (".jpg" if kind == "thumb" else ".png")
            dest = self.cache / kind / f"{sha}{suffix}"
        if dest.exists():
            return str(dest)
        try:
            data, _ = self.request("GET", f"/api/file/{int(dict.get(row, 'id'))}/{kind}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(f"{dest.name}.{uuid.uuid4().hex[:6]}.part")
            tmp.write_bytes(data)
            os.replace(tmp, dest)
        except (ShareError, OSError) as exc:
            if not isinstance(exc, ShareError) or "404" not in str(exc):
                self.on_error(str(exc))
        return str(dest)

    def prune_cache(self, limit: int = CACHE_LIMIT) -> None:
        """Keep the photo cache under ``limit`` bytes: the files not used for longest go first."""
        files = []
        for dirpath, _, names in os.walk(self.cache):
            for n in names:
                p = os.path.join(dirpath, n)
                try:
                    st = os.stat(p)
                    files.append((max(st.st_atime, st.st_mtime), st.st_size, p))
                except OSError:
                    pass
        total = sum(f[1] for f in files)
        for _, size, p in sorted(files):
            if total <= limit:
                break
            try:
                os.remove(p)
                total -= size
            except OSError:
                pass


class _RemoteImporter:
    def __init__(self, remote: RemoteDatabase):
        self.db = remote

    def add_derived(self, row, rgb, note: str = "편집 영상", *, suffix: str = "편집", derived_from=None,
                    **fields) -> int:
        """Store an edited picture (편집 영상, 몽타주, 디스크 2장 …) on the server; see
        :meth:`fundusview.importer.Importer.add_derived`."""
        from PIL import Image

        if isinstance(fields.get("meta_json"), str):
            fields["meta_json"] = json.loads(fields["meta_json"] or "{}")
        buf = io.BytesIO()
        Image.fromarray(rgb).save(buf, "PNG", compress_level=3)
        info = {"row_id": row["id"], "note": note, "suffix": suffix,
                "derived_from": _jsonable(derived_from), "fields": _jsonable(fields)}
        head = {"Content-Type": "image/png", "X-Fundus-Args": quote(json.dumps(info, ensure_ascii=False))}
        try:
            return int(self.db._post("/api/derived", buf.getvalue(), head))
        except ShareError as exc:
            self.db.on_error(f"{exc} — 저장하지 못했습니다")
            raise


class RemoteImportService:
    """Stands in for :class:`~fundusview.watcher.ImportService` on a computer connected to a server:
    the server watches the cameras' folders; a file imported here by hand is sent to it."""

    def __init__(self, remote: RemoteDatabase, settings: Settings,
                 on_result: Callable[[ImportResult], None] | None = None,
                 on_status: Callable[[str], None] | None = None):
        import queue

        self.db = remote
        self.settings = settings
        self.importer = _RemoteImporter(remote)
        self.on_result = on_result or (lambda r: None)
        self.on_status = on_status or (lambda s: None)
        self._q: "queue.Queue" = queue.Queue()
        self._n = 0
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._run, name="fundus-upload", daemon=True)
        self._worker.start()

    is_watching = False

    @property
    def queued(self) -> int:
        with self._lock:
            return self._n

    def start_watching(self) -> list[str]:
        return []

    def stop_watching(self) -> None:
        pass

    def scan_all(self, full: bool = False) -> int:
        return 0

    def manual_files(self, paths: list[str]) -> list[tuple[str, WatchFolder | None, str]]:
        """As :meth:`ImportService.manual_files <fundusview.watcher.ImportService.manual_files>`, with
        the name each file is sent to the server under (the folder names it is read with)."""
        from .importer import MANUAL_PARENT_LEVELS
        from .watcher import _cheap_candidate

        out: list[tuple[str, WatchFolder | None, str]] = []
        for p in paths:
            if os.path.isdir(p):
                p = os.path.normpath(p)
                base = os.path.dirname(p) or p
                own = WatchFolder(path=base)
                for dirpath, dirnames, filenames in os.walk(p):
                    dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
                    for n in sorted(filenames):
                        fp = os.path.join(dirpath, n)
                        if _cheap_candidate(fp):
                            out.append((fp, own, os.path.relpath(fp, base)))
            elif os.path.isfile(p):
                out.append((p, None, os.path.join(*Path(p).parts[-(MANUAL_PARENT_LEVELS + 1):])))
        return out

    def preview_paths(self, paths: list[str], progress: Callable[[int, int], None] | None = None,
                      cancelled: Callable[[], bool] | None = None) -> list:
        """사진 가져오기 → 환자 정보 확인: what the photos say, read here (nothing is sent yet); a photo
        the server has already is a duplicate."""
        from .importer import is_candidate

        files = self.manual_files(paths)
        items = []
        for i, (fp, folder, _) in enumerate(files):
            if cancelled is not None and cancelled():
                break
            if is_candidate(Path(fp)):
                items.append(self._preview(fp, folder))
            if progress is not None:
                progress(i + 1, len(files))
        return items

    def _preview(self, fp: str, folder: WatchFolder | None):
        from PIL import Image

        from .extract import extract_metadata, is_dicom
        from .importer import MANUAL_PARENT_LEVELS, PreviewItem, describe_error, sha256_of

        path = Path(fp)
        try:
            if path.stat().st_size == 0:
                return PreviewItem(fp, "error", message="빈 파일")
            dup = self.db.image_by_sha(sha256_of(path))
            if dup is None and not is_dicom(path):
                with Image.open(path) as img:        # the header only: is it a picture at all?
                    img.size
            meta, profile = extract_metadata(
                path, folder.profile if folder else "auto", watch_root=Path(folder.path) if folder else None,
                custom_patterns=self.settings.custom_filename_patterns,
                parent_levels=None if folder else MANUAL_PARENT_LEVELS)
            if dup is not None:
                return PreviewItem(fp, "duplicate", meta, profile.name, "이미 가져온 사진",
                                   dup["id"], dup["patient_ref"], folder)
            return PreviewItem(fp, "new", meta, profile.name, folder=folder)
        except Exception as exc:
            return PreviewItem(fp, "error", message=describe_error(exc)[:200])

    def import_items(self, items) -> int:
        """Send the previewed photos to the server, each with the patient confirmed for it — or the
        one read here, so that the server files it where the review showed it."""
        from .importer import MANUAL_PARENT_LEVELS

        jobs = []
        for item, assign in items:
            m = item.meta
            if assign is None and m is not None and (m.patient_id or "").strip():
                assign = PatientAssign(m.patient_id, m.name, m.birth_date, m.sex)
            if item.folder is not None:
                name = os.path.relpath(item.path, item.folder.path)
            else:
                name = os.path.join(*Path(item.path).parts[-(MANUAL_PARENT_LEVELS + 1):])
            jobs.append((item.path, name, assign))
        self._enqueue(jobs)
        return len(jobs)

    def import_paths(self, paths: list[str], force: bool = False) -> int:
        jobs = [(fp, name, None) for fp, _, name in self.manual_files(paths)]
        self._enqueue(jobs)
        return len(jobs)

    def _enqueue(self, jobs) -> None:
        with self._lock:
            self._n += len(jobs)
        for job in jobs:
            self._q.put(job)

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                return
            fp, name, assign = item
            with self._lock:
                self._n -= 1
                left = self._n
            self.on_status(f"가져오는 중: {os.path.basename(fp)} (대기 {left})")
            try:
                with open(fp, "rb") as fh:
                    data = fh.read()
                url = f"/api/import?force=1&name={quote(name)}"
                if assign is not None:
                    url += "&assign=" + quote(json.dumps(
                        {k: getattr(assign, k) for k in ("patient_id", "name", "birth_date", "sex")},
                        ensure_ascii=False))
                r = self.db._post(url, data, {"Content-Type": "application/octet-stream"})
                res = ImportResult(r["status"], fp, r.get("message") or "", r.get("image_id"), r.get("patient_ref"))
            except (ShareError, OSError) as exc:
                res = ImportResult("error", fp, str(exc))
            self.on_result(res)
            if self.queued == 0:
                self.on_status("대기 중")

    def shutdown(self) -> None:
        self._q.put(None)
        self._worker.join(timeout=5)


def serve(settings: Settings, db) -> int:
    """``--serve``: the server without a window — watches the folders, imports, and answers the
    other computers until it is stopped (Ctrl+C)."""
    from . import autosetup
    from .watcher import ImportService

    if not settings.share_key:
        settings.share_key = new_key()
        settings.save()
    if settings.auto_detect:
        autosetup.apply(settings, autosetup.detect())
    service = ImportService(db, settings)
    service.start_watching()
    server = ShareServer(db, settings, service.importer)
    print(f"{APP_NAME} 서버: {server.address}  (접속 암호: {settings.share_key})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.httpd.server_close()
        service.shutdown()
    return 0
