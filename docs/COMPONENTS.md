# Components & Modules

This codebase has two application files (`app.py` and `static/index.html`). All backend helpers/routes live in `app.py`, and all frontend subsystems live inside a single IIFE in `static/index.html`.

---

## Backend (`app.py`)

| Symbol | Lines | Responsibility |
| --- | --- | --- |
| `MAX_NOTE_BYTES`, `MAX_FILENAME_LEN` | `12-13` | Payload limit (`5 MiB`) and filename limit (`255` chars) |
| `get_notes_dir()`, `get_db_path()` | `23-28` | Resolve `app.config["NOTES_DIR"]` and `<NOTES_DIR>/notes.db` |
| `init_db()` | `31-56` | Thread-safe lazy creation of `NOTES_DIR`, WAL mode, and `notes` table |
| `get_db()`, `close_db()` | `59-72` | Per-request SQLite connection stored on `flask.g.db` and closed on app context teardown |
| `now_iso()` | `75-76` | Current UTC ISO-8601 timestamp with `Z` suffix |
| `note_file_path(note_id)` | `79-86` | Builds `<NOTES_DIR>/<id>.md` with positive-int validation and directory containment check |
| `atomic_write_text(path, content)` | `89-107` | Writes UTF-8 (`newline=""`) to sibling `.tmp` file, calls `fsync`, atomically swaps via `os.replace` |
| `safe_zip_name(filename, note_id, used_lower)` | `110-128` | Sanitizes display name against Zip Slip, enforces `.md` extension, deduplicates collisions |
| `handle_too_large(_err)` | `131-133` | Flask `413` error handler returning JSON |
| `index()`, `list_notes()`, `create_note()`, `get_note()`, `update_note()`, `export_notes()` | `136-271` | HTTP route handlers (see `docs/API_REFERENCE.md`) |

---

## Frontend Subsystems (`static/index.html`)

### DOM Layout Map (`static/index.html:698-732`)

- **Sidebar (`#sidebar`):** Search input (`#search`), scrollable note list (`#note-list`), footer actions (`#new-note-btn`, `#export-btn`).
- **Editor Header (`.editor-header`):**
  - Left/center: scrollable tab strip (`#tab-strip`) + add tab button (`#new-tab-btn`).
  - Right (`.header-actions`): save status (`#save-status`), `#sidebar-toggle-btn`, `#editor-toggle-btn`, `#preview-toggle-btn`.
- **Workspace (`#workspace`) & Empty State (`#empty-state`):**
  - `#editor-pane`: hosts CodeMirror 5 instance (`cm`).
  - `#preview`: `contenteditable="true"` rendered Markdown pane (`.markdown`).
  - `#empty-state`: shown only when `openTabIds` is empty (`activeId === null`).
- **Floating Popovers (appended under `<body>`):**
  - `#preview-slash-menu`: live-preview `/` command menu.
  - `#col-type-menu`: table column-type selector popover.

### 1. Responsive Layout & Pane Visibility (`applyLayout`, `static/index.html:1155-1180`)
- Controlled by `wideQuery = window.matchMedia("(min-width: 900px)")` and state flags `sidebarVisible`, `wideEditorVisible`, `widePreviewVisible`, `narrowPreviewActive`.
- Wide (`>= 900px`): editor and preview sit 50/50 side-by-side (`#editor-toggle-btn` visible). Clicking `Hide editor` or `Hide preview` automatically re-shows the other pane if both would become hidden (`static/index.html:2538-2559`).
- Narrow (`< 900px`): `#editor-toggle-btn` is hidden; `#preview-toggle-btn` switches single-pane `Preview` / `Edit`. Below `640px`, `.app` stacks vertically (`static/index.html:464-473`).
- Only calls `renderPreview(cm.getValue())` when `#preview` transitions from hidden → visible so toggling the sidebar or editor never clobbers the live preview caret.

### 2. Sidebar & Client-Side Search (`renderSidebar`, `sortNotesNewestFirst`, `formatDate`)
- `static/index.html:1217-1284`: Filters `notes` in-memory by case-insensitive substring match against `#search.value`, renders `<li>` items with bold filename and `en-US` local timestamp (`Nov 19, 2026 8:57 PM`), highlights `note.id === activeId`.

### 3. Multi-Tab Manager (`selectNote`, `closeTab`, `renderTabs`, `saveTabsState`, `restoreTabsState`)
- `static/index.html:1351-1627`:
  - `openTabIds` (array of open IDs) + `tabDocs` (`Map` of `id → { doc: CodeMirror.Doc, editorScroll, previewScroll }`).
  - `selectNote(noteId)`: saves scroll and pending edits on current tab, then either swaps instantly via `cm.swapDoc(cached.doc)` or fetches `GET /api/notes/<id>` (guarded by monotonic `loadSeq` to drop stale responses).
  - `closeTab(noteId)`: flushes & saves if active, removes ID and deletes its `CodeMirror.Doc`, switches to neighbor tab or enters empty state (`activeId = null`).
  - Supports `×` click, middle-click (`auxclick` button `1`), horizontal wheel scrolling on `#tab-strip`, and `localStorage` persistence under `"notes.openTabs"`.

