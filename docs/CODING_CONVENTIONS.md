# Coding Conventions & Engineering Rules

These conventions are verified from `app.py` and `static/index.html` and should be followed by any contributor or AI agent extending this codebase.

## Architectural & Dependency Rules

1. **No build step or frontend framework:** All client code is plain HTML, CSS, and vanilla ES2020+ JavaScript inside `static/index.html`. Do not introduce npm, Vite/Webpack, React/Vue, or TypeScript compilation unless explicitly requested.
2. **No external CDNs:** Any third-party browser library must be vendored at a pinned version under `static/vendor/` and loaded via `/static/vendor/...`.
3. **Minimal backend:** Keep the Flask backend in `app.py` with only `flask` and `gunicorn` in `requirements.txt` (rely on Python's standard library for `sqlite3`, `zipfile`, `tempfile`, `pathlib`, `threading`, `datetime`).
4. **Pure `.md` storage:** All notes are `.md` files only. Never introduce proprietary Markdown extensions that break standard GFM readability — interactive features (like typed table columns) must serialize cleanly to standard GFM syntax.

## Python Conventions (`app.py`)

- **Formatting & typing:** Standard PEP 8, 4-space indentation, explicit return and parameter type annotations on helper functions (Python 3.10+ union syntax like `BaseException | None`, `set[str]`).
- **Naming:**
  - `UPPER_SNAKE_CASE` for module constants (`MAX_NOTE_BYTES`, `MAX_FILENAME_LEN`).
  - `snake_case` for functions and variables; leading underscore (`_init_lock`, `_initialized_dirs`) for module-private globals.
- **Database access:**
  - Always use parameterized SQL queries (`?` placeholders) — never string-interpolate values into SQL.
  - Access the per-request connection through `get_db()` so `init_db()` is guaranteed to have run and `close_db()` tears it down cleanly.
  - Wrap multi-step DB + file mutations in `try / except: db.rollback(); raise` (see `create_note()`, `app.py:162-174`).
- **Filesystem safety:**
  - Always resolve note paths via `note_file_path(note_id)`. Never build filesystem paths from user-supplied `filename` strings.
  - Always write files via `atomic_write_text()` (UTF-8, `newline=""`, sibling temp file + `fsync` + `os.replace`).
- **API responses:**
  - Return JSON consistently for both success and error responses (`{"error": "..."}` with appropriate HTTP status codes `400`, `404`, `413`).
  - Parse incoming JSON safely with `request.get_json(silent=True)` and explicitly validate types (`isinstance(..., str)`).

## Frontend Conventions (`static/index.html`)

- **Encapsulation:** Keep all JS inside the top-level IIFE `(() => { ... })();` with zero leaked globals.
- **Naming:**
  - `UPPER_SNAKE_CASE` for configuration constants (`AUTOSAVE_DELAY_MS`, `SLASH_ITEMS`, `COL_TYPES`).
  - `camelCase` for functions and variables; `*El` suffix for DOM element references (`previewEl`, `tabStripEl`); `*Btn` suffix for buttons (`newTabBtn`, `exportBtn`).
  - `kebab-case` for HTML IDs and CSS classes (`.table-add-row`, `#preview-slash-menu`).
- **DOM construction & XSS safety:**
  - Build dynamic UI elements (`renderSidebar`, `renderTabs`, slash menu items, table controls) with `document.createElement` + `textContent` + `DocumentFragment` — never interpolate untrusted note names into `innerHTML`.
  - **Every** write of Markdown-rendered HTML to `previewEl.innerHTML` **must** pass through `DOMPurify.sanitize(...)` first.
  - Any UI chrome injected into `#preview` (e.g., table `+` buttons, `.col-type-btn`) **must** set `contenteditable="false"` and be explicitly stripped by a Turndown rule (`tableUiIgnore`) so it never leaks into `.md` files.
- **Two-way sync discipline:**
  - Always pass `origin = "preview"` when updating CodeMirror from `#preview` so `cm.on("change")` does not re-render `#preview`.
  - Always call `flushPreviewSync()` before saving, switching/closing tabs, toggling panes, or unloading the page.
  - Never trigger autosave when `change.origin === "setValue"` or on `cm.swapDoc(...)`.
- **Event delegation:** Attach click/mousedown listeners to stable parent containers (`noteListEl`, `tabStripEl`, `previewEl`, `previewSlashMenuEl`, `colTypeMenuEl`) using `e.target.closest(...)` rather than binding individual listeners per dynamic node.
- **Focus preservation on buttons:** On popover/table buttons inside or adjacent to `contenteditable` (`previewSlashMenuEl`, `colTypeMenuEl`, `.table-add-row`, `.table-add-col`, `.col-type-btn`), handle actions on `mousedown` with `e.preventDefault()` so the editor/preview caret does not unexpectedly blur before the action runs.
- **CSS scoping:** Scope rendered Markdown rules under `.markdown` so they do not bleed into the sidebar, tab bar, or CodeMirror. Use `[hidden] { display: none !important; }` as the uniform visibility mechanism across JS toggles.
