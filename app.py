import base64
import binascii
import json
import os
import re
import sqlite3
import tempfile
import threading
import time
import uuid
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, g, jsonify, send_file, send_from_directory
from flask_sock import Sock
from simple_websocket import ConnectionClosed

MAX_NOTE_BYTES = 5 * 1024 * 1024  # 5 MB per note
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB per image
MAX_WS_MESSAGE_BYTES = 16 * 1024 * 1024  # 16 MB (allows base64-encoded images up to 10 MB)
MAX_FILENAME_LEN = 255
DEFAULT_USERNAME = os.environ.get("DEFAULT_USER", "user1")

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_IMAGE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}\.(png|jpg|jpeg|webp|gif)$", re.IGNORECASE)
_DATA_URL_RE = re.compile(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", re.DOTALL)
_IMAGE_MIMES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

app = Flask(__name__, static_folder="static")
app.config["NOTES_DIR"] = os.environ.get("NOTES_DIR", "/var/notes")
app.config["IMAGES_DIR"] = os.environ.get(
    "IMAGES_DIR", str(Path(__file__).resolve().parent / "user-images")
)
app.config["MAX_CONTENT_LENGTH"] = MAX_WS_MESSAGE_BYTES
app.config["SOCK_SERVER_OPTIONS"] = {"ping_interval": 25}

sock = Sock(app)

_init_lock = threading.Lock()
_initialized_dirs: set[str] = set()

_clients_lock = threading.Lock()
_clients: set["WSClient"] = set()

_note_locks_guard = threading.Lock()
_note_locks: dict[int, threading.Lock] = {}


class AppError(Exception):
    def __init__(self, message: str, code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class WSClient:
    def __init__(self, ws) -> None:
        self.ws = ws
        self._send_lock = threading.Lock()

    def send_json(self, payload: dict) -> bool:
        encoded = json.dumps(payload, separators=(",", ":"))
        with self._send_lock:
            try:
                self.ws.send(encoded)
                return True
            except Exception:
                return False


def _get_note_lock(note_id: int) -> threading.Lock:
    with _note_locks_guard:
        lock = _note_locks.get(note_id)
        if lock is None:
            lock = threading.Lock()
            _note_locks[note_id] = lock
        return lock


def broadcast(payload: dict, exclude: WSClient | None = None) -> None:
    with _clients_lock:
        targets = list(_clients)
    dead: list[WSClient] = []
    for client in targets:
        if client is exclude:
            continue
        if not client.send_json(payload):
            dead.append(client)
    if dead:
        with _clients_lock:
            for client in dead:
                _clients.discard(client)


def get_notes_dir() -> Path:
    return Path(app.config["NOTES_DIR"]).resolve()


def get_images_dir() -> Path:
    return Path(app.config["IMAGES_DIR"]).resolve()


def get_db_path() -> Path:
    return get_notes_dir() / "notes.db"


def init_db() -> None:
    notes_dir = get_notes_dir()
    key = str(notes_dir)
    if key in _initialized_dirs:
        return
    with _init_lock:
        if key in _initialized_dirs:
            return
        notes_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(get_db_path(), timeout=30.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS folders (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    name       TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename   TEXT NOT NULL,
                    path       TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    folder_id  INTEGER REFERENCES folders(id) ON DELETE SET NULL
                )
                """
            )
            cols = {row[1] for row in conn.execute("PRAGMA table_info(notes)").fetchall()}
            if "folder_id" not in cols:
                conn.execute(
                    "ALTER TABLE notes ADD COLUMN folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL"
                )
            conn.commit()
        finally:
            conn.close()
        _initialized_dirs.add(key)


def open_db() -> sqlite3.Connection:
    init_db()
    conn = sqlite3.connect(get_db_path(), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = open_db()
    return g.db


@app.teardown_appcontext
def close_db(_exc: BaseException | None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_note_id(raw_id: object) -> int:
    if isinstance(raw_id, bool) or not isinstance(raw_id, int) or raw_id <= 0:
        raise AppError("Invalid note id", 400)
    return raw_id


def parse_folder_id(raw_id: object, *, allow_none: bool = False) -> int | None:
    if raw_id is None and allow_none:
        return None
    if isinstance(raw_id, bool) or not isinstance(raw_id, int) or raw_id <= 0:
        raise AppError("Invalid folder id", 400)
    return raw_id


def note_file_path(note_id: int) -> Path:
    if isinstance(note_id, bool) or not isinstance(note_id, int) or note_id <= 0:
        raise ValueError("Invalid note id")
    notes_dir = get_notes_dir()
    path = (notes_dir / f"{note_id}.md").resolve()
    if path.parent != notes_dir:
        raise ValueError("Resolved path escapes notes directory")
    return path


def atomic_write_text(path: Path, content: str) -> None:
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def atomic_write_bytes(path: Path, data: bytes) -> None:
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def validate_username(raw_username: object) -> str:
    if raw_username is None or raw_username == "":
        username = DEFAULT_USERNAME
    elif isinstance(raw_username, str):
        username = raw_username.strip()
    else:
        raise AppError("Invalid username", 400)
    if not _USERNAME_RE.match(username):
        raise AppError("Invalid username", 400)
    return username


def image_file_path(username: str, filename: str) -> Path:
    if not _USERNAME_RE.match(username) or not _IMAGE_FILENAME_RE.match(filename):
        raise ValueError("Invalid image path")
    images_root = get_images_dir()
    user_dir = (images_root / username).resolve()
    if user_dir.parent != images_root:
        raise ValueError("Resolved user directory escapes images directory")
    path = (user_dir / filename).resolve()
    if path.parent != user_dir:
        raise ValueError("Resolved image path escapes user directory")
    return path


def detect_image_ext(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def safe_zip_folder_name(name: str, folder_id: int, used_lower: set[str]) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip().strip(".")
    if not cleaned:
        cleaned = f"folder-{folder_id}"
    candidate = cleaned
    counter = 2
    while candidate.lower() in used_lower:
        candidate = f"{cleaned} ({counter})"
        counter += 1
    used_lower.add(candidate.lower())
    return candidate


def safe_zip_name(
    filename: str, note_id: int, used_lower: set[str], folder_prefix: str = ""
) -> str:
    # Strip path separators, control characters, and illegal filename characters.
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", filename).strip().strip(".")
    if not cleaned:
        cleaned = f"note-{note_id}"

    if cleaned.lower().endswith(".md"):
        stem = cleaned[:-3].strip().rstrip(".") or f"note-{note_id}"
    else:
        stem = cleaned

    prefix = f"{folder_prefix}/" if folder_prefix else ""
    candidate = f"{prefix}{stem}.md"
    counter = 2
    while candidate.lower() in used_lower:
        candidate = f"{prefix}{stem} ({counter}).md"
        counter += 1

    used_lower.add(candidate.lower())
    return candidate


def op_list_notes() -> list[dict]:
    with closing(open_db()) as db:
        rows = db.execute(
            "SELECT id, filename, updated_at, folder_id FROM notes ORDER BY updated_at DESC, id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def op_list_folders() -> list[dict]:
    with closing(open_db()) as db:
        rows = db.execute(
            "SELECT id, name, created_at FROM folders ORDER BY LOWER(name) ASC, id ASC"
        ).fetchall()
    return [dict(row) for row in rows]


def op_create_folder(name: object) -> dict:
    if not isinstance(name, str):
        raise AppError("name must be a string", 400)
    name = name.strip()
    if not name or len(name) > MAX_FILENAME_LEN:
        raise AppError("name must be between 1 and 255 characters", 400)

    created_at = now_iso()
    with closing(open_db()) as db:
        cursor = db.execute(
            "INSERT INTO folders (name, created_at) VALUES (?, ?)",
            (name, created_at),
        )
        folder_id = cursor.lastrowid
        db.commit()
    return {"id": folder_id, "name": name, "created_at": created_at}


def op_rename_folder(raw_id: object, name: object) -> dict:
    folder_id = parse_folder_id(raw_id)
    if not isinstance(name, str):
        raise AppError("name must be a string", 400)
    name = name.strip()
    if not name or len(name) > MAX_FILENAME_LEN:
        raise AppError("name must be between 1 and 255 characters", 400)

    with closing(open_db()) as db:
        row = db.execute(
            "SELECT id, created_at FROM folders WHERE id = ?",
            (folder_id,),
        ).fetchone()
        if row is None:
            raise AppError("Folder not found", 404)
        db.execute("UPDATE folders SET name = ? WHERE id = ?", (name, folder_id))
        db.commit()
    return {"id": row["id"], "name": name, "created_at": row["created_at"]}


def op_create_note(filename: object, raw_folder_id: object = None) -> dict:
    if not isinstance(filename, str):
        raise AppError("filename must be a string", 400)
    filename = filename.strip()
    if not filename or len(filename) > MAX_FILENAME_LEN:
        raise AppError("filename must be between 1 and 255 characters", 400)

    folder_id = parse_folder_id(raw_folder_id, allow_none=True)

    updated_at = now_iso()
    with closing(open_db()) as db:
        if folder_id is not None:
            folder_row = db.execute(
                "SELECT id FROM folders WHERE id = ?",
                (folder_id,),
            ).fetchone()
            if folder_row is None:
                raise AppError("Folder not found", 404)
        try:
            cursor = db.execute(
                "INSERT INTO notes (filename, path, updated_at, folder_id) VALUES (?, '', ?, ?)",
                (filename, updated_at, folder_id),
            )
            note_id = cursor.lastrowid
            file_path = note_file_path(note_id)
            db.execute("UPDATE notes SET path = ? WHERE id = ?", (str(file_path), note_id))
            atomic_write_text(file_path, "")
            db.commit()
        except Exception:
            db.rollback()
            raise

    return {
        "id": note_id,
        "filename": filename,
        "updated_at": updated_at,
        "folder_id": folder_id,
    }


def op_get_note(raw_id: object) -> dict:
    note_id = parse_note_id(raw_id)
    with closing(open_db()) as db:
        row = db.execute(
            "SELECT id, filename, updated_at, folder_id FROM notes WHERE id = ?",
            (note_id,),
        ).fetchone()
    if row is None:
        raise AppError("Note not found", 404)

    file_path = note_file_path(note_id)
    try:
        content = file_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        content = ""

    return {
        "id": row["id"],
        "filename": row["filename"],
        "updated_at": row["updated_at"],
        "folder_id": row["folder_id"],
        "content": content,
    }


def op_update_note(raw_id: object, content: object) -> tuple[dict, str]:
    note_id = parse_note_id(raw_id)
    if not isinstance(content, str):
        raise AppError("content must be a string", 400)
    if len(content.encode("utf-8")) > MAX_NOTE_BYTES:
        raise AppError("Note exceeds maximum size limit", 413)

    with _get_note_lock(note_id):
        with closing(open_db()) as db:
            row = db.execute(
                "SELECT id, filename, folder_id FROM notes WHERE id = ?",
                (note_id,),
            ).fetchone()
            if row is None:
                raise AppError("Note not found", 404)

            file_path = note_file_path(note_id)
            atomic_write_text(file_path, content)

            updated_at = now_iso()
            db.execute(
                "UPDATE notes SET updated_at = ? WHERE id = ?",
                (updated_at, note_id),
            )
            db.commit()

        meta = {
            "id": row["id"],
            "filename": row["filename"],
            "updated_at": updated_at,
            "folder_id": row["folder_id"],
        }
        return meta, content


def op_rename_note(raw_id: object, filename: object) -> dict:
    note_id = parse_note_id(raw_id)
    if not isinstance(filename, str):
        raise AppError("filename must be a string", 400)
    filename = filename.strip()
    if not filename or len(filename) > MAX_FILENAME_LEN:
        raise AppError("filename must be between 1 and 255 characters", 400)

    with _get_note_lock(note_id):
        with closing(open_db()) as db:
            row = db.execute(
                "SELECT id, updated_at, folder_id FROM notes WHERE id = ?",
                (note_id,),
            ).fetchone()
            if row is None:
                raise AppError("Note not found", 404)

            db.execute(
                "UPDATE notes SET filename = ? WHERE id = ?",
                (filename, note_id),
            )
            db.commit()

        return {
            "id": row["id"],
            "filename": filename,
            "updated_at": row["updated_at"],
            "folder_id": row["folder_id"],
        }


def op_move_note(raw_id: object, raw_folder_id: object) -> dict:
    note_id = parse_note_id(raw_id)
    folder_id = parse_folder_id(raw_folder_id, allow_none=True)

    with _get_note_lock(note_id):
        with closing(open_db()) as db:
            row = db.execute(
                "SELECT id, filename, updated_at FROM notes WHERE id = ?",
                (note_id,),
            ).fetchone()
            if row is None:
                raise AppError("Note not found", 404)
            if folder_id is not None:
                folder_row = db.execute(
                    "SELECT id FROM folders WHERE id = ?",
                    (folder_id,),
                ).fetchone()
                if folder_row is None:
                    raise AppError("Folder not found", 404)

            db.execute(
                "UPDATE notes SET folder_id = ? WHERE id = ?",
                (folder_id, note_id),
            )
            db.commit()

        return {
            "id": row["id"],
            "filename": row["filename"],
            "updated_at": row["updated_at"],
            "folder_id": folder_id,
        }


def op_delete_note(raw_id: object) -> dict:
    note_id = parse_note_id(raw_id)

    with _get_note_lock(note_id):
        with closing(open_db()) as db:
            row = db.execute(
                "SELECT id FROM notes WHERE id = ?",
                (note_id,),
            ).fetchone()
            if row is None:
                raise AppError("Note not found", 404)

            db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            db.commit()

        file_path = note_file_path(note_id)
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass

        return {"id": note_id}


def op_delete_folder(raw_id: object, delete_notes: bool = False) -> dict:
    folder_id = parse_folder_id(raw_id)
    deleted_note_ids: list[int] = []

    with closing(open_db()) as db:
        row = db.execute(
            "SELECT id FROM folders WHERE id = ?",
            (folder_id,),
        ).fetchone()
        if row is None:
            raise AppError("Folder not found", 404)

        if delete_notes:
            note_rows = db.execute(
                "SELECT id FROM notes WHERE folder_id = ?",
                (folder_id,),
            ).fetchall()
            deleted_note_ids = [r["id"] for r in note_rows]
            db.execute("DELETE FROM notes WHERE folder_id = ?", (folder_id,))
        else:
            db.execute("UPDATE notes SET folder_id = NULL WHERE folder_id = ?", (folder_id,))

        db.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
        db.commit()

    for note_id in deleted_note_ids:
        with _get_note_lock(note_id):
            try:
                note_file_path(note_id).unlink(missing_ok=True)
            except OSError:
                pass

    return {"id": folder_id, "deleted_note_ids": deleted_note_ids}


def op_upload_image(
    raw_data: object,
    raw_username: object = None,
    replace_filename: object = None,
) -> tuple[dict, bool]:
    if not isinstance(raw_data, str) or not raw_data:
        raise AppError("Image data must be a non-empty string", 400)

    username = validate_username(raw_username)

    match = _DATA_URL_RE.match(raw_data.strip())
    b64_payload = match.group(2) if match else raw_data.strip()
    try:
        raw_bytes = base64.b64decode(b64_payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AppError("Invalid base64 image data", 400) from exc

    if not raw_bytes:
        raise AppError("Image data is empty", 400)
    if len(raw_bytes) > MAX_IMAGE_BYTES:
        raise AppError("Image exceeds maximum size limit (10 MB)", 413)

    ext = detect_image_ext(raw_bytes)
    if ext is None:
        raise AppError("Unsupported image format (use PNG, JPEG, GIF, or WebP)", 400)

    images_root = get_images_dir()
    user_dir = (images_root / username).resolve()
    if user_dir.parent != images_root:
        raise AppError("Invalid username", 400)
    user_dir.mkdir(parents=True, exist_ok=True)

    replaced = False
    if replace_filename is not None:
        if not isinstance(replace_filename, str) or not _IMAGE_FILENAME_RE.match(replace_filename):
            raise AppError("Invalid image filename", 400)
        filename = replace_filename
        file_path = image_file_path(username, filename)
        replaced = file_path.exists()
    else:
        filename = f"{uuid.uuid4().hex}{ext}"
        file_path = image_file_path(username, filename)

    atomic_write_bytes(file_path, raw_bytes)
    version = str(int(time.time() * 1000))
    return (
        {
            "username": username,
            "filename": filename,
            "url": f"/images/{username}/{filename}",
            "v": version,
        },
        replaced,
    )


def handle_ws_message(client: WSClient, msg: dict) -> None:
    msg_type = msg.get("type")
    req_id = msg.get("req_id")

    def reply(payload: dict) -> None:
        if req_id is not None:
            payload = {**payload, "req_id": req_id}
        client.send_json(payload)

    try:
        if msg_type == "ping":
            reply({"type": "pong"})
        elif msg_type == "list_notes":
            reply(
                {
                    "type": "notes_list",
                    "notes": op_list_notes(),
                    "folders": op_list_folders(),
                }
            )
        elif msg_type == "create_note":
            note = op_create_note(msg.get("filename"), msg.get("folder_id"))
            reply({"type": "note_created", "note": note})
            broadcast({"type": "note_created", "note": note}, exclude=client)
        elif msg_type == "get_note":
            note = op_get_note(msg.get("id"))
            reply({"type": "note_content", "note": note})
        elif msg_type == "update_note":
            note, content = op_update_note(msg.get("id"), msg.get("content"))
            reply({"type": "note_saved", "note": note})
            broadcast(
                {"type": "note_updated", "note": {**note, "content": content}},
                exclude=client,
            )
        elif msg_type == "rename_note":
            note = op_rename_note(msg.get("id"), msg.get("filename"))
            reply({"type": "note_renamed", "note": note})
            broadcast({"type": "note_renamed", "note": note}, exclude=client)
        elif msg_type == "move_note":
            note = op_move_note(msg.get("id"), msg.get("folder_id"))
            reply({"type": "note_moved", "note": note})
            broadcast({"type": "note_moved", "note": note}, exclude=client)
        elif msg_type == "create_folder":
            folder = op_create_folder(msg.get("name"))
            reply({"type": "folder_created", "folder": folder})
            broadcast({"type": "folder_created", "folder": folder}, exclude=client)
        elif msg_type == "rename_folder":
            folder = op_rename_folder(msg.get("id"), msg.get("name"))
            reply({"type": "folder_renamed", "folder": folder})
            broadcast({"type": "folder_renamed", "folder": folder}, exclude=client)
        elif msg_type == "delete_note":
            deleted = op_delete_note(msg.get("id"))
            reply({"type": "note_deleted", **deleted})
            broadcast({"type": "note_deleted", **deleted}, exclude=client)
        elif msg_type == "delete_folder":
            deleted = op_delete_folder(msg.get("id"), bool(msg.get("delete_notes", False)))
            reply({"type": "folder_deleted", **deleted})
            broadcast({"type": "folder_deleted", **deleted}, exclude=client)
        elif msg_type == "upload_image":
            image, replaced = op_upload_image(
                msg.get("data"),
                msg.get("username"),
                msg.get("replace"),
            )
            reply({"type": "image_uploaded", "image": image})
            if replaced:
                broadcast({"type": "image_updated", "image": image}, exclude=client)
        else:
            reply({"type": "error", "error": f"Unknown message type: {msg_type}", "code": 400})
    except AppError as exc:
        reply({"type": "error", "error": exc.message, "code": exc.code})
    except Exception:
        app.logger.exception("WebSocket message handling failed")
        reply({"type": "error", "error": "Internal server error", "code": 500})


@sock.route("/ws")
def ws_endpoint(ws):
    client = WSClient(ws)
    with _clients_lock:
        _clients.add(client)
    try:
        while True:
            raw = ws.receive()
            if raw is None:
                break
            if isinstance(raw, bytes):
                if len(raw) > MAX_WS_MESSAGE_BYTES:
                    client.send_json(
                        {
                            "type": "error",
                            "error": "Note exceeds maximum size limit",
                            "code": 413,
                        }
                    )
                    continue
                raw = raw.decode("utf-8", errors="replace")
            elif len(raw.encode("utf-8")) > MAX_WS_MESSAGE_BYTES:
                client.send_json(
                    {
                        "type": "error",
                        "error": "Note exceeds maximum size limit",
                        "code": 413,
                    }
                )
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                client.send_json(
                    {"type": "error", "error": "Invalid JSON message", "code": 400}
                )
                continue

            if not isinstance(msg, dict):
                client.send_json(
                    {"type": "error", "error": "Message must be a JSON object", "code": 400}
                )
                continue

            handle_ws_message(client, msg)
    except ConnectionClosed:
        pass
    finally:
        with _clients_lock:
            _clients.discard(client)


@app.errorhandler(413)
def handle_too_large(_err):
    return jsonify({"error": "Note exceeds maximum size limit"}), 413


@app.route("/", methods=["GET"])
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/images/<username>/<filename>", methods=["GET"])
def serve_user_image(username: str, filename: str):
    try:
        file_path = image_file_path(username, filename)
    except ValueError:
        abort(404)
    if not file_path.is_file():
        abort(404)
    try:
        with file_path.open("rb") as handle:
            detected_ext = detect_image_ext(handle.read(16))
    except OSError:
        abort(404)
    mimetype = _IMAGE_MIMES.get(
        detected_ext or file_path.suffix.lower(), "application/octet-stream"
    )
    response = send_file(file_path, mimetype=mimetype)
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.route("/api/export", methods=["GET"])
def export_notes():
    db = get_db()
    folder_rows = db.execute(
        "SELECT id, name FROM folders ORDER BY LOWER(name) ASC, id ASC"
    ).fetchall()
    rows = db.execute(
        "SELECT id, filename, folder_id FROM notes ORDER BY updated_at DESC, id DESC"
    ).fetchall()

    spool = tempfile.SpooledTemporaryFile(max_size=10 * 1024 * 1024)
    used_folders: set[str] = {"images"}
    folder_zip_names: dict[int, str] = {}
    for frow in folder_rows:
        folder_zip_names[frow["id"]] = safe_zip_folder_name(
            frow["name"], frow["id"], used_folders
        )
    used_names: set[str] = set()

    with zipfile.ZipFile(spool, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for row in rows:
            file_path = note_file_path(row["id"])
            try:
                content = file_path.read_bytes()
            except FileNotFoundError:
                content = b""
            folder_prefix = folder_zip_names.get(row["folder_id"], "")
            arcname = safe_zip_name(
                row["filename"], row["id"], used_names, folder_prefix=folder_prefix
            )
            zf.writestr(arcname, content)

        images_root = get_images_dir()
        if images_root.is_dir():
            for user_dir in sorted(images_root.iterdir(), key=lambda p: p.name):
                if not user_dir.is_dir() or not _USERNAME_RE.match(user_dir.name):
                    continue
                for img_file in sorted(user_dir.iterdir(), key=lambda p: p.name):
                    if not img_file.is_file() or not _IMAGE_FILENAME_RE.match(img_file.name):
                        continue
                    try:
                        img_bytes = img_file.read_bytes()
                    except OSError:
                        continue
                    zf.writestr(f"images/{user_dir.name}/{img_file.name}", img_bytes)

    spool.seek(0)
    return send_file(
        spool,
        mimetype="application/zip",
        as_attachment=True,
        download_name="notes.zip",
    )


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8000")),
        threaded=True,
    )
