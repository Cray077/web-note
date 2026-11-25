# API & WebSocket Reference

All endpoints are defined in `app.py`. Note listing, loading, creation, saving, and real-time broadcasts run over a persistent WebSocket (`/ws`). HTTP routes are reserved for serving the SPA (`GET /`), static vendor assets (`/static/...`), and binary `.zip` archive download (`GET /api/export`). There is no built-in authentication layer.

## Endpoint Summary

| Protocol / Method | Route | Handler (`app.py`) | Purpose |
| --- | --- | --- | --- |
| `GET` | `/` | `index` | Serve the single-page app (`static/index.html`) |
| `GET` | `/static/<path>` | Flask built-in | Serve vendored JS/CSS assets under `static/` |
| `WS` | `/ws` | `ws_endpoint` | Bidirectional JSON WebSocket for note CRUD, image uploads & live updates |
| `GET` | `/images/<username>/<filename>` | `serve_user_image` | Serve an uploaded user image from `<IMAGES_DIR>/<username>/<filename>` |
| `GET` | `/api/export` | `export_notes` | Download all notes and uploaded images as a single `.zip` archive |

Note: There is currently **no** delete operation.

---

## Global Limits & Error Format

- **WebSocket message / request body limit:** `MAX_WS_MESSAGE_BYTES = 16 MiB`.
- **Note content limit:** `MAX_NOTE_BYTES = 5 * 1024 * 1024` (5 MB UTF-8 encoded).
- **Image upload limit:** `MAX_IMAGE_BYTES = 10 * 1024 * 1024` (10 MB decoded binary; PNG, JPEG, GIF, WebP verified by magic bytes).
- **Filename length limit:** `MAX_FILENAME_LEN = 255` characters after `.strip()`.
- **WebSocket keepalive:** `SOCK_SERVER_OPTIONS = {"ping_interval": 25}` sends WebSocket ping frames every 25 seconds.
- **Error response message (WebSocket):**
  ```json
  {"type": "error", "req_id": "4", "error": "<human-readable message>", "code": 400}
  ```
  (`req_id` is included whenever the client sent one in the request.)

---

## WebSocket Protocol (`WS /ws`)

All frames are UTF-8 JSON objects with a `"type"` field. Client requests may include an arbitrary `"req_id"` echoed back on the matching response. Unsolicited live broadcasts omit `"req_id"` and are pushed to all connected clients **except** the sender.

### `list_notes`

- **Client → Server:**
  ```json
  {"type": "list_notes", "req_id": "1"}
  ```
- **Server → Client (`notes_list`):**
  ```json
  {
    "type": "notes_list",
    "req_id": "1",
    "notes": [
      {"id": 4, "filename": "TODO", "updated_at": "2026-11-25T14:30:00.123456Z"}
    ]
  }
  ```

### `create_note`

- **Client → Server:**
  ```json
  {"type": "create_note", "req_id": "2", "filename": "Meeting Notes"}
  ```
- **Validation:** `filename` must be a `str` whose trimmed length is `1..255` characters (`code: 400` otherwise).
- **Server → Sender (`note_created`):**
  ```json
  {
    "type": "note_created",
    "req_id": "2",
    "note": {"id": 5, "filename": "Meeting Notes", "updated_at": "2026-11-25T14:31:00.654321Z"}
  }
  ```
- **Server → Other Clients (live broadcast):**
  ```json
  {
    "type": "note_created",
    "note": {"id": 5, "filename": "Meeting Notes", "updated_at": "2026-11-25T14:31:00.654321Z"}
  }
  ```

### `get_note`

- **Client → Server:**
  ```json
  {"type": "get_note", "req_id": "3", "id": 5}
  ```
- **Server → Client (`note_content`):**
  ```json
  {
    "type": "note_content",
    "req_id": "3",
    "note": {
      "id": 5,
      "filename": "Meeting Notes",
      "updated_at": "2026-11-25T14:31:00.654321Z",
      "content": "# Agenda\n\n- [ ] Review docs\n"
    }
  }
  ```
- **Errors:** `code: 400` (`Invalid note id`), `code: 404` (`Note not found`). If `<id>.md` is missing on disk while the DB row exists, returns `content: ""`.

### `update_note`

Atomically replaces `<NOTES_DIR>/<id>.md` (temp file + `fsync` + `os.replace`, serialized per note ID via `_get_note_lock`), updates `notes.updated_at`, replies to the sender, and broadcasts the updated note content to all other connected clients.

- **Client → Server:**
  ```json
  {"type": "update_note", "req_id": "4", "id": 5, "content": "# Agenda\n\n- [x] Review docs\n"}
  ```
