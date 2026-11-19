# web-note

A minimal, self-hosted Markdown notes web application inspired by lightweight desktop text editors like Notepad++. Built with a single-file Flask backend, a zero-build vanilla JS/CSS frontend, plain UTF-8 `.md` files on disk, and a single-table SQLite index — designed to run comfortably on a low-resource server (1 CPU core / 1 GB RAM VPS).

## Features

- **Plain Markdown storage:** Notes are saved atomically as standard UTF-8 GFM `.md` files (`<NOTES_DIR>/<id>.md`), indexed by a lightweight SQLite database (`notes.db` in WAL mode).
- **Multi-tab workspace:** Open multiple notes simultaneously with instant tab switching, independent Undo/Redo history, preserved cursor and scroll positions, `×` / middle-click tab closing (keeps the note in the sidebar and on disk), and `localStorage` tab persistence.
- **Two-way split editor & editable live preview:**
  - **Markdown source (CodeMirror 5):** Line numbers, line wrapping, smart list/quote continuation on `Enter`, 2-space `Tab`/`Shift+Tab` indent/outdent, selective bracket/backtick auto-closing, formatting shortcuts (`Ctrl/Cmd+B`, `I`, `K`), and paste-URL-over-selection linking.
  - **Editable live preview:** Live XSS-sanitized HTML rendering (`marked` + `DOMPurify`) with direct `contenteditable` editing synced back to clean GFM via `Turndown`, plus clickable task-list checkboxes.
- **`/` slash command menu:** Available in both the source editor and the live preview for inserting headings (`H1`–`H3`), bullet/numbered/task lists, quotes, code blocks, tables, dividers, links, and images.
- **Interactive typed tables:** Add rows and columns directly in the live preview with `+` buttons, navigate cells with `Tab` / `Enter`, and assign per-column types (**Text**, **Number**, **Currency**, **Checkbox**, **Date**).
- **Responsive collapsible layout:** Independent **Hide/Show sidebar**, **Hide/Show editor**, and **Hide/Show preview** controls on desktop (`>= 900px`), and single-pane **Edit / Preview** switching on smaller screens.
- **Sidebar search, autosave & export:** Instant client-side note filtering, `800ms` debounced autosave with `pagehide` unload flush, and one-click `.zip` export of all notes.
- **Zero-build & self-contained:** No Node.js, npm, bundler, or external CDN requests. All frontend dependencies are pinned and vendored locally under `static/vendor/`.

## Tech Stack

| Layer | Technology | Purpose |
| --- | --- | --- |
| Backend | Python 3.10+ & Flask (`flask>=3.0,<4.0`) | HTTP API, static file serving, atomic file I/O, `.zip` export |
| Production WSGI | Gunicorn (`gunicorn>=22.0,<24.0`) | Multi-worker threaded WSGI server behind a reverse proxy |
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

> Note: `gunicorn` is Unix-only, so install `flask` directly for local Windows development.

```powershell
git clone https://github.com/Cray077/web-note.git
cd web-note
python -m venv .venv
.venv\Scripts\pip install flask
$env:NOTES_DIR = ".\data"
$env:PORT = "8000"
.venv\Scripts\python app.py
```

Open `http://127.0.0.1:8000` in your browser.

### Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `NOTES_DIR` | `/var/notes` | Directory storing `notes.db` and `<id>.md` files (created automatically if missing) |
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
3. Run the app with Gunicorn (recommended under `systemd`):
   ```bash
   .venv/bin/gunicorn -w 2 -k gthread --threads 4 -b 127.0.0.1:8000 app:app
   ```
4. Proxy `127.0.0.1:8000` over HTTPS with Caddy (or another reverse proxy).

> **Security note:** `web-note` intentionally includes **no built-in authentication**. If exposing it beyond localhost, protect it at the network or reverse-proxy layer (for example, Caddy `basic_auth`, a VPN such as Tailscale, or firewall rules).

> **Backups:** Back up your `NOTES_DIR` directory periodically. Because SQLite runs in WAL mode, use `sqlite3 /var/notes/notes.db ".backup '/path/to/backup.db'"` or copy `notes.db`, `notes.db-wal`, and `notes.db-shm` together alongside all `*.md` files.

## Keyboard Shortcuts & Slash Commands

| Action | Shortcut / Trigger |
| --- | --- |
| Bold | `Ctrl/Cmd + B` |
| Italic | `Ctrl/Cmd + I` |
| Insert link | `Ctrl/Cmd + K` (or paste a URL over selected text in the editor) |
| Open link in preview | `Ctrl/Cmd + Click` |
| Indent / outdent | `Tab` / `Shift + Tab` |
| Insert block menu | Type `/` at line start or after whitespace |
| Navigate table cells (preview) | `Tab` / `Shift + Tab` / `Enter` |

## API Overview

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/` | Serve the web application (`static/index.html`) |
| `GET` | `/api/notes` | List note metadata sorted newest-first |
| `POST` | `/api/notes` | Create a new note (`{"filename": "..."}`) |
| `GET` | `/api/notes/<id>` | Fetch note metadata and Markdown content |
| `PUT` | `/api/notes/<id>` | Atomically save Markdown content (`{"content": "..."}`, max 5 MB) |
| `GET` | `/api/export` | Download all notes as `notes.zip` |

See [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) for request/response schemas, limits, and error formats.

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
