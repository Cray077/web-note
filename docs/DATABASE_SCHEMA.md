# Database Schema

## Engine & Configuration

- **Engine:** SQLite 3 via Python's built-in `sqlite3` module (`app.py:3`).
- **Database file path:** `<NOTES_DIR>/notes.db`, resolved by `get_db_path()` (`app.py:27-28`), where `NOTES_DIR` defaults to `/var/notes` (`app.py:16`).
- **Journal mode:** `PRAGMA journal_mode=WAL;` set during `init_db()` (`app.py:42`) for concurrent read/write support across Gunicorn workers and threads.
- **Lock timeout:** `timeout=30.0` seconds on all connections (`app.py:40`, `app.py:62`).
- **Row access:** `conn.row_factory = sqlite3.Row` on request connections (`app.py:63`).
- **Lifecycle:** Lazy one-time initialization per configured `NOTES_DIR` guarded by `_init_lock` and `_initialized_dirs` (`app.py:19-56`). Connections are scoped per Flask request via `flask.g.db` (`get_db()`, `app.py:59-65`) and closed by `@app.teardown_appcontext` (`close_db()`, `app.py:68-72`).

## Tables

There is a single application table, `notes` (plus SQLite's internal `sqlite_sequence` table created automatically because of `AUTOINCREMENT`).

### `notes` (`app.py:43-52`)

```sql
CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    filename   TEXT NOT NULL,
    path       TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

| Column | SQLite Type | Constraints | Semantics & Format |
| --- | --- | --- | --- |
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Server-assigned monotonic integer ID. Used in API URLs (`/api/notes/<id>`) and to build the on-disk filename `<id>.md`. Never reused after deletions (if deletion is ever added). |
| `filename` | `TEXT` | `NOT NULL` | User-facing display name (trimmed, 1–255 chars enforced in `create_note()` at `app.py:154-158`). Duplicate display names are permitted. Used in the sidebar, tab strip, document title, and ZIP export entry naming. Never used in disk paths. |
| `path` | `TEXT` | `NOT NULL` | Recorded absolute filesystem path to the note file (e.g., `/var/notes/12.md` on Linux or `C:\...\data\12.md` on Windows). Written during `create_note()` (`app.py:169`). |
| `updated_at` | `TEXT` | `NOT NULL` | UTC ISO-8601 timestamp with microsecond precision and `Z` suffix produced by `now_iso()` (`app.py:75-76`), e.g., `2026-11-19T13:05:12.123456Z`. Lexicographically sortable. |

## Relationships, Constraints & Indexes

- **Relationships:** None (single-table design; no users, folders, tags, or revisions).
- **Indexes:** Only the implicit `INTEGER PRIMARY KEY` B-tree index on `id`. There is no secondary index on `updated_at`; for a personal notes collection (hundreds to low thousands of notes), full-table sorting by `ORDER BY updated_at DESC, id DESC` is sub-millisecond.
- **Uniqueness:** `filename` is intentionally **not** `UNIQUE`. Two notes may share the same display name; `safe_zip_name()` (`app.py:110-128`) deduplicates collisions on export (`Todo List.md`, `Todo List (2).md`).

## Important Storage Invariants

1. **Content does not live in SQLite:** Note text lives exclusively in `<NOTES_DIR>/<id>.md`.
2. **`path` column vs. runtime resolution:** While `create_note()` stores `str(note_file_path(note_id))` in the `path` column, `get_note()`, `update_note()`, and `export_notes()` all recompute the disk path at runtime via `note_file_path(note_id)` (`app.py:192`, `226`, `257`). This means:
   - Path traversal is structurally impossible even if the `path` column were manually altered.
   - Moving `NOTES_DIR` to a different directory works for reads/writes/exports immediately, though the stored `path` string in `notes.db` would retain the old directory prefix unless updated.
3. **Missing `.md` files on disk:** If a row exists in `notes` but its `<id>.md` file is missing from disk, `get_note()` returns `content: ""` (`app.py:195-196`) and `export_notes()` writes `b""` (`app.py:260-261`) rather than raising a 500 error. The next `PUT` recreates `<id>.md` atomically.
4. **Two-step `INSERT` + `UPDATE` on creation (`app.py:162-174`):** `create_note()` inserts with `path = ''` to obtain `cursor.lastrowid`, computes `note_file_path(note_id)`, updates `path`, writes the empty `.md` file atomically, and only then calls `db.commit()` (rolling back on exception).

## Query Inventory (`app.py`)

| Endpoint / Function | SQL Statement |
| --- | --- |
| `list_notes` (`app.py:144-146`) | `SELECT id, filename, updated_at FROM notes ORDER BY updated_at DESC, id DESC` |
| `create_note` (`app.py:163-169`) | `INSERT INTO notes (filename, path, updated_at) VALUES (?, '', ?)` followed by `UPDATE notes SET path = ? WHERE id = ?` |
| `get_note` (`app.py:185-188`) | `SELECT id, filename, updated_at FROM notes WHERE id = ?` |
| `update_note` (`app.py:219-233`) | `SELECT id, filename FROM notes WHERE id = ?` followed by `UPDATE notes SET updated_at = ? WHERE id = ?` |
| `export_notes` (`app.py:248-250`) | `SELECT id, filename FROM notes ORDER BY updated_at DESC, id DESC` |
