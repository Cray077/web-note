# AGENTS.md

Guidance and persistent context for AI coding agents working on `web-npp`.

## Project Summary

`web-npp` is a minimal, self-hosted Markdown notes web app:
- **Backend:** Single-file Flask + `flask-sock` app (`app.py`) backed by SQLite (`<NOTES_DIR>/notes.db`, WAL mode) for metadata and individual UTF-8 `.md` files (`<NOTES_DIR>/<id>.md`) for content, using WebSocket (`/ws`) for note CRUD and real-time live broadcasts across clients.
- **Frontend:** Zero-build single-page app (`static/index.html`, 2,599 lines) with vanilla JS/CSS and locally vendored libraries (`CodeMirror 5.65.16`, `marked 18.2.1`, `DOMPurify 3.4.18`, `turndown 7.2.5`, `turndown-plugin-gfm 1.0.2`).
- **UI capabilities:** Sidebar with client-side search & `.zip` export, multi-tab bar (`×` closes tab only, `+` creates new note), collapsible sidebar/editor/preview panes, CodeMirror 5 source editor with smart Markdown typing, and an editable live preview with two-way Markdown sync, `/` slash commands, and interactive typed tables.

## Documentation Map

Read the relevant docs in `docs/` before making changes:

- [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) — Purpose, capabilities, tech stack, and design philosophy.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — System architecture, two-way editor/preview sync loop, per-tab `CodeMirror.Doc` model, concurrency, and security boundaries.
- [`docs/DIRECTORY_STRUCTURE.md`](docs/DIRECTORY_STRUCTURE.md) — Complete file layout, entry points, and required vendor script load order.
- [`docs/DATABASE_SCHEMA.md`](docs/DATABASE_SCHEMA.md) — SQLite `notes` table DDL, WAL configuration, query inventory, and storage invariants.
- [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) — HTTP routes, validation rules, error formats, and `.zip` export contract.
- [`docs/COMPONENTS.md`](docs/COMPONENTS.md) — Detailed map of backend functions (`app.py`) and frontend subsystems (`static/index.html`).
- [`docs/CODING_CONVENTIONS.md`](docs/CODING_CONVENTIONS.md) — Language conventions, DOM/XSS rules, and sync invariants.
- [`docs/DEVELOPMENT_SETUP.md`](docs/DEVELOPMENT_SETUP.md) — Local Windows/Linux setup, env vars (`NOTES_DIR`, `PORT`), production Gunicorn/Caddy deployment, and smoke tests.
- [`docs/DEVELOPMENT_STATUS.md`](docs/DEVELOPMENT_STATUS.md) — Implemented features, known limitations, technical debt, and uncertainties.
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — Explicitly deferred optional features, maintenance candidates, and non-goals.

## Non-Negotiable Constraints

1. **Stay minimal & zero-build:** Do not add bundlers, npm, TypeScript, or frontend frameworks unless explicitly requested.
2. **No external CDNs:** All browser libraries must live under `static/vendor/` at pinned versions.
3. **Never build disk paths from user input:** All file paths in `app.py` must go through `note_file_path(note_id)` (`<NOTES_DIR>/<id>.md`) and atomic writes through `atomic_write_text()`.
4. **Always sanitize rendered Markdown:** Every `marked.parse()` output must pass through `DOMPurify.sanitize()` before touching `previewEl.innerHTML`.
5. **Preserve two-way sync invariants:**
   - Preview → CodeMirror updates **must** use `origin = "preview"` so `cm.on("change")` skips `schedulePreview()` (avoiding caret/loop bugs).
   - Remote WebSocket updates → CodeMirror **must** use `origin = "remote"` and programmatic loads (`setValue` / `swapDoc`) must **never** mark `dirty = true` or trigger autosave (preventing echo loops).
   - Flush pending preview edits (`flushPreviewSync()`) before saving, switching/closing tabs, toggling layout, or unloading.
   - Any non-Markdown UI chrome placed inside `#preview` (e.g., table `+` buttons, column type badges) must have `contenteditable="false"` and be stripped by a Turndown rule so it never leaks into `.md` files.
6. **Keep `.md` files pure GFM:** Do not add proprietary syntax or migrate back to `.txt`.
7. **Closing a tab ≠ deleting a note:** `×` on a tab closes the tab only and keeps the note in the sidebar and on disk.

## Quick Commands

- **Run locally (Windows PowerShell):**
  ```powershell
  $env:NOTES_DIR = ".\data"
  .venv\Scripts\python app.py
  ```
- **Run in production (Linux):**
  ```bash
  .venv/bin/gunicorn -w 1 -k gthread --threads 64 -b 127.0.0.1:8000 app:app
  ```
- **Check clean working tree:** Ensure `data/` and `.venv/` remain gitignored (see `.gitignore`).
