# Project Overview

## Purpose

`web-npp` is a minimal, self-hosted web Markdown notes application inspired by lightweight desktop text editors (such as Notepad++). It provides a fast, zero-build browser workspace backed by plain `.md` files on disk and a single-table SQLite index, designed to run comfortably on a low-resource server (1 CPU core / 1 GB RAM VPS).

## Core Capabilities (Implemented)

- **File-backed Markdown notes:** Every note is stored as an individual UTF-8 `.md` file on the server (`<NOTES_DIR>/<id>.md`), indexed by a lightweight SQLite database (`<NOTES_DIR>/notes.db`) storing only `id`, display `filename`, `path`, and ISO-8601 UTC `updated_at`.
- **Sidebar & instant search:** Left sidebar lists all notes sorted newest-first with formatted modification timestamps, client-side substring filtering by name, `+ New Note`, and one-click `.zip` export.
- **Multi-tab workspace:** Tab strip above the editor supports opening multiple notes simultaneously, instant in-memory switching via per-tab `CodeMirror.Doc` instances (preserving independent Undo/Redo history, cursor position, and scroll positions), tab closing (`×` or middle-click, keeping the note in the sidebar), `+` new tab creation, and `localStorage` tab persistence.
- **Split-pane CodeMirror 5 editor & editable live preview:**
  - **Left pane (Markdown source):** CodeMirror 5 (`markdown` mode) with line numbers, line wrapping, light Markdown syntax styling, smart list continuation (`Enter`), 2-space `Tab`/`Shift+Tab` indent/outdent, selective bracket auto-closing (`()[]{}`` `), formatting shortcuts (`Ctrl/Cmd+B`, `I`, `K`), URL-over-selection paste, and `/` block insertion menu.
  - **Right pane (editable live preview):** Live sanitized HTML rendering (`marked` + `DOMPurify`) with `contenteditable="true"` direct editing, two-way synchronization back to Markdown via `TurndownService` + GFM plugin, clickable task-list checkboxes, `/` block insertion menu, and interactive tables (`+` add column/row and per-column types: Text, Number, Currency, Checkbox, Date).
  - **Responsive pane visibility:** Side-by-side 50/50 panes on viewports `>= 900px` with independent **Hide/Show sidebar**, **Hide/Show editor**, and **Hide/Show preview** buttons; single-pane **Edit / Preview** switching on viewports `< 900px`.
- **Autosave & ZIP export:** Debounced autosave (`800ms` after typing stops), immediate save on tab switch/close/export, `keepalive` flush on `pagehide`, and `/api/export` streaming a `.zip` of all notes named after their database `filename` (`<filename>.md`).

## Technology Stack

| Layer | Technology | Version / Pin | Purpose |
| --- | --- | --- | --- |
| Backend | Python + Flask | `flask>=3.0,<4.0` (tested on Python 3.14, Flask 3.1.3) | HTTP routing, JSON API, static file serving, ZIP export |
| WSGI Server (prod) | Gunicorn | `gunicorn>=22.0,<24.0` | Multi-worker threaded production server behind Caddy |
| Database | SQLite (`sqlite3` stdlib) | Python stdlib (WAL mode) | Metadata index (`notes` table) |
| Frontend | Single-file HTML + CSS + vanilla JS | ES2020+ (no build step) | Entire client application (`static/index.html`) |
| Source Editor | CodeMirror 5 | `5.65.16` (vendored) | Markdown editing, line numbers, Undo/Redo, hints |
| Markdown → HTML | `marked` | `18.2.1` (vendored) | GFM parsing with line breaks |
| HTML Sanitizer | `DOMPurify` | `3.4.18` (vendored) | Mandatory XSS sanitization before `innerHTML` |
| HTML → Markdown | `turndown` + `turndown-plugin-gfm` | `7.2.5` / `1.0.2` (vendored) | Two-way sync from editable preview to Markdown |

All frontend libraries are vendored locally under `static/vendor/`. No external CDN requests are made at runtime (except user-authored Markdown `<img>` URLs or external links clicked by the user).

## Design Philosophy & Explicit Constraints

- **Zero build pipeline:** No Node.js, npm, bundler, transpiler, or frontend framework. Editing `static/index.html` takes effect immediately on browser refresh.
- **Minimal server footprint:** Single-file Flask backend (`app.py`, 275 lines), single-file SQLite database, plain `.md` files that can be backed up or inspected directly with standard OS tools.
- **No built-in authentication:** Access control is intentionally delegated to the network/reverse-proxy layer (e.g., Caddy basic auth, VPN, or firewall).
- **Non-goals (not implemented by design):** Multi-user accounts, folders/tags, note version history, syntax-highlighted code blocks in preview, theme/settings menus, or formatting toolbars.