### 4. CodeMirror 5 Editor & Smart Typing (`static/index.html:983-1119`)
- Instantiated at `static/index.html:1058` with `mode: "markdown"`, `lineNumbers: true`, `lineWrapping: true`, `indentUnit: 2`, `tabSize: 2`, `autoCloseBrackets: { pairs: "()[]{}``", closeBefore: ")]}:;>", triples: "" }`.
- `extraKeys`:
  - `Enter`: `"newlineAndIndentContinueMarkdownList"` (`continuelist.js`)
  - `Tab` / `Shift-Tab`: 2-space indent/outdent on selections or list lines; inserts `"  "` otherwise
  - `Ctrl/Cmd-B` & `Ctrl/Cmd-I`: `wrap(cm, "**")` / `wrap(cm, "*")` (toggles off when already wrapped)
  - `Ctrl/Cmd-K`: `insertLink(cm)` → `[sel](url)` with `url` selected
- `paste` handler (`static/index.html:1096-1104`): pasting an `http(s)://` URL over selected text turns it into `[selection](url)`.
- `inputRead` handler (`static/index.html:1085-1093`): opens `cm.showHint({ hint: slashHint, completeSingle: false })` when `/` is typed via `+input` at line start or after whitespace.

### 5. Markdown Render & Sanitization Pipeline (`renderPreview`, `static/index.html:789-805`, `959-979`)
- Configures `marked.use({ gfm: true, breaks: true })`.
- `DOMPurify` `afterSanitizeAttributes` hook:
  - Adds `target="_blank" rel="noopener noreferrer"` to all `<a>` elements.
  - Removes any `<input>` that is not a disabled checkbox (blocks hand-typed raw `<input>`), then removes `disabled` and sets `contenteditable="false"` on genuine GFM task checkboxes so they are clickable in the live preview.
- `renderPreview(text)` sanitizes with `{ ADD_TAGS: ["input"], ADD_ATTR: ["type", "checked", "disabled", "align"] }`, preserves `previewEl.scrollTop`, and calls `enhanceTables(previewEl)`.

### 6. Editable Live Preview & Turndown Two-Way Sync (`static/index.html:807-956`, `1121-1153`, `2310-2487`)
- `TurndownService` configured with ATX `#` headings, `---` HR, `-` bullets, fenced code blocks, `*` / `**`, `br: ""`, and `turndownPluginGfm.gfm`.
- Custom Turndown rules:
  - `strikethrough`: emits `~~...~~` (overrides plugin's single `~`).
  - `tableUiIgnore` / `tableUiUnwrap`: strips `.col-type-btn`, `.table-add-col`, `.table-add-row` and unwraps `.table-wrap` / `.table-row-top`.
  - `tableCell`: serializes checkboxes as `[x]`/`[ ]`, date inputs as `YYYY-MM-DD`, and flattens cell newlines to spaces.
  - `fencedCodeBlock` + `extractCodeText(node)`: converts `<br>`, `<div>`, `<p>`, and text nodes inside `<pre>` into exact `\n` newlines (fixing `textContent` newline loss in `contenteditable`).
  - `listItem`: standard 1-space bullet/numbered markers and 2-space nested indentation.
- `previewToMarkdown(root)` preserves trailing empty `<p>` / `<div>` / `<br>` blocks so pressing `Enter` at the bottom of the preview adds a newline to the file immediately.
- Preview keyboard/mouse handlers:
  - `Ctrl/Cmd+B` / `I` / `K`, plain-text `paste`, `Ctrl/Cmd+Click` to open links, `Enter` inside `<pre>` inserts `<br>` (`insertLineBreak`), `Enter` / `Tab` inside table cells navigates rows/columns (adding a row at the end).

### 7. Shared Slash Command Menu (`SLASH_ITEMS`, `slashHint`, `applyPreviewSlashItem`)
- `static/index.html:1005-1054` (CodeMirror) and `1648-1930` (live preview).
- 12 shared items with keyword aliases (`filterSlashItems`): Heading 1–3 (`header`, `h1`–`h3`), Bullet list, Numbered list, Task list (`todo`), Quote, Code block (`block`), Table, Divider (`hr`), Link, Image (`img`).
- In live preview, `updatePreviewSlashMenu()` detects `/(^|\s)\/(\w*)$/` outside `<pre, code>`, positions `#preview-slash-menu` at the caret clamped to the viewport, and `applyPreviewSlashItem()` replaces `/query` with the rendered DOM block, sets caret/selection cleanly, and calls `syncPreviewToEditor()`.

### 8. Interactive Typed Tables (`static/index.html:1932-2325`)
- `enhanceTables(root)` wraps every `<table>` in `.table-wrap` with `+` add-column (`.table-add-col`) on the right and `+` add-row (`.table-add-row`) on the bottom, and adds a `.col-type-btn` badge to every `<th>`.
- `COL_TYPES`: `text` (`Aa`), `number` (`#`), `currency` (`$`), `checkbox` (`☑`), `date` (`Date`).
- `inferColumnType(table, colIndex)` restores column types automatically from existing Markdown values & `--:` right-alignment on load.
- `setColumnType(table, colIndex, type)` updates the header badge/alignment and converts all cells in that column across every row in `<tbody>`.
- `flushTypedCell()` (driven by `document` `selectionchange` + preview `blur`) auto-formats `currency` cells (USD via `Intl.NumberFormat`) and `number` cells when leaving a cell.

### 9. Autosave & Unload Flush (`saveCurrentNote`, `scheduleAutosave`, `flushOnUnload`, `handleExport`)
- `static/index.html:1286-1350`, `1629-1645`:
  - `800ms` debounce via `scheduleAutosave()`.
  - `saveCurrentNote()` flushes preview sync, serializes concurrent saves via `saveInFlight`, updates note `updated_at`, re-sorts sidebar newest-first, and updates `#save-status`.
  - `flushOnUnload()` (`pagehide`) sends a `fetch(..., { keepalive: true })` `PUT` if `dirty`.
  - `handleExport()` awaits `saveCurrentNote()` before navigating to `/api/export`.
