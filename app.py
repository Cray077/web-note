import json
import os
import re
import sqlite3
import tempfile
import threading
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, g, jsonify, send_file, send_from_directory
from flask_sock import Sock
from simple_websocket import ConnectionClosed

MAX_NOTE_BYTES = 5 * 1024 * 1024  # 5 MB per note
MAX_WS_MESSAGE_BYTES = MAX_NOTE_BYTES + 1024 * 1024
MAX_FILENAME_LEN = 255

app = Flask(__name__, static_folder="static")
app.config["NOTES_DIR"] = os.environ.get("NOTES_DIR", "/var/notes")
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename   TEXT NOT NULL,
                    path       TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
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


def safe_zip_name(filename: str, note_id: int, used_lower: set[str]) -> str:
    # Strip path separators, control characters, and illegal filename characters.
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", filename).strip().strip(".")
    if not cleaned:
        cleaned = f"note-{note_id}"

    if cleaned.lower().endswith(".md"):
        stem = cleaned[:-3].strip().rstrip(".") or f"note-{note_id}"
    else:
        stem = cleaned

    candidate = f"{stem}.md"
    counter = 2
    while candidate.lower() in used_lower:
        candidate = f"{stem} ({counter}).md"
        counter += 1

    used_lower.add(candidate.lower())
    return candidate


def op_list_notes() -> list[dict]:
    with closing(open_db()) as db:
        rows = db.execute(
            "SELECT id, filename, updated_at FROM notes ORDER BY updated_at DESC, id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def op_create_note(filename: object) -> dict:
    if not isinstance(filename, str):
        raise AppError("filename must be a string", 400)
    filename = filename.strip()
    if not filename or len(filename) > MAX_FILENAME_LEN:
        raise AppError("filename must be between 1 and 255 characters", 400)

    updated_at = now_iso()
    with closing(open_db()) as db:
        try:
            cursor = db.execute(
                "INSERT INTO notes (filename, path, updated_at) VALUES (?, '', ?)",
                (filename, updated_at),
            )
            note_id = cursor.lastrowid
            file_path = note_file_path(note_id)
            db.execute("UPDATE notes SET path = ? WHERE id = ?", (str(file_path), note_id))
            atomic_write_text(file_path, "")
            db.commit()
        except Exception:
            db.rollback()
            raise

    return {"id": note_id, "filename": filename, "updated_at": updated_at}


def op_get_note(raw_id: object) -> dict:
    note_id = parse_note_id(raw_id)
    with closing(open_db()) as db:
        row = db.execute(
            "SELECT id, filename, updated_at FROM notes WHERE id = ?",
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
                "SELECT id, filename FROM notes WHERE id = ?",
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
        }
        return meta, content


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
            reply({"type": "notes_list", "notes": op_list_notes()})
        elif msg_type == "create_note":
            note = op_create_note(msg.get("filename"))
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


@app.route("/api/export", methods=["GET"])
def export_notes():
    db = get_db()
    rows = db.execute(
        "SELECT id, filename FROM notes ORDER BY updated_at DESC, id DESC"
    ).fetchall()

    spool = tempfile.SpooledTemporaryFile(max_size=10 * 1024 * 1024)
    used_names: set[str] = set()

    with zipfile.ZipFile(spool, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for row in rows:
            file_path = note_file_path(row["id"])
            try:
                content = file_path.read_bytes()
            except FileNotFoundError:
                content = b""
            arcname = safe_zip_name(row["filename"], row["id"], used_names)
            zf.writestr(arcname, content)

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
