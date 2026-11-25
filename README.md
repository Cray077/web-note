# web-note

A minimal, self-hosted Markdown notes web application inspired by lightweight desktop text editors like Notepad++. Built with a single-file Flask backend, a zero-build vanilla JS/CSS frontend, plain UTF-8 `.md` files on disk, and a single-table SQLite index — designed to run comfortably on a low-resource server (1 CPU core / 1 GB RAM VPS).

## Features

- **Real-time live updates (WebSocket):** All note operations (list, load, create, save) run over a persistent WebSocket (`/ws`). Changes and new notes are broadcast live to all other connected clients with automatic reconnection and resync.
- **Plain Markdown storage:** Notes are saved atomically as standard UTF-8 GFM `.md` files (`<NOTES_DIR>/<id>.md`), indexed by a lightweight SQLite database (`notes.db` in WAL mode).
- **Multi-tab workspace:** Open multiple notes simultaneously with instant tab switching, independent Undo/Redo history, preserved cursor and scroll positions, `×` / middle-click tab closing (keeps the note in the sidebar and on disk), and `localStorage` tab persistence.
- **Two-way split editor & editable live preview:**
  - **Markdown source (CodeMirror 5):** Line numbers, line wrapping, smart list/quote continuation on `Enter`, 2-space `Tab`/`Shift+Tab` indent/outdent, selective bracket/backtick auto-closing, formatting shortcuts (`Ctrl/Cmd+B`, `I`, `K`), and paste-URL-over-selection linking.
  - **Editable live preview:** Live XSS-sanitized HTML rendering (`marked` + `DOMPurify`) with direct `contenteditable` editing synced back to clean GFM via `Turndown`, plus clickable task-list checkboxes.
- **`/` slash command menu:** Available in both the source editor and the live preview for inserting headings (`H1`–`H3`), bullet/numbered/task lists, quotes, code blocks, tables, dividers, links, and images.
- **Image upload & in-preview editing:** Upload images via `/image`, clipboard paste (`Ctrl/Cmd+V`), or drag-and-drop (stored under `user-images/<username>/`, served at `/images/<username>/<file>`, default `user1`). Hover any image in the live preview to drag-resize, flip (horizontal/vertical), rotate (±90°), or open the built-in canvas editor to resize, transform, and add freehand scribbles — saved atomically and synced live to connected clients.
- **Interactive typed tables:** Add rows and columns directly in the live preview with `+` buttons, navigate cells with `Tab` / `Enter`, and assign per-column types (**Text**, **Number**, **Currency**, **Checkbox**, **Date**).
- **Responsive collapsible layout:** Independent **Hide/Show sidebar**, **Hide/Show editor**, and **Hide/Show preview** controls on desktop (`>= 900px`), and single-pane **Edit / Preview** switching on smaller screens.
- **Sidebar search, inline rename, autosave & export:** Instant client-side note filtering, inline note renaming directly in the sidebar (via the `✎` button or double-clicking a note name, synced live across open tabs and connected clients), fast debounced autosave (`350ms` debounce / `1000ms` max-wait during continuous typing) with `pagehide` unload flush, and one-click `.zip` export of all notes and uploaded images.
- **Zero-build & self-contained:** No Node.js, npm, bundler, or external CDN requests. All frontend dependencies are pinned and vendored locally under `static/vendor/`.

## Tech Stack

| Layer | Technology | Purpose |
| --- | --- | --- |
| Backend | Python 3.10+, Flask (`flask>=3.0,<4.0`), `flask-sock>=0.7,<1.0` | WebSocket live sync (`/ws`), static file serving, atomic file I/O, `.zip` export |
| Production WSGI | Gunicorn (`gunicorn>=22.0,<24.0`) | Single-worker threaded WSGI server (`-w 1 -k gthread --threads 64`) behind a reverse proxy |
| Metadata Index | SQLite (`sqlite3` stdlib, WAL mode) | Lightweight `notes` metadata table (`id`, `filename`, `path`, `updated_at`) |
| Frontend | Single-file HTML / CSS / vanilla JS | Entire SPA in `static/index.html` with zero build step |
| Vendored Libraries | CodeMirror `5.65.16`, `marked 18.2.1`, `DOMPurify 3.4.18`, `turndown 7.2.5`, `turndown-plugin-gfm 1.0.2` | Markdown editing, rendering, sanitization, and HTML → Markdown sync |

## Quick Start

### Prerequisites

- **Python 3.10+**
- No Node.js or frontend build tools required.

### Linux / macOS

```bash
git clone https://github.com/Cray077/web-note.git
cd web-note
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
NOTES_DIR=./data PORT=8000 .venv/bin/python app.py
```

### Windows (PowerShell)

> Note: `gunicorn` is Unix-only, so install `flask` and `flask-sock` directly for local Windows development.

```powershell
git clone https://github.com/Cray077/web-note.git
cd web-note
python -m venv .venv
.venv\Scripts\python -m pip install flask flask-sock
$env:NOTES_DIR = ".\data"
$env:PORT = "8000"
.venv\Scripts\python app.py
```

Open `http://127.0.0.1:8000` in your browser.

### Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `NOTES_DIR` | `/var/notes` | Directory storing `notes.db` and `<id>.md` files (created automatically if missing) |
| `IMAGES_DIR` | `./user-images` | Directory storing uploaded images organized per user (`<IMAGES_DIR>/<username>/<file>`) |
| `DEFAULT_USER` | `user1` | Default username folder used for image uploads until user accounts are added |
| `PORT` | `8000` | Port used when running `python app.py` directly (ignored by Gunicorn, which uses `-b`) |

## Production Deployment

Example setup for a Linux VPS behind [Caddy](https://caddyserver.com/):

1. Create and assign ownership of the notes directory:
   ```bash
   sudo mkdir -p /var/notes && sudo chown <app-user> /var/notes
   ```
2. Install dependencies into a virtual environment:
   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
3. Run the app with Gunicorn (recommended under `systemd`, using `-w 1` so all connected WebSocket clients share the same process for live broadcasts):
   ```bash
   .venv/bin/gunicorn -w 1 -k gthread --threads 64 -b 127.0.0.1:8000 app:app
   ```
4. Proxy `127.0.0.1:8000` over HTTPS with Caddy (Caddy proxies WebSocket upgrades automatically via `reverse_proxy 127.0.0.1:8000`).

> **Security note:** `web-note` intentionally includes **no built-in authentication**. If exposing it beyond localhost, protect it at the network or reverse-proxy layer (for example, Caddy `basic_auth`, a VPN such as Tailscale, or firewall rules).

> **Backups:** Back up your `NOTES_DIR` directory periodically. Because SQLite runs in WAL mode, use `sqlite3 /var/notes/notes.db ".backup '/path/to/backup.db'"` or copy `notes.db`, `notes.db-wal`, and `notes.db-shm` together alongside all `*.md` files.

## Keyboard Shortcuts & Slash Commands

| Action | Shortcut / Trigger |
| --- | --- |
| Bold | `Ctrl/Cmd + B` |
| Italic | `Ctrl/Cmd + I` |
| Insert link | `Ctrl/Cmd + K` (or paste a URL over selected text in the editor) |
| Open link in preview | `Click` (use `Alt + Click` to place caret and edit link text) |
| Indent / outdent | `Tab` / `Shift + Tab` |
| Insert block menu | Type `/` at line start or after whitespace |
| Navigate table cells (preview) | `Tab` / `Shift + Tab` / `Enter` |

## Endpoints & WebSocket Protocol

### HTTP Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/` | Serve the web application (`static/index.html`) |
| `GET` | `/images/<username>/<filename>` | Serve an uploaded user image (`PNG`, `JPEG`, `GIF`, `WebP`) |
| `GET` | `/api/export` | Download all notes and uploaded images (`images/<username>/...`) as `notes.zip` |

### WebSocket (`/ws`)

All note CRUD, image uploads, and live broadcasts happen as JSON messages over `/ws`:

| Direction | Message `type` | Description |
| --- | --- | --- |
| Client → Server | `list_notes` | Request all note metadata (`notes_list` reply) |
| Client → Server | `create_note` | Create a note (`{"filename": "..."}`); replies and broadcasts `note_created` |
| Client → Server | `get_note` | Fetch note metadata and Markdown content (`note_content` reply) |
| Client → Server | `update_note` | Atomically save Markdown content (max 5 MB); replies `note_saved` and broadcasts `note_updated` |
| Client → Server | `rename_note` | Rename a note (`{"id": 5, "filename": "..."}`); replies and broadcasts `note_renamed` |
| Client → Server | `upload_image` | Upload or replace a base64 image (max 10 MB); replies `image_uploaded` and broadcasts `image_updated` on edits |
| Client → Server | `ping` | Keepalive check (`pong` reply) |
| Server → Clients | `note_created` / `note_updated` / `note_renamed` / `image_updated` | Live broadcast pushed to all other connected clients |

See [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) for full message schemas, limits, and error formats.

## Project Structure

```text
web-note/
├── app.py                   # Single-file Flask backend, SQLite WAL setup, atomic writes, ZIP export
├── requirements.txt         # Python dependencies (flask, gunicorn)
├── static/
│   ├── index.html           # Complete single-page frontend (HTML, CSS, vanilla JS)
│   └── vendor/              # Locally vendored JS/CSS libraries (CodeMirror 5, marked, DOMPurify, Turndown)
├── docs/                    # Architecture, API, database schema, setup, and conventions docs
└── data/                    # (Gitignored) Local development notes directory when NOTES_DIR=./data
```

## Documentation

Detailed technical documentation lives in [`docs/`](docs/):

- [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) — Goals, capabilities, and design constraints
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — System design, two-way editor/preview sync, and concurrency
- [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) — Complete HTTP endpoint documentation
- [`docs/DATABASE_SCHEMA.md`](docs/DATABASE_SCHEMA.md) — SQLite schema and storage invariants
- [`docs/DEVELOPMENT_SETUP.md`](docs/DEVELOPMENT_SETUP.md) — Local development, deployment, and smoke tests
- [`docs/COMPONENTS.md`](docs/COMPONENTS.md) — Backend and frontend subsystem map
- [`docs/DEVELOPMENT_STATUS.md`](docs/DEVELOPMENT_STATUS.md) — Current status and known limitations

## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).
