# API Reference

All routes are defined in `app.py`. JSON endpoints consume and return `application/json` with UTF-8 encoding. There is no authentication layer; all routes are directly accessible over HTTP.

## Route Summary

| Method | Route | Handler (`app.py`) | Purpose |
| --- | --- | --- | --- |
| `GET` | `/` | `index` (`app.py:136`) | Serve the single-page app (`static/index.html`) |
| `GET` | `/static/<path>` | Flask built-in | Serve vendored JS/CSS assets under `static/` |
| `GET` | `/api/notes` | `list_notes` (`app.py:141`) | List all note metadata, newest first |
| `POST` | `/api/notes` | `create_note` (`app.py:150`) | Create a new note and empty `.md` file |
| `GET` | `/api/notes/<int:note_id>` | `get_note` (`app.py:182`) | Fetch note metadata and UTF-8 Markdown content |
| `PUT` | `/api/notes/<int:note_id>` | `update_note` (`app.py:208`) | Save note Markdown content atomically and bump `updated_at` |
| `GET` | `/api/export` | `export_notes` (`app.py:245`) | Download all notes as a single `.zip` archive |

Note: There are currently **no** `PATCH` / `DELETE` endpoints for renaming or deleting notes.

---

## Global Limits & Error Format

- **Request body limit:** `app.config["MAX_CONTENT_LENGTH"] = MAX_NOTE_BYTES + 1 MiB` (`6 MiB`, `app.py:17`). Exceeding this triggers `@app.errorhandler(413)` (`app.py:131-133`).
- **Note content limit:** `MAX_NOTE_BYTES = 5 * 1024 * 1024` (5 MB UTF-8 encoded, checked in `update_note` at `app.py:215-216`).
- **Filename length limit:** `MAX_FILENAME_LEN = 255` characters after `.strip()` (`app.py:13`, `156-158`).
- **Error response body:** All handled API errors return JSON of the shape:
  ```json
  {"error": "<human-readable message>"}
  ```

---

## Endpoint Details

### `GET /`

Serves `static/index.html` via `send_from_directory(app.static_folder, "index.html")`.

- **Response:** `200 OK`, `text/html; charset=utf-8`

---

### `GET /api/notes`

Returns metadata for all notes sorted newest-first (`ORDER BY updated_at DESC, id DESC`). Does not return note bodies or filesystem `path`.

- **Response (`200 OK`):**
  ```json
  [
    {
      "id": 4,
      "filename": "TODO",
      "updated_at": "2026-11-19T13:37:00.123456Z"
    }
  ]
  ```

---

### `POST /api/notes`

Creates a new note record in `notes.db` and atomically writes an empty `<id>.md` file.

- **Request body:**
  ```json
  {
    "filename": "Meeting Notes"
  }
  ```
- **Validation (`app.py:152-158`):**
  - `filename` must be a `str`; leading/trailing whitespace is trimmed.
  - Trimmed length must be `1..255` characters.
- **Success response (`201 Created`):**
  ```json
  {
    "id": 5,
    "filename": "Meeting Notes",
    "updated_at": "2026-11-19T14:00:00.654321Z"
  }
  ```
- **Error responses:**
  - `400 Bad Request`: `{"error": "filename must be a string"}` or `{"error": "filename must be between 1 and 255 characters"}`

---

### `GET /api/notes/<int:note_id>`

Reads note metadata from SQLite and UTF-8 content from `<NOTES_DIR>/<note_id>.md`. If the file is missing on disk while the DB row exists, returns `content: ""`.

- **Success response (`200 OK`):**
  ```json
  {
    "id": 5,
    "filename": "Meeting Notes",
    "updated_at": "2026-11-19T14:00:00.654321Z",
    "content": "# Agenda\n\n- [ ] Review docs\n"
  }
  ```
- **Error responses:**
  - `404 Not Found`: `{"error": "Note not found"}` (also returned automatically by Flask routing for non-integer IDs)

---

### `PUT /api/notes/<int:note_id>`

Atomically replaces `<NOTES_DIR>/<note_id>.md` with UTF-8 `content` (via temp file + `fsync` + `os.replace`) and updates `notes.updated_at` to current UTC time.

- **Request body:**
  ```json
  {
    "content": "# Agenda\n\n- [x] Review docs\n"
  }
  ```
- **Validation (`app.py:210-224`):**
  - Body must be a JSON object with string `content`.
  - `len(content.encode("utf-8")) <= 5 * 1024 * 1024`.
  - Note `note_id` must exist in `notes`.
- **Success response (`200 OK`):**
  ```json
  {
    "id": 5,
    "filename": "Meeting Notes",
    "updated_at": "2026-11-19T14:05:12.000123Z"
  }
  ```
- **Error responses:**
  - `400 Bad Request`: `{"error": "content must be a string"}`
  - `404 Not Found`: `{"error": "Note not found"}`
  - `413 Payload Too Large`: `{"error": "Note exceeds maximum size limit"}`

---

### `GET /api/export`

Streams a `ZIP_DEFLATED` archive containing every note in `notes.db`, ordered newest-first, using a `SpooledTemporaryFile(max_size=10 MB)` buffer (`app.py:252`).

- **Archive member naming (`safe_zip_name()`, `app.py:110-128`):**
  - Replaces `[\\/:*?"<>|\x00-\x1f]` with `_`, trims whitespace and leading/trailing `.` characters (falls back to `note-<id>` if empty).
  - Appends `.md` without doubling `.md.md` when the display name already ends with `.md` (case-insensitive).
  - Deduplicates case-insensitive collisions with ` (2)`, ` (3)`, etc. (e.g., `Todo List.md`, `Todo List (2).md`).
- **Response (`200 OK`):**
  - `Content-Type: application/zip`
  - `Content-Disposition: attachment; filename=notes.zip`