- **Server → Sender (`note_saved`):**
  ```json
  {
    "type": "note_saved",
    "req_id": "4",
    "note": {"id": 5, "filename": "Meeting Notes", "updated_at": "2026-11-25T14:32:12.000123Z"}
  }
  ```
- **Server → Other Clients (live broadcast):**
  ```json
  {
    "type": "note_updated",
    "note": {
      "id": 5,
      "filename": "Meeting Notes",
      "updated_at": "2026-11-25T14:32:12.000123Z",
      "content": "# Agenda\n\n- [x] Review docs\n"
    }
  }
  ```
- **Errors:** `code: 400` (`Invalid note id` / `content must be a string`), `code: 404` (`Note not found`), `code: 413` (`Note exceeds maximum size limit`).

### `rename_note`

Updates `notes.filename` in SQLite without touching `<NOTES_DIR>/<id>.md` on disk, replies to the sender, and broadcasts `note_renamed` to all other connected clients.

- **Client → Server:**
  ```json
  {"type": "rename_note", "req_id": "5", "id": 5, "filename": "Sprint Planning"}
  ```
- **Validation:** `id` must be a positive integer (`code: 400`), `filename` must be a `str` whose trimmed length is `1..255` characters (`code: 400`), and the note must exist (`code: 404`).
- **Server → Sender (`note_renamed`):**
  ```json
  {
    "type": "note_renamed",
    "req_id": "5",
    "note": {"id": 5, "filename": "Sprint Planning", "updated_at": "2026-11-25T14:32:12.000123Z"}
  }
  ```
- **Server → Other Clients (live broadcast):**
  ```json
  {
    "type": "note_renamed",
    "note": {"id": 5, "filename": "Sprint Planning", "updated_at": "2026-11-25T14:32:12.000123Z"}
  }
  ```

### `upload_image`

Decodes a base64 image (or data URL), validates its magic bytes (`PNG`, `JPEG`, `GIF`, `WebP`) and 10 MB size limit, writes it atomically to `<IMAGES_DIR>/<username>/<filename>`, and replies with the image URL (`/images/<username>/<filename>`). When `replace` is provided for editing an existing local image, overwrites it atomically and broadcasts `image_updated` to all other connected clients.

- **Client → Server:**
  ```json
  {"type": "upload_image", "req_id": "6", "data": "data:image/png;base64,...", "username": "user1", "replace": "a1b2c3.png"}
  ```
- **Server → Sender (`image_uploaded`):**
  ```json
  {
    "type": "image_uploaded",
    "req_id": "6",
    "image": {"username": "user1", "filename": "a1b2c3.png", "url": "/images/user1/a1b2c3.png", "v": "1732546800123"}
  }
  ```
- **Server → Other Clients (on replace, live broadcast `image_updated`):**
  ```json
  {
    "type": "image_updated",
    "image": {"username": "user1", "filename": "a1b2c3.png", "url": "/images/user1/a1b2c3.png", "v": "1732546800123"}
  }
  ```
- **Errors:** `code: 400` (invalid username/filename/base64 or unsupported format), `code: 413` (`Image exceeds maximum size limit (10 MB)`).

### `ping`

- **Client → Server:** `{"type": "ping", "req_id": "p1"}`
- **Server → Client:** `{"type": "pong", "req_id": "p1"}`

---

## HTTP Endpoints

### `GET /`

Serves `static/index.html` (`200 OK`, `text/html; charset=utf-8`).

### `GET /images/<username>/<filename>`

Serves an uploaded image from `<IMAGES_DIR>/<username>/<filename>` after validating `username` (`^[a-zA-Z0-9_-]{1,64}$`), `filename` (`^[a-zA-Z0-9_-]{1,128}\.(png|jpg|jpeg|webp|gif)$`), and resolved directory containment. Sets `Cache-Control: no-cache` and sniffs magic bytes for `Content-Type`.

### `GET /api/export`

Streams a `ZIP_DEFLATED` archive containing every note in `notes.db` (ordered newest-first) plus all uploaded user images under `images/<username>/<filename>`, using a `SpooledTemporaryFile(max_size=10 MB)` buffer.

- **Archive member naming (`safe_zip_name()`):**
  - Replaces `[\\/:*?"<>|\x00-\x1f]` with `_`, trims whitespace and leading/trailing `.` characters (falls back to `note-<id>` if empty).
  - Appends `.md` without doubling `.md.md` when the display name already ends with `.md` (case-insensitive).
  - Deduplicates case-insensitive collisions with ` (2)`, ` (3)`, etc.
- **Response (`200 OK`):** `Content-Type: application/zip`, `Content-Disposition: attachment; filename=notes.zip`.
