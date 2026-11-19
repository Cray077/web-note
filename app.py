import os
import re
import sqlite3
import tempfile
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, g, jsonify, request, send_file, send_from_directory

MAX_NOTE_BYTES = 5 * 1024 * 1024  # 5 MB per note
MAX_FILENAME_LEN = 255

app = Flask(__name__, static_folder="static")
app.config["NOTES_DIR"] = os.environ.get("NOTES_DIR", "/var/notes")
app.config["MAX_CONTENT_LENGTH"] = MAX_NOTE_BYTES + 1024 * 1024

_init_lock = threading.Lock()
_initialized_dirs: set[str] = set()


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


def get_db() -> sqlite3.Connection:
    init_db()
    if "db" not in g:
        conn = sqlite3.connect(get_db_path(), timeout=30.0)
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(_exc: BaseException | None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def note_file_path(note_id: int) -> Path:
    if not isinstance(note_id, int) or note_id <= 0:
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


@app.errorhandler(413)
def handle_too_large(_err):
    return jsonify({"error": "Note exceeds maximum size limit"}), 413


@app.route("/", methods=["GET"])
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/notes", methods=["GET"])
def list_notes():
    db = get_db()
    rows = db.execute(
        "SELECT id, filename, updated_at FROM notes ORDER BY updated_at DESC, id DESC"
    ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.route("/api/notes", methods=["POST"])
def create_note():
    data = request.get_json(silent=True) or {}
    filename = data.get("filename")
    if not isinstance(filename, str):
        return jsonify({"error": "filename must be a string"}), 400
    filename = filename.strip()
    if not filename or len(filename) > MAX_FILENAME_LEN:
        return jsonify({"error": "filename must be between 1 and 255 characters"}), 400

    db = get_db()
    updated_at = now_iso()
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

    return (
        jsonify({"id": note_id, "filename": filename, "updated_at": updated_at}),
        201,
    )


@app.route("/api/notes/<int:note_id>", methods=["GET"])
def get_note(note_id: int):
    db = get_db()
    row = db.execute(
        "SELECT id, filename, updated_at FROM notes WHERE id = ?",
        (note_id,),
    ).fetchone()
    if row is None:
        return jsonify({"error": "Note not found"}), 404

    file_path = note_file_path(note_id)
    try:
        content = file_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        content = ""

    return jsonify(
        {
            "id": row["id"],
            "filename": row["filename"],
            "updated_at": row["updated_at"],
            "content": content,
        }
    )


@app.route("/api/notes/<int:note_id>", methods=["PUT"])
def update_note(note_id: int):
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("content"), str):
        return jsonify({"error": "content must be a string"}), 400

    content = data["content"]
    if len(content.encode("utf-8")) > MAX_NOTE_BYTES:
        return jsonify({"error": "Note exceeds maximum size limit"}), 413

    db = get_db()
    row = db.execute(
        "SELECT id, filename FROM notes WHERE id = ?",
        (note_id,),
    ).fetchone()
    if row is None:
        return jsonify({"error": "Note not found"}), 404

    file_path = note_file_path(note_id)
    atomic_write_text(file_path, content)

    updated_at = now_iso()
    db.execute(
        "UPDATE notes SET updated_at = ? WHERE id = ?",
        (updated_at, note_id),
    )
    db.commit()

    return jsonify(
        {
            "id": row["id"],
            "filename": row["filename"],
            "updated_at": updated_at,
        }
    )


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
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
